import datetime as dt
import urllib.error

import pytest
from conftest import FakeResponse

from hackernews_rss.comments import Comment
from hackernews_rss.config import Digest, Feed
from hackernews_rss.preview import Preview
from hackernews_rss.source import Story
from hackernews_rss.state import (
    COMMENT_INTERVAL,
    MAX_ATTEMPTS,
    Entry,
    State,
    add_digest_day,
    digest_days_due,
    fetch_comments,
    fetch_previews,
    load,
    publish_time,
    update,
)

HOUR = 3600
NOW = 1_800_000_000
FRONT = Feed("frontpage.xml", "Front", "front_page")
BEST = Feed("best.xml", "Best", "story", min_points=100)


def story(id, points=10, created=NOW - HOUR, url="", **kw):
    return Story(
        id=str(id),
        title=f"Story {id}",
        url=f"https://example.com/{id}" if url == "" else url,
        points=points,
        comments=1,
        created=created,
        author="a",
        text="",
        **kw,
    )


def test_a_new_feed_dates_its_first_batch_by_post_time():
    state = State()
    update(state, [FRONT], {"frontpage.xml": [story(1, created=NOW - 2 * HOUR), story(2, created=NOW - HOUR)]}, NOW)
    assert state.feeds["frontpage.xml"] == {"2": NOW - HOUR, "1": NOW - 2 * HOUR}


def test_first_batch_dates_are_never_in_the_future():
    state = State()
    update(state, [FRONT], {"frontpage.xml": [story(1, created=NOW + 60)]}, NOW)
    assert state.feeds["frontpage.xml"] == {"1": NOW}


def test_a_listed_story_older_than_the_window_stays_until_it_leaves():
    # Algolia's front_page tag can list stories posted days ago.
    state = State()
    feed = Feed("f.xml", "F", "front_page", window_hours=1)
    old = story(1, created=NOW - 50 * HOUR)
    update(state, [feed], {"f.xml": [old]}, NOW)
    update(state, [feed], {"f.xml": [old]}, NOW + HOUR)
    assert state.feeds["f.xml"] == {"1": NOW - 50 * HOUR}  # kept, and its date doesn't move
    update(state, [feed], {"f.xml": []}, NOW + 2 * HOUR)
    assert state.feeds["f.xml"] == {}


def test_later_stories_are_dated_when_the_feed_first_lists_them():
    state = State()
    update(state, [FRONT], {"frontpage.xml": [story(1)]}, NOW)
    update(state, [FRONT], {"frontpage.xml": [story(1), story(2, created=NOW - 5 * HOUR)]}, NOW + HOUR)
    assert state.feeds["frontpage.xml"] == {"2": NOW + HOUR, "1": NOW - HOUR}


def test_each_feed_keeps_its_own_first_seen_time():
    state = State()
    update(state, [FRONT, BEST], {"frontpage.xml": [story(1, points=40)], "best.xml": [story(9)]}, NOW)
    # One hour later story 1 crosses 100 points: news to best.xml now, not when it hit the front page.
    update(
        state, [FRONT, BEST], {"frontpage.xml": [story(1, points=120)], "best.xml": [story(1, points=120)]}, NOW + HOUR
    )
    assert state.feeds["frontpage.xml"]["1"] == NOW - HOUR
    assert state.feeds["best.xml"]["1"] == NOW + HOUR
    assert state.stories["1"].story.points == 120


def test_stories_leave_after_the_window_and_unlisted_stories_are_dropped():
    state = State()
    feed = Feed("f.xml", "F", "front_page", window_hours=2)
    update(state, [feed], {"f.xml": [story(1)]}, NOW)
    update(state, [feed], {"f.xml": [story(2)]}, NOW + HOUR)
    update(state, [feed], {"f.xml": []}, NOW + 3 * HOUR)
    assert list(state.feeds["f.xml"]) == ["2"]
    assert list(state.stories) == ["2"]


