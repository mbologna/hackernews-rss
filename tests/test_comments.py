import pytest

from hackernews_rss.comments import Comment, fetch_top_comment
from hackernews_rss.source import FIREBASE


def test_first_live_comment_wins(web):
    web.json(FIREBASE + "item/1.json", {"kids": [10, 11, 12, 13]})
    web.json(FIREBASE + "item/10.json", {"deleted": True})
    web.json(FIREBASE + "item/11.json", {"dead": True, "text": "flagged", "by": "troll"})
    web.json(FIREBASE + "item/12.json", {"by": "bob", "text": "<p>Good point &amp; more</p>"})
    comment = fetch_top_comment("1")
    assert comment == Comment("12", "bob", "Good point & more")
    assert comment.url == "https://news.ycombinator.com/item?id=12"
    assert FIREBASE + "item/13.json" not in web.requests


def test_gives_up_after_three_kids(web):
    web.json(FIREBASE + "item/1.json", {"kids": [10, 11, 12, 13]})
    for kid in (10, 11, 12):
        web.json(FIREBASE + f"item/{kid}.json", {"deleted": True})
    web.json(FIREBASE + "item/13.json", {"by": "late", "text": "too far"})
    assert fetch_top_comment("1") is None


def test_story_without_comments_or_missing(web):
    web.json(FIREBASE + "item/1.json", {"id": 1})
    assert fetch_top_comment("1") is None
    web.json(FIREBASE + "item/2.json", None)
    assert fetch_top_comment("2") is None


def test_network_errors_raise(web):
    web.status(FIREBASE + "item/1.json", 500)
    with pytest.raises(OSError):
        fetch_top_comment("1")
