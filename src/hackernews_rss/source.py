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
FIREBASE = "https://hacker-news.firebaseio.com/v0/"
HN_ITEM = "https://news.ycombinator.com/item?id="
MAX_HITS = 1000  # Algolia's hitsPerPage ceiling
ID_CHUNK = 100  # story ids per Algolia request, keeping URLs short
TEXT_LIMIT = 600  # the submitter's text, shown in full more often than not


@dataclass(frozen=True)
class Story:
    id: str
    title: str
    url: str | None  # None for posts without a link, such as Ask HN
    points: int
    comments: int
    created: int  # Unix time
    author: str
    text: str  # the submitter's own text (Ask HN, Show HN and the like), as a plain-text excerpt

    @property
    def comments_url(self) -> str:
        return HN_ITEM + self.id


def count_filters(feed: Feed) -> list[str]:
    filters = []
    if feed.min_points:
        filters.append(f"points>={feed.min_points}")
    if feed.min_comments:
        filters.append(f"num_comments>={feed.min_comments}")
    return filters


def ids_query_urls(ids: list[int], tags: str, filters: list[str]) -> list[str]:
    """Algolia requests for the given story ids that match tags and filters, ID_CHUNK ids each."""
    urls = []
    for start in range(0, len(ids), ID_CHUNK):
        chunk = ids[start : start + ID_CHUNK]
        params = {
            "tags": f"{tags},({','.join(f'story_{i}' for i in chunk)})",
            "hitsPerPage": str(len(chunk)),
        }
        if filters:
            params["numericFilters"] = ",".join(filters)
        urls.append(API + "search?" + urllib.parse.urlencode(params))
    return urls


def day_query_url(start: int, end: int) -> str:
    """The stories created in [start, end), most points first: Algolia's search ranks an empty query by points."""
    params = {"tags": "story", "numericFilters": f"created_at_i>={start},created_at_i<{end}", "hitsPerPage": "200"}
    return API + "search?" + urllib.parse.urlencode(params)


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_ranked_ids() -> list[int]:
    """HN's current ranking (up to 500 story ids), the list hackernewsbot reads."""
    ids = fetch_json(FIREBASE + "topstories.json")
    if not isinstance(ids, list):
        raise ValueError("topstories.json is not a list")
    return [i for i in ids if isinstance(i, int)]


def query_url(feed: Feed, now: dt.datetime) -> str:
    """The API request for a feed's stories.

    A front_page feed asks for the current front page. Any other feed asks for
    the newest matching stories created within its window.
    """
    filters = count_filters(feed)
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
                text=excerpt(plain_text(hit.get("story_text") or ""), TEXT_LIMIT),
            )
        )
    return stories


def fetch_stories(url: str) -> list[Story]:
    """Stories for a query_url. Raises on any failure: a feed built from a failed request would be empty."""
    return parse_hits(fetch_json(url))
