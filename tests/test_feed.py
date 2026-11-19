import datetime as dt
import xml.etree.ElementTree as ET

import pytest

from hackernews_rss.config import Feed
from hackernews_rss.feed import ATOM, DC, MEDIA, domain, item_html, last_build_date, render_feed
from hackernews_rss.page import describe, render_page
from hackernews_rss.preview import Preview
from hackernews_rss.source import Story
from hackernews_rss.state import Entry

NOW = dt.datetime(2026, 11, 19, 12, 0, tzinfo=dt.UTC)
FEED = Feed("frontpage.xml", "Hacker News: front page", "front_page")


def story(**kw):
    base = {
        "id": "42",
        "title": 'Rust & "C" <compared>',
        "url": "https://www.example.com/post?a=1&b=2",
        "points": 150,
        "comments": 37,
        "created": 1_795_000_000,
        "author": "pg",
        "text": "",
    }
    return Story(**{**base, **kw})


def render(entries):
    doc = render_feed(FEED, entries, "https://site.example/frontpage.xml", "https://site.example/", NOW)
    return doc, ET.fromstring(doc)


def test_item_fields():
    entry = Entry(story(), Preview("https://cdn.example.com/i.png?x=1&y=2", "An excerpt <b>raw</b>", "Example"))
    doc, root = render([(entry, 1_795_001_000)])
    assert doc.startswith(b"<?xml version='1.0' encoding='utf-8'?>")
    channel = root.find("channel")
    assert channel.findtext("title") == "Hacker News: front page"
    assert channel.find(f"{{{ATOM}}}link").get("href") == "https://site.example/frontpage.xml"
    assert channel.findtext("lastBuildDate") == "Thu, 19 Nov 2026 12:00:00 +0000"
    item = channel.find("item")
    assert item.findtext("title") == 'Rust & "C" <compared>'
    assert item.findtext("link") == "https://www.example.com/post?a=1&b=2"
    assert item.findtext("comments") == "https://news.ycombinator.com/item?id=42"
    guid = item.find("guid")
    assert (guid.text, guid.get("isPermaLink")) == ("https://news.ycombinator.com/item?id=42", "false")
    assert item.findtext("pubDate") == "Wed, 18 Nov 2026 11:23:20 +0000"
    assert item.findtext(f"{{{DC}}}creator") == "pg"
    assert item.find(f"{{{MEDIA}}}thumbnail").get("url") == "https://cdn.example.com/i.png?x=1&y=2"
    assert item.find(f"{{{MEDIA}}}content").get("medium") == "image"


def test_item_html_escapes_and_links():
    entry = Entry(story(), Preview("https://cdn.example.com/i.png?x=1&y=2", "An excerpt <b>raw</b>", "Example"))
    assert item_html(entry) == (
        '<p><img src="https://cdn.example.com/i.png?x=1&amp;y=2" alt=""></p>\n'
        "<p><b>Example</b></p>\n"
        "<p>An excerpt &lt;b&gt;raw&lt;/b&gt;</p>\n"
        '<p><a href="https://www.example.com/post?a=1&amp;b=2">Article</a> · '
        '<a href="https://news.ycombinator.com/item?id=42">37 comments</a> · 150 points</p>'
    )


def test_item_without_preview_shows_the_domain():
    html = item_html(Entry(story(points=1, comments=1)))
    assert "<img" not in html
    assert "<p><b>example.com</b></p>" in html
    assert "1 comment</a> · 1 point</p>" in html


def test_ask_hn_item_links_the_thread_and_shows_its_text():
    entry = Entry(story(url=None, text="What do you use?"), Preview())
    _, root = render([(entry, 1_795_001_000)])
    item = root.find("channel/item")
    assert item.findtext("link") == "https://news.ycombinator.com/item?id=42"
    assert item.find(f"{{{MEDIA}}}content") is None
    html = item.findtext("description")
    assert "Article" not in html
    assert "<p>What do you use?</p>" in html


def test_items_keep_the_given_order():
    entries = [(Entry(story(id=str(i))), 1_795_000_000 - i) for i in range(3)]
    _, root = render(entries)
    assert [i.findtext("guid")[-1] for i in root.iter("item")] == ["0", "1", "2"]


def test_domain():
    assert domain("https://www.github.com/x") == "github.com"
    assert domain(None) is None
    assert domain("not a url") is None


def test_last_build_date_round_trip():
    doc, _ = render([])
    assert last_build_date(doc) == NOW


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        (b"<html>", "not XML"),
        (b"<rss><channel></channel></rss>", "no lastBuildDate"),
        (b"<rss><channel><lastBuildDate>yesterday</lastBuildDate></channel></rss>", "unreadable lastBuildDate"),
    ],
)
def test_last_build_date_errors(doc, message):
    with pytest.raises(ValueError, match=message):
        last_build_date(doc)


def test_page_lists_feeds():
    best = Feed("best.xml", "Best <100+>", "story", min_points=100, min_comments=3)
    page = render_page([(FEED, "https://site.example/frontpage.xml"), (best, "https://site.example/best.xml")])
    assert '<a href="https://site.example/best.xml">Best &lt;100+&gt;</a>' in page
    assert "<code>https://site.example/frontpage.xml</code>" in page
    assert describe(FEED) == "the current front page, kept 48 hours, up to 150 items"
    assert (
        describe(best)
        == "newest stories tagged story, at least 100 points, at least 3 comments, kept 48 hours, up to 150 items"
    )
