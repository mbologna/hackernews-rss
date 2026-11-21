"""Command line: build the feeds, or check the published ones' age."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.resources
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import PAGE_URL, STATE_NAME, USER_AGENT, comments, config, preview, source, state
from .feed import last_build_date, render_digest, render_feed
from .page import render_page

HEALTH_NAME = "health.json"
IMAGE_RATE_FLOOR = 0.3  # below this share of items with an image, something is blocking or broken


def feed_url(page_url: str, file: str) -> str:
    return page_url.rstrip("/") + "/" + file


def build(config_path: Path, output_dir: Path, page_url: str, previous: str, now: dt.datetime) -> None:
    """Write every configured feed, state.json and index.html into output_dir."""
    conf = config.load(config_path)
    feeds = conf.feeds
    current = state.load(previous)

    # Feeds with the same query share one request.
    responses: dict[str, list[source.Story]] = {}

    def stories(url: str) -> list[source.Story]:
        if url not in responses:
            responses[url] = source.fetch_stories(url)
        return responses[url]

    ranked = source.fetch_ranked_ids() if any(f.ranked for f in feeds) else []
    results = {}
    for feed in feeds:
        if feed.ranked:
            # In rank order, at most max_items: state.update relies on a
            # feed's results fitting in it.
            urls = source.ids_query_urls(ranked, feed.tags, source.count_filters(feed))
            rank = {str(sid): n for n, sid in enumerate(ranked)}
            matched = sorted((s for url in urls for s in stories(url)), key=lambda s: rank.get(s.id, len(rank)))
            results[feed.file] = matched[: feed.max_items]
        else:
            results[feed.file] = stories(source.query_url(feed, now))

    # Stories a feed still holds but the API no longer lists for it (off the
    # front page, unranked): refresh their counts, 100 per request.
    listed = {s.id for found in results.values() for s in found}
    unlisted = sorted({sid for seen in current.feeds.values() for sid in seen} - listed)
    for url in source.ids_query_urls(unlisted, "story", []):
        for story in stories(url):
            if story.id in current.stories:
                state.merge_story(current, story)
    print(f"counts: refreshed {len(unlisted)} stories no longer listed")

    stamp = int(now.timestamp())
    for digest in conf.digests:
        for day in state.digest_days_due(current, digest, stamp):
            start = int(dt.datetime.combine(day, dt.time(), dt.UTC).timestamp())
            state.add_digest_day(current, digest, day, stories(source.day_query_url(start, start + 86400)))
            print(f"{digest.file}: published {day.isoformat()}")
    state.update(current, feeds, results, stamp, conf.digests)
    fetched, failed = state.fetch_previews(current, preview.fetch_preview)
    print(f"previews: fetched {fetched} new, {len(failed)} failed")
    for url, error in failed:
        print(f"  {url}: {error}")
    fetched, failed = state.fetch_comments(current, comments.fetch_top_comment, listed, stamp)
    print(f"top comments: looked up {fetched}, {len(failed)} failed")
    for url, error in failed:
        print(f"  {url}: {error}")

    output_dir.mkdir(parents=True, exist_ok=True)
    health: dict = {"built": stamp, "feeds": {}, "digests": {}}
    for feed in feeds:
        seen = current.feeds[feed.file]
        items = [(current.stories[sid], t) for sid, t in seen.items()]
        document = render_feed(feed, items, feed_url(page_url, feed.file), page_url, now)
        (output_dir / feed.file).write_bytes(document)
        images = sum(1 for e, _ in items if e.preview and e.preview.image)
        excerpts = sum(1 for e, _ in items if (e.preview and e.preview.description) or e.story.text)
        print(f"{feed.file}: {len(items)} items, {images} with an image, {excerpts} with an excerpt")
        health["feeds"][feed.file] = {"items": len(items), "images": images, "excerpts": excerpts}
        if len(items) >= 10 and images < IMAGE_RATE_FLOOR * len(items):
            # A GitHub Actions annotation: shows on the run's summary page.
            print(f"::warning::{feed.file}: only {images} of {len(items)} items have an image")
    for digest in conf.digests:
        days = sorted(current.digests.get(digest.file, {}).items(), reverse=True)
        entries = [
            (dt.date.fromisoformat(day), [current.stories[sid] for sid in ids if sid in current.stories])
            for day, ids in days
        ]
        document = render_digest(digest, entries, feed_url(page_url, digest.file), page_url, now)
        (output_dir / digest.file).write_bytes(document)
        print(f"{digest.file}: {len(entries)} days")
        health["digests"][digest.file] = {"days": len(entries)}
    # For outside monitoring: when the build ran and how the feeds look.
    (output_dir / HEALTH_NAME).write_text(json.dumps(health, indent=2) + "\n", encoding="utf-8")
    (output_dir / STATE_NAME).write_bytes(current.to_json())
    # The icons: the feeds' <image> and the index page's favicon.
    for asset in importlib.resources.files("hackernews_rss").joinpath("site").iterdir():
        (output_dir / asset.name).write_bytes(asset.read_bytes())
    published: list[config.Feed | config.Digest] = [*feeds, *conf.digests]
    page = render_page([(f, feed_url(page_url, f.file)) for f in published])
    (output_dir / "index.html").write_text(page, encoding="utf-8")


def check(config_path: Path, page_url: str, max_age: dt.timedelta, now: dt.datetime) -> bool:
    """Whether every configured feed is published and was built within max_age."""
    ok = True
    for file in config.load(config_path).files:
        url = feed_url(page_url, file)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310 # the operator's own page URL
                built = last_build_date(r.read())
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"{url}: {e}", file=sys.stderr)
            ok = False
            continue
        hours = (now - built).total_seconds() / 3600
        message = (
            f"{url}: built {built:%Y-%m-%d %H:%M} UTC, {hours:.1f} hours ago (limit {max_age.total_seconds() / 3600:g})"
        )
        fresh = now - built <= max_age
        print(message, file=sys.stdout if fresh else sys.stderr)
        ok = ok and fresh
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hackernews-rss", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="write the feeds, state.json and index.html")
    b.add_argument("--config", type=Path, default=Path("feeds.toml"))
    b.add_argument("--output-dir", type=Path, default=Path("public"))
    b.add_argument("--page-url", default=PAGE_URL, help="where the site is published")
    b.add_argument(
        "--previous-state",
        help="URL or path of the previous state.json; an empty string starts fresh "
        "(default: state.json under --page-url)",
    )

    c = sub.add_parser("check", help="fail when a published feed is missing or older than --max-age-hours")
    c.add_argument("--config", type=Path, default=Path("feeds.toml"))
    c.add_argument("--page-url", default=PAGE_URL)
    c.add_argument("--max-age-hours", type=float, default=3)

    args = parser.parse_args(argv)
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)

    try:
        if args.command == "build":
            # The Pages CDN caches state.json for 10 minutes and ignores query
            # strings, so a run that starts within 10 minutes of a deploy reads
            # the state before it. That costs refetching the previews and top
            # comments of the stories the newer run added, nothing more.
            default = feed_url(args.page_url, STATE_NAME)
            previous = default if args.previous_state is None else args.previous_state
            build(args.config, args.output_dir, args.page_url, previous, now)
            return 0
        return 0 if check(args.config, args.page_url, dt.timedelta(hours=args.max_age_hours), now) else 1
    except config.ConfigError as e:
        print(f"{args.config}: {e}", file=sys.stderr)
        return 2