def test_max_items_keeps_listed_stories_before_newer_unlisted_ones():
    state = State()
    feed = Feed("f.xml", "F", "front_page", max_items=2)
    update(state, [feed], {"f.xml": [story(1, created=NOW - 3 * HOUR)]}, NOW)
    update(state, [feed], {"f.xml": [story(2)]}, NOW + HOUR)  # 1 left the list
    update(state, [feed], {"f.xml": [story(1, created=NOW - 3 * HOUR), story(3)]}, NOW + 2 * HOUR)  # 1 is back
    assert list(state.feeds["f.xml"]) == ["3", "1"]  # 2 is newer than 1 but no longer listed
    assert state.feeds["f.xml"]["1"] == NOW - 3 * HOUR


def test_max_items_keeps_the_newest():
    state = State()
    feed = Feed("f.xml", "F", "story", max_items=2)
    update(state, [feed], {"f.xml": [story(i, created=NOW - i * HOUR) for i in (1, 2, 3)]}, NOW)
    assert list(state.feeds["f.xml"]) == ["1", "2"]
    assert set(state.stories) == {"1", "2"}


def test_removed_feeds_are_forgotten():
    state = State()
    update(state, [FRONT, BEST], {"frontpage.xml": [story(1)], "best.xml": [story(2)]}, NOW)
    update(state, [FRONT], {"frontpage.xml": [story(1)]}, NOW + HOUR)
    assert list(state.feeds) == ["frontpage.xml"]
    assert list(state.stories) == ["1"]


def test_an_edited_link_drops_the_old_preview():
    state = State()
    update(state, [FRONT], {"frontpage.xml": [story(1)]}, NOW)
    state.stories["1"].preview = Preview(site_name="Old")
    update(state, [FRONT], {"frontpage.xml": [story(1, url="https://other.example/")]}, NOW + HOUR)
    assert state.stories["1"].preview is None
    update(state, [FRONT], {"frontpage.xml": [story(1, url="https://other.example/", points=99)]}, NOW + 2 * HOUR)
    assert state.stories["1"].story.points == 99


def test_round_trip():
    state = State(
        stories={
            "1": Entry(story(1), Preview("https://i.example/a.png", "desc", "Site"), 0),
            "2": Entry(story(2, url=None), None, 2),
            "3": Entry(story(3), Preview(), 0, Comment("30", "bob", "nice"), NOW),
        },
        feeds={"frontpage.xml": {"1": NOW, "2": NOW - HOUR}},
    )
    assert State.from_json(state.to_json()) == state


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        b'{"version": 99}',
        b'{"version": 1}',
        b'{"version": 1, "stories": {"1": {"story": {}}}, "feeds": {}}',
    ],
)
def test_malformed_state_is_rejected(raw):
    with pytest.raises(ValueError):
        State.from_json(raw)


def test_load_from_a_path_url_or_nothing(tmp_path, web, capsys):
    good = State(feeds={"f.xml": {}})
    path = tmp_path / "state.json"
    path.write_bytes(good.to_json())
    assert load(str(path)) == good

    web.routes["https://site.example/state.json"] = lambda: FakeResponse(good.to_json())
    assert load("https://site.example/state.json") == good

    assert load("") == State()
    web.status("https://site.example/missing.json", 404)
    assert load("https://site.example/missing.json") == State()
    path.write_bytes(b"garbage")
    assert load(str(path)) == State()
    assert "starting empty" in capsys.readouterr().err


def test_fetch_previews_retries_transient_errors_and_gives_up_on_permanent_ones():
    state = State(
        stories={
            "ok": Entry(story("ok")),
            "flaky": Entry(story("flaky")),
            "blocked": Entry(story("blocked")),
            "ask": Entry(story("ask", url=None)),
            "done": Entry(story("done"), Preview(site_name="Done")),
            "spent": Entry(story("spent"), None, MAX_ATTEMPTS),
        }
    )

    def fetch(url):
        if url.endswith("/flaky"):
            raise TimeoutError("slow")
        if url.endswith("/blocked"):
            raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
        if url.endswith("/ok"):
            return Preview(site_name="OK")
        raise AssertionError(f"unexpected fetch of {url}")

    fetched, failed = fetch_previews(state, fetch, workers=2)
    assert fetched == 1
    assert sorted(u for u, _ in failed) == ["https://example.com/blocked", "https://example.com/flaky"]
    assert state.stories["ok"].preview == Preview(site_name="OK")
    assert state.stories["ask"].preview == Preview()
    assert state.stories["flaky"].attempts == 1 and state.stories["flaky"].wants_preview
    assert state.stories["blocked"].attempts == MAX_ATTEMPTS and not state.stories["blocked"].wants_preview


