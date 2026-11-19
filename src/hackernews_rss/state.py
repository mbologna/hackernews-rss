"""What the previous run published: each story with its preview, and when each feed first saw it.

The state travels with the site. Each run reads state.json from the published
site and deploys the updated copy next to the feeds, so it needs no commits
and no cache. Losing it only costs fetching the previews again.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import USER_AGENT
from .comments import Comment
from .config import Digest, Feed
from .preview import Preview
from .source import Story

VERSION = 1
MAX_ATTEMPTS = 3  # preview fetches per story before giving up on it
COMMENT_INTERVAL = 2 * 3600  # how often a listed story's top comment is looked up again
RETRY_STATUSES = {408, 429}  # client errors worth another try; other 4xx won't change


@dataclass
class Entry:
    story: Story
    preview: Preview | None = None  # None until a fetch succeeds
    attempts: int = 0
    comment: Comment | None = None  # the top comment when last looked up
    comment_checked: int = 0  # Unix time of that lookup; 0 = never

    @property
    def wants_preview(self) -> bool:
        return self.preview is None and self.attempts < MAX_ATTEMPTS


@dataclass
class State:
    stories: dict[str, Entry] = field(default_factory=dict)
    # Feed file -> story id -> Unix time the feed first listed the story.
    feeds: dict[str, dict[str, int]] = field(default_factory=dict)
    # Digest file -> UTC day (YYYY-MM-DD) -> its top story ids, frozen once published.
    digests: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def to_json(self) -> bytes:
        data = {
            "version": VERSION,
            "stories": {
                sid: {
                    "story": asdict(e.story),
                    "preview": asdict(e.preview) if e.preview else None,
                    "attempts": e.attempts,
                    "comment": asdict(e.comment) if e.comment else None,
                    "comment_checked": e.comment_checked,
                }
                for sid, e in self.stories.items()
            },
            "feeds": self.feeds,
            "digests": self.digests,
        }
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> State:
        """Raises ValueError on anything that isn't a state file of this version."""
        try:
            data = json.loads(raw)
            if data.get("version") != VERSION:
                raise ValueError(f"state version {data.get('version')!r}, expected {VERSION}")
            stories = {
                sid: Entry(
                    story=Story(**e["story"]),
                    preview=Preview(**e["preview"]) if e["preview"] is not None else None,
                    attempts=int(e["attempts"]),
                    # Added after the first release: absent from older state files.
                    comment=Comment(**e["comment"]) if e.get("comment") else None,
                    comment_checked=int(e.get("comment_checked", 0)),
                )
                for sid, e in data["stories"].items()
            }
            feeds = {f: {sid: int(t) for sid, t in seen.items()} for f, seen in data["feeds"].items()}
            # Added with the digests: absent from older state files.
            digests = {
                f: {day: [str(sid) for sid in ids] for day, ids in days.items()}
                for f, days in data.get("digests", {}).items()
            }
        except (AttributeError, KeyError, TypeError) as e:
            raise ValueError(f"malformed state: {e!r}") from e
        return cls(stories, feeds, digests)


def load(source: str) -> State:
    """The state at a URL or path; empty when source is empty, missing or unreadable."""
    if not source:
        return State()
    try:
        if source.startswith(("http://", "https://")):
            req = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
        else:
            raw = Path(source).read_bytes()
        return State.from_json(raw)
    except (OSError, ValueError) as e:
        print(f"previous state {source}: {e}; starting empty", file=sys.stderr)
        return State()


def merge_story(state: State, story: Story) -> None:
    """Add a story, or refresh the one the state has."""
    entry = state.stories.get(story.id)
    if entry is None:
        state.stories[story.id] = Entry(story)
        return
    if entry.story.url != story.url:  # the link was edited: its preview no longer applies
        entry.preview, entry.attempts = None, 0
    entry.story = story


def utc_day(timestamp: int) -> dt.date:
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).date()


def publish_time(digest: Digest, day: dt.date) -> int:
    """When a digest publishes a day: publish_hour (UTC) on the next day."""
    moment = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(digest.publish_hour), dt.UTC)
    return int(moment.timestamp())


def digest_days_due(state: State, digest: Digest, now: int) -> list[dt.date]:
    """The days within the digest's window that are due but not yet published, oldest first."""
    published = state.digests.get(digest.file, {})
    today = utc_day(now)
    days = [today - dt.timedelta(days=n) for n in range(digest.days, 0, -1)]
    return [d for d in days if d.isoformat() not in published and publish_time(digest, d) <= now]


