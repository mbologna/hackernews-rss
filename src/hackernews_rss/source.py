"""Stories from the Algolia Hacker News API, the one hnrss uses."""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import USER_AGENT
from .config import Feed
from .text import excerpt, plain_text

API = "https://hn.algolia.com/api/v1/"
HN_ITEM = "https://news.ycombinator.com/item?id="
MAX_HITS = 1000  # Algolia's hitsPerPage ceiling


@dataclass(frozen=True)
class Story:
    id: str
    title: str
    url: str | None  # None for posts without a link, such as Ask HN
    points: int
    comments: int
    created: int  # Unix time
    author: str
    text: str  # the post's own text (Ask HN and the like), as a plain-text excerpt

    @property
    def comments_url(self) -> str:
        return HN_ITEM + self.id


def query_url(feed: Feed, now: dt.datetime) -> str:
    """The API request for a feed's stories.

    A front_page feed asks for the current front page. Any other feed asks for
    the newest matching stories created within its window.
    """
    filters = []
    if feed.min_points:
        filters.append(f"points>={feed.min_points}")
    if feed.min_comments:
        filters.append(f"num_comments>={feed.min_comments}")
    params = {"tags": feed.tags, "hitsPerPage": str(min(feed.max_items, MAX_HITS))}
    if feed.follows_front_page:
        endpoint = "search"
    else:
        endpoint = "search_by_date"
        filters.append(f"created_at_i>{int(now.timestamp()) - feed.window_hours * 3600}")
    if filters:
        params["numericFilters"] = ",".join(filters)
    return API + endpoint + "?" + urllib.parse.urlencode(params)


def parse_hits(data: dict) -> list[Story]:
    stories = []
    for hit in data.get("hits", []):
        title = (hit.get("title") or "").strip()
        if not title or not hit.get("objectID"):
            continue
        stories.append(
            Story(
                id=str(hit["objectID"]),
                title=title,
                url=hit.get("url") or None,
                points=hit.get("points") or 0,
                comments=hit.get("num_comments") or 0,
                created=hit.get("created_at_i") or 0,
                author=hit.get("author") or "",
                text=excerpt(plain_text(hit.get("story_text") or "")),
            )
        )
    return stories


def fetch_stories(url: str) -> list[Story]:
    """Stories for a query_url. Raises on any failure: a feed built from a failed request would be empty."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return parse_hits(json.load(r))
