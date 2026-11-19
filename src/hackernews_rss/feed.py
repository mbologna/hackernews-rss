"""RSS 2.0 output, shaped like hnrss: the link is the article, <comments> is the HN thread."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import format_datetime, parsedate_to_datetime
from html import escape
from urllib.parse import urlsplit

from .config import Feed
from .preview import Preview
from .state import Entry

ATOM = "http://www.w3.org/2005/Atom"
DC = "http://purl.org/dc/elements/1.1/"
MEDIA = "http://search.yahoo.com/mrss/"
for prefix, uri in (("atom", ATOM), ("dc", DC), ("media", MEDIA)):
    ET.register_namespace(prefix, uri)


def domain(url: str | None) -> str | None:
    host = urlsplit(url).hostname if url else None
    return host.removeprefix("www.") if host else None


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


HOT = 4 * 3600  # hackernewsbot's 🔥: at most 4 hours old
COLD = 2 * 86400  # and its ❄️: at least 2 days old


def ago(seconds: int) -> str:
    if seconds < 60:
        return "just now"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            return plural(seconds // size, unit) + " ago"
    raise AssertionError("unreachable")  # pragma: no cover


def age_line(created: int, now: int) -> str:
    """The story's age as on HN, with hackernewsbot's 🔥 (new) and ❄️ (old) markers."""
    elapsed = max(0, now - created)
    marker = "🔥 " if elapsed <= HOT else "❄️ " if elapsed >= COLD else ""
    return marker + ago(elapsed)


def item_html(entry: Entry, now: int) -> str:
    """The item body: image, source, excerpt, the submitter's text, then links, counts and age."""
    story, preview = entry.story, entry.preview or Preview()
    parts = []
    if preview.image:
        parts.append(f'<p><img src="{escape(preview.image)}" alt=""></p>')
    source = preview.site_name or domain(story.url)
    if source:
        parts.append(f"<p><b>{escape(source)}</b></p>")
    if preview.description:
        parts.append(f"<p>{escape(preview.description)}</p>")
        if story.text:  # Show HN and the like: the page and the submitter's own words
            parts.append(f"<blockquote>{escape(story.text)}</blockquote>")
    elif story.text:
        parts.append(f"<p>{escape(story.text)}</p>")
    stats = [f'<a href="{escape(story.url)}">Article</a>'] if story.url else []
    stats.append(f'<a href="{escape(story.comments_url)}">{plural(story.comments, "comment")}</a>')
    stats.append(plural(story.points, "point"))
    age = age_line(story.created, now)
    stats.append(f"{age} by {escape(story.author)}" if story.author else age)
    parts.append("<p>" + " · ".join(stats) + "</p>")
    return "\n".join(parts)


def utc(timestamp: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(timestamp, dt.UTC)


def render_feed(feed: Feed, items: list[tuple[Entry, int]], feed_url: str, page_url: str, now: dt.datetime) -> bytes:
    """The feed document. items pairs each entry with when the feed first listed it, newest first.

    pubDate is that first-listed time, not the story's age: a story that
    crosses min_points a day after it was posted is news to this feed now, and
    a reader sorting by date should show it at the top.
    """
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = feed.title
    ET.SubElement(channel, "link").text = page_url
    ET.SubElement(channel, "description").text = f"{feed.title}, with each linked page's image and excerpt"
    ET.SubElement(channel, f"{{{ATOM}}}link", {"href": feed_url, "rel": "self", "type": "application/rss+xml"})
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(now)
    ET.SubElement(channel, "generator").text = "hackernews-rss"
    ET.SubElement(channel, "ttl").text = "30"
    for entry, first_seen in items:
        story = entry.story
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = story.title
        ET.SubElement(item, "link").text = story.url or story.comments_url
        ET.SubElement(item, "description").text = item_html(entry, int(now.timestamp()))
        ET.SubElement(item, "comments").text = story.comments_url
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = story.comments_url
        ET.SubElement(item, "pubDate").text = format_datetime(utc(first_seen))
        if story.author:
            ET.SubElement(item, f"{{{DC}}}creator").text = story.author
        image = entry.preview.image if entry.preview else None
        if image:
            ET.SubElement(item, f"{{{MEDIA}}}content", {"url": image, "medium": "image"})
            ET.SubElement(item, f"{{{MEDIA}}}thumbnail", {"url": image})
    ET.indent(rss)
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True) + b"\n"


def last_build_date(document: bytes) -> dt.datetime:
    """A feed's lastBuildDate. Raises ValueError when the document has none."""
    try:
        text = ET.fromstring(document).findtext("channel/lastBuildDate")
    except ET.ParseError as e:
        raise ValueError(f"not XML: {e}") from e
    if not text:
        raise ValueError("no lastBuildDate in the feed")
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError) as e:
        raise ValueError(f"unreadable lastBuildDate {text!r}") from e