def add_digest_day(state: State, digest: Digest, day: dt.date, stories: list[Story]) -> None:
    """Freeze the day's top stories by points, and add them to the state."""
    top = sorted(stories, key=lambda s: s.points, reverse=True)[: digest.top]
    for story in top:
        merge_story(state, story)
    state.digests.setdefault(digest.file, {})[day.isoformat()] = [s.id for s in top]


def update(
    state: State, feeds: list[Feed], results: dict[str, list[Story]], now: int, digests: list[Digest] = ()
) -> None:
    """Merge this run's stories into the state, then drop what no feed or digest keeps."""
    for feed in feeds:
        cutoff = now - feed.window_hours * 3600
        # A feed with no history (new, or the state was lost) dates its first
        # batch by when each story was posted, so the batch doesn't all share
        # one timestamp. Readers match items by guid, so re-dating stories
        # they already have doesn't make them new again.
        fresh = feed.file not in state.feeds
        seen = state.feeds.setdefault(feed.file, {})
        for story in results[feed.file]:
            merge_story(state, story)
            seen.setdefault(story.id, min(now, story.created) if fresh else now)
        # A story the source still returns stays, however old: Algolia's
        # front_page tag can list stories posted days ago, and dropping one
        # while it is still listed would add it back on the next run. The
        # window times out only the stories that no longer match.
        current = {story.id for story in results[feed.file]}
        kept = [sid for sid, t in seen.items() if sid in state.stories and (sid in current or t >= cutoff)]
        # The cap keeps the listed stories first, for the same reason. A query
        # asks for at most max_items hits, so they always fit.
        kept.sort(key=lambda sid: (sid in current, seen[sid]), reverse=True)
        kept = kept[: feed.max_items]
        kept.sort(key=lambda sid: (seen[sid], state.stories[sid].story.created), reverse=True)
        state.feeds[feed.file] = {sid: seen[sid] for sid in kept}

    configured = {f.file for f in feeds}
    state.feeds = {f: seen for f, seen in state.feeds.items() if f in configured}
    today = utc_day(now)
    kept_days = {}
    for digest in digests:
        oldest = (today - dt.timedelta(days=digest.days)).isoformat()
        days = state.digests.get(digest.file, {})
        kept_days[digest.file] = {day: ids for day, ids in days.items() if day >= oldest}
    state.digests = kept_days
    listed = {sid for seen in state.feeds.values() for sid in seen}
    listed |= {sid for days in state.digests.values() for ids in days.values() for sid in ids}
    state.stories = {sid: e for sid, e in state.stories.items() if sid in listed}


def fetch_previews(state: State, fetch, workers: int = 8) -> tuple[int, list[tuple[str, str]]]:
    """Fetch the previews still missing. Returns how many succeeded and the (url, error) failures."""
    todo = []
    for entry in state.stories.values():
        if not entry.wants_preview:
            continue
        if entry.story.url:
            todo.append(entry)
        else:
            entry.preview = Preview()  # nothing to fetch
    fetched, failed = 0, []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, e.story.url): e for e in todo}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                entry.preview = future.result()
                fetched += 1
            # Any error, not only network ones: one odd page must not break
            # every feed. The story keeps its title and links either way.
            except Exception as e:
                permanent = (
                    isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500 and e.code not in RETRY_STATUSES
                )
                entry.attempts = MAX_ATTEMPTS if permanent else entry.attempts + 1
                failed.append((entry.story.url, f"{type(e).__name__}: {e}"))
    return fetched, failed


def fetch_comments(
    state: State, fetch, listed: set[str], now: int, workers: int = 8
) -> tuple[int, list[tuple[str, str]]]:
    """Look up the top comment of the listed stories that have comments, at most every COMMENT_INTERVAL.

    Only stories a feed still lists: the top comment of one that has dropped
    off changes little. A failed lookup is retried on the next run.
    """
    todo = [
        e
        for sid, e in state.stories.items()
        if sid in listed and e.story.comments and now - e.comment_checked >= COMMENT_INTERVAL
    ]
    fetched, failed = 0, []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, e.story.id): e for e in todo}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                entry.comment = future.result()
            except Exception as e:  # as in fetch_previews: one bad item must not break the feeds
                failed.append((entry.story.comments_url, f"{type(e).__name__}: {e}"))
                continue
            entry.comment_checked = now
            fetched += 1
    return fetched, failed