def test_rate_limits_are_retried():
    state = State(stories={"1": Entry(story(1))})

    def fetch(url):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

    fetch_previews(state, fetch)
    assert state.stories["1"].attempts == 1


def test_state_files_from_before_top_comments_still_load():
    old = b'{"version":1,"stories":{"1":{"story":{"id":"1","title":"T","url":null,"points":1,"comments":0,"created":0,"author":"a","text":""},"preview":null,"attempts":0}},"feeds":{}}'
    entry = State.from_json(old).stories["1"]
    assert (entry.comment, entry.comment_checked) == (None, 0)


def test_fetch_comments_looks_up_listed_stories_with_comments_at_most_every_interval():
    state = State(
        stories={
            "new": Entry(story("new")),
            "recent": Entry(story("recent"), comment_checked=NOW - 60),
            "due": Entry(story("due"), comment=Comment("9", "x", "old"), comment_checked=NOW - COMMENT_INTERVAL),
            "quiet": Entry(Story("quiet", "T", None, 5, 0, NOW, "a", "")),
            "gone": Entry(story("gone")),
            "flaky": Entry(story("flaky")),
        }
    )
    asked = []

    def fetch(sid):
        asked.append(sid)
        if sid == "flaky":
            raise TimeoutError("slow")
        return None if sid == "due" else Comment("c" + sid, "bob", "hi")

    looked_up, failed = fetch_comments(state, fetch, {"new", "recent", "due", "quiet", "flaky"}, NOW, workers=2)
    assert sorted(asked) == ["due", "flaky", "new"]
    assert looked_up == 2
    assert failed == [("https://news.ycombinator.com/item?id=flaky", "TimeoutError: slow")]
    assert state.stories["new"].comment == Comment("cnew", "bob", "hi")
    assert state.stories["new"].comment_checked == NOW
    assert state.stories["due"].comment is None  # its comments were deleted
    assert state.stories["flaky"].comment_checked == 0  # retried next run


DIGEST = Digest("digest.xml", "Digest", top=2, days=3, publish_hour=6)


def at(day: str, hour: int = 0) -> int:
    return int(dt.datetime.combine(dt.date.fromisoformat(day), dt.time(hour), dt.UTC).timestamp())


def test_digest_days_become_due_at_the_publish_hour():
    state = State()
    assert digest_days_due(state, DIGEST, at("2026-11-19", 5)) == [dt.date(2026, 11, 16), dt.date(2026, 11, 17)]
    assert digest_days_due(state, DIGEST, at("2026-11-19", 6))[-1] == dt.date(2026, 11, 18)
    assert publish_time(DIGEST, dt.date(2026, 11, 18)) == at("2026-11-19", 6)


def test_published_days_are_frozen_and_old_ones_pruned():
    state = State()
    now = at("2026-11-19", 7)
    add_digest_day(state, DIGEST, dt.date(2026, 11, 18), [story(1, points=5), story(2, points=50), story(3, points=20)])
    assert state.digests["digest.xml"] == {"2026-11-18": ["2", "3"]}
    assert dt.date(2026, 11, 18) not in digest_days_due(state, DIGEST, now)
    state.digests["digest.xml"]["2026-11-10"] = ["9"]
    update(state, [], {}, now, [DIGEST])
    assert state.digests == {"digest.xml": {"2026-11-18": ["2", "3"]}}
    assert set(state.stories) == {"2", "3"}  # digest stories stay without any feed
    update(state, [], {}, now, [])  # the digest was removed from the config
    assert state.digests == {} and state.stories == {}


def test_digests_survive_a_round_trip_and_older_files_load():
    state = State(stories={"1": Entry(story(1))}, digests={"digest.xml": {"2026-11-18": ["1"]}})
    assert State.from_json(state.to_json()) == state
    old = b'{"version":1,"stories":{},"feeds":{}}'
    assert State.from_json(old).digests == {}
