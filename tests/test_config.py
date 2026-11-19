from pathlib import Path

import pytest

from hackernews_rss.config import ConfigError, Digest, Feed, load, parse

REPO_CONFIG = Path(__file__).parent.parent / "feeds.toml"


def test_the_repo_config_is_valid():
    conf = load(REPO_CONFIG)
    feeds = conf.feeds
    assert conf.digests == [Digest("digest.xml", "Hacker News: daily digest")]
    assert conf.files == ["frontpage.xml", "best.xml", "top.xml", "digest.xml"]
    assert [f.file for f in feeds] == ["frontpage.xml", "best.xml", "top.xml"]
    assert feeds[0].follows_front_page
    assert not feeds[1].follows_front_page
    assert feeds[1].min_points == 100
    assert feeds[2].ranked and feeds[2].min_points == 150


def test_defaults_apply():
    (feed,) = parse('[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\n').feeds
    assert feed == Feed("a.xml", "A", "story", min_points=0, min_comments=0, window_hours=48, max_items=150)
    assert not feed.ranked


def test_front_page_among_several_tags():
    (feed,) = parse('[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "front_page,show_hn"\n').feeds
    assert feed.follows_front_page


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("this is = = not toml", "not valid TOML"),
        ("", r"no \[\[feed\]\] or \[\[digest\]\] tables"),
        ('feed = "x"', r"no \[\[feed\]\] or \[\[digest\]\] tables"),
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


def test_digest_defaults_and_digest_only_config():
    conf = parse('[[digest]]\nfile = "d.xml"\ntitle = "D"\n')
    assert conf.feeds == []
    assert conf.digests == [Digest("d.xml", "D", top=20, days=7, publish_hour=6)]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[digest]]\nfile = "d.xml"', "digest #1: missing title"),
        ('[[digest]]\nfile = "d.xml"\ntitle = ""', "digest #1: title must be a non-empty string"),
        ('[[digest]]\nfile = "d.xml"\ntitle = "D"\ntags = "story"', "digest #1: unknown keys: tags"),
        ('[[digest]]\nfile = "d.xml"\ntitle = "D"\ntop = 0', "top must be a whole number from 1 to 100"),
        (
            '[[digest]]\nfile = "d.xml"\ntitle = "D"\npublish_hour = 24',
            "publish_hour must be a whole number from 0 to 23",
        ),
        ('[[digest]]\nfile = "d.xml"\ntitle = "D"\ndays = true', "days must be a whole number"),
        ('[[digest]]\nfile = "D.XML"\ntitle = "D"', "file must be a lowercase name"),
        (
            '[[feed]]\nfile = "a.xml"\ntitle = "A"\ntags = "story"\n[[digest]]\nfile = "a.xml"\ntitle = "D"',
            "digest #1: a.xml is already used",
        ),
    ],
)
def test_bad_digests_fail_with_a_message(text, message):
    with pytest.raises(ConfigError, match=message):
        parse(text)
