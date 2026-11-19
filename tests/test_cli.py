import datetime as dt
import json
import xml.etree.ElementTree as ET
from email.utils import format_datetime

from conftest import FakeResponse, hit

from hackernews_rss import cli
from hackernews_rss.source import API, FIREBASE

PAGE = "https://site.example/"
CONFIG = """
[[feed]]
file = "frontpage.xml"
title = "Front"
tags = "front_page"

[[feed]]
file = "best.xml"
title = "Best"
tags = "story"
min_points = 100
"""
OG = '<head><meta property="og:image" content="/i.png"><meta property="og:description" content="Desc {n}"></head>'


def setup(tmp_path, web, now):
    config = tmp_path / "feeds.toml"
    config.write_text(CONFIG)
    t = int(now.timestamp())
    web.json(API + "search?", {"hits": [hit(1, points=150, created=t - 600), hit(2, points=20, created=t - 300)]})
    web.json(
        API + "search_by_date?", {"hits": [hit(1, points=150, created=t - 600), hit(3, points=300, created=t - 900)]}
    )
    for n in (1, 2):
        web.html(f"https://example.com/{n}", OG.format(n=n))
    web.status("https://example.com/3", 403)
    web.json(FIREBASE + "item/1.json", {"kids": [11]})
    web.json(FIREBASE + "item/11.json", {"by": "alice", "text": "First! <i>really</i>"})
    web.json(FIREBASE + "item/", {"kids": []})  # the other stories: no comments yet
    return config


def build(config, out, *extra):
    return cli.main(["build", "--config", str(config), "--output-dir", str(out), "--page-url", PAGE, *extra])


def guids(path):
    return [i.findtext("guid").rsplit("=", 1)[1] for i in ET.parse(path).getroot().iter("item")]


def test_build_writes_every_feed_and_reuses_the_state(tmp_path, web, capsys):
    now = dt.datetime.now(dt.UTC)
    config = setup(tmp_path, web, now)
    out = tmp_path / "public"

    assert build(config, out, "--previous-state", "") == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "best.xml",
        "favicon.svg",
        "frontpage.xml",
        "icon.png",
        "index.html",
        "state.json",
    ]
    assert guids(out / "frontpage.xml") == ["2", "1"]
    assert guids(out / "best.xml") == ["1", "3"]
    front = (out / "frontpage.xml").read_text()
    assert (out / "icon.png").read_bytes().startswith(b"\x89PNG")
    assert "https://example.com/i.png" in front
    assert "Desc 1" in front
    log = capsys.readouterr().out
    assert "previews: fetched 2 new, 1 failed" in log
    assert "https://example.com/3: HTTPError: HTTP Error 403" in log
    assert "best.xml: 2 items, 1 with an image, 1 with an excerpt" in log
    assert "top comments: looked up 3, 0 failed" in log
    assert "💬 &lt;b&gt;alice&lt;/b&gt;: First! really" in front
    # One request per distinct query, one per page.
    assert sum(r.startswith(API) for r in web.requests) == 2

    # The next run reads the published state: nothing is fetched again,
    # and the 403 is not retried.
    web.requests.clear()
    web.routes[PAGE + "state.json"] = lambda: FakeResponse((out / "state.json").read_bytes(), "application/json")
    assert build(config, tmp_path / "next") == 0
    assert [r for r in web.requests if not r.startswith(API)] == [PAGE + "state.json"]
    log = capsys.readouterr().out
    assert "previews: fetched 0 new, 0 failed" in log
    assert "top comments: looked up 0, 0 failed" in log  # checked less than COMMENT_INTERVAL ago
    state = json.loads((tmp_path / "next" / "state.json").read_bytes())
    assert set(state["stories"]) == {"1", "2", "3"}


def test_build_rejects_a_bad_config(tmp_path, capsys):
    config = tmp_path / "feeds.toml"
    config.write_text("[[feed]]\nfile = 'x.xml'\n")
    assert build(config, tmp_path / "out") == 2
    assert "feed #1: missing title, tags" in capsys.readouterr().err


def feed_doc(built):
    return f"<rss><channel><lastBuildDate>{format_datetime(built)}</lastBuildDate></channel></rss>".encode()


def check(config, *extra):
    return cli.main(["check", "--config", str(config), "--page-url", PAGE, *extra])


def test_check_passes_on_fresh_feeds(tmp_path, web, capsys):
    config = tmp_path / "feeds.toml"
    config.write_text(CONFIG)
    built = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    for name in ("frontpage.xml", "best.xml"):
        web.routes[PAGE + name] = lambda: FakeResponse(feed_doc(built), "application/rss+xml")
    assert check(config) == 0
    assert "1.0 hours ago (limit 3)" in capsys.readouterr().out


