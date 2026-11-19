from pathlib import Path

import pytest

from hackernews_rss.config import ConfigError, Feed, load, parse

REPO_CONFIG = Path(__file__).parent.parent / "feeds.toml"


def test_the_repo_config_is_valid():
    feeds = load(REPO_CONFIG)
    assert [f.file for f in feeds] == ["frontpage.xml", "best.xml", "top.xml"]
    assert feeds[0].follows_front_page
    assert not feeds[1].follows_front_page
    assert feeds[1].min_points == 100
    assert feeds[2].ranked and feeds[2].min_points == 150


def test_defaults_apply():
    (feed,) = parse('[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\n')
    assert feed == Feed("a.xml", "A", "story", min_points=0, min_comments=0, window_hours=48, max_items=150)
    assert not feed.ranked


def test_front_page_among_several_tags():
    (feed,) = parse('[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "front_page,show_hn"\n')
    assert feed.follows_front_page


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("this is = = not toml", "not valid TOML"),
        ("", r"no \[\[feed\]\] tables"),
        ('feed = "x"', r"no \[\[feed\]\] tables"),
        ('other = 1\n[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"', "unknown top-level keys: other"),
        ('[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\nmin_point = 5', "feed #1: unknown keys: min_point"),
        ('[[feed]]\nfile = "a.xml"\ntags = "story"', "feed #1: missing title"),
        ('[[feed]]\nfile = "a.xml"\ntitle = " "\ntags = "story"', "title must be a non-empty string"),
        ('[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\nmin_points = -1', "min_points must be a whole number"),
        (
            '[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\nmin_points = "100"',
            "min_points must be a whole number",
        ),
        ('[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\nmax_items = true', "max_items must be a whole number"),
        ('[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\nwindow_hours = 0', "must be at least 1"),
        ('[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\nranked = 1', "ranked must be true or false"),
        ('[[feed]]\nfile = "../a.xml"\ntitle = "A"\ntags = "story"', "file must be a lowercase name ending in .xml"),
        ('[[feed]]\nfile = "index.html"\ntitle = "A"\ntags = "story"', "file must be a lowercase name ending in .xml"),
        (
            '[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\n[[feed]]\nfile = "a.xml"\ntitle = "B"\ntags = "ask_hn"',
            "feed #2: a.xml is already used",
        ),
    ],
)
def test_bad_configs_fail_with_a_message(text, message):
    with pytest.raises(ConfigError, match=message):
        parse(text)
