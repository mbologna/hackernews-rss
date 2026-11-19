"""A story's top comment, from the HN Firebase API: its kids come in the order HN ranks them."""

from __future__ import annotations

from dataclasses import dataclass

from .source import FIREBASE, HN_ITEM, fetch_json
from .text import excerpt, plain_text

TRIES = 3  # kids to look at past dead or deleted ones


@dataclass(frozen=True)
class Comment:
    id: str
    author: str
    text: str  # a plain-text excerpt

    @property
    def url(self) -> str:
        return HN_ITEM + self.id


def fetch_top_comment(story_id: str) -> Comment | None:
    """The first live comment under the story, or None when it has none. Raises on network errors."""
    story = fetch_json(f"{FIREBASE}item/{story_id}.json") or {}
    for kid in story.get("kids", [])[:TRIES]:
        item = fetch_json(f"{FIREBASE}item/{kid}.json") or {}
        if item.get("dead") or item.get("deleted") or not item.get("text"):
            continue
        return Comment(id=str(kid), author=item.get("by") or "", text=excerpt(plain_text(item["text"])))
    return None