def test_check_fails_on_a_stale_or_missing_feed(tmp_path, web, capsys):
    config = tmp_path / "feeds.toml"
    config.write_text(CONFIG)
    stale = dt.datetime.now(dt.UTC) - dt.timedelta(hours=5)
    web.routes[PAGE + "frontpage.xml"] = lambda: FakeResponse(feed_doc(stale), "application/rss+xml")
    web.status(PAGE + "best.xml", 404)
    assert check(config, "--max-age-hours", "4.5") == 1
    err = capsys.readouterr().err
    assert "5.0 hours ago (limit 4.5)" in err
    assert "best.xml: HTTP Error 404" in err


RANKED_CONFIG = """
[[feed]]
file = "top.xml"
title = "Top"
tags = "story"
min_points = 150
ranked = true
max_items = 2
"""


def test_ranked_feed_keeps_ranked_stories_in_rank_order(tmp_path, web):
    config = tmp_path / "feeds.toml"
    config.write_text(RANKED_CONFIG)
    now = int(dt.datetime.now(dt.UTC).timestamp())
    web.json(FIREBASE + "topstories.json", [30, 10, 20, 40])
    # Algolia answers the id query with the ranked stories that have 150+
    # points, in its own order. 40 is ranked last and falls off max_items.
    web.json(
        API + "search?",
        {
            "hits": [
                hit(10, points=200, created=now - 3 * 86400),
                hit(30, points=160, created=now - 600),
                hit(40, points=999, created=now - 60),
            ]
        },
    )
    for n in (10, 30, 40):
        web.html(f"https://example.com/{n}", "<head></head>")
    assert build(config, tmp_path / "out", "--previous-state", "") == 0
    # 10 is three days old but still ranked: it stays, as with the bot.
    assert guids(tmp_path / "out" / "top.xml") == ["30", "10"]
    (query,) = [r for r in web.requests if r.startswith(API)]
    assert "story_30" in query and "story_40" in query and "points%3E%3D150" in query


def test_digest_publishes_due_days_once(tmp_path, web, capsys):
    config = tmp_path / "feeds.toml"
    config.write_text('[[digest]]\nfile = "digest.xml"\ntitle = "Daily"\ntop = 1\ndays = 2\n')
    web.json(API + "search?", {"hits": [hit(5, points=10), hit(6, points=90)]})
    web.html("https://example.com/6", OG.format(n=6))
    out = tmp_path / "out"
    assert build(config, out, "--previous-state", "") == 0
    items = ET.parse(out / "digest.xml").getroot().findall("channel/item")
    assert 1 <= len(items) <= 2  # yesterday only once past 06:00 UTC
    assert all("Desc 6" in i.findtext("description") for i in items)
    day_queries = [r for r in web.requests if r.startswith(API)]
    assert len(day_queries) == len(items)
    assert "digest.xml: published" in capsys.readouterr().out

    web.requests.clear()
    web.routes[PAGE + "state.json"] = lambda: FakeResponse((out / "state.json").read_bytes(), "application/json")
    assert build(config, tmp_path / "again") == 0
    assert not [r for r in web.requests if r.startswith(API)]  # frozen: never asked again
    assert "previews: fetched 0 new" in capsys.readouterr().out
    assert "digest.xml" in (tmp_path / "again" / "index.html").read_text()


def test_stories_no_longer_listed_get_fresh_counts(tmp_path, web, capsys):
    config = tmp_path / "feeds.toml"
    config.write_text('[[feed]]\nfile = "f.xml"\ntitle = "F"\ntags = "front_page"\n')
    now = int(dt.datetime.now(dt.UTC).timestamp())
    web.json(API + "search?tags=front_page", {"hits": [hit(1, points=10, created=now), hit(2, created=now)]})
    for n in (1, 2):
        web.html(f"https://example.com/{n}", "<head></head>")
    web.json(FIREBASE + "item/", {"kids": []})
    out = tmp_path / "out"
    assert build(config, out, "--previous-state", "") == 0

    # Story 1 drops off the front page; the id query reports its new count.
    web.json(API + "search?tags=front_page", {"hits": [hit(2, created=now)]})
    web.json(API + "search?tags=story%2C%28story_1%29", {"hits": [hit(1, points=321, created=now)]})
    assert build(config, tmp_path / "next", "--previous-state", str(out / "state.json")) == 0
    assert "321 points" in (tmp_path / "next" / "f.xml").read_text()
    assert "counts: refreshed 1 stories no longer listed" in capsys.readouterr().out
