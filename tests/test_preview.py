from pathlib import Path

import pytest
from conftest import FakeResponse

from hackernews_rss.preview import MAX_BYTES, Preview, fetch_preview, parse_preview
from hackernews_rss.text import excerpt

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_open_graph_tags():
    p = parse_preview(fixture("og.html"), "https://example.com/blog/post")
    assert p.image == "https://example.com/images/cover.png?a=1&b=2"
    assert p.description == 'An article about "things" & stuff. Second line.'
    assert p.site_name == "Example Blog"


def test_twitter_fallback_skips_non_web_images():
    p = parse_preview(fixture("twitter.html"), "https://example.com/")
    assert p.image == "https://cdn.example.com/card.jpg"
    assert p.description == "Card description"
    assert p.site_name is None


def test_plain_description_fallback():
    p = parse_preview('<head><meta name="description" content="Plain"></head>', "https://example.com/")
    assert p == Preview(description="Plain")


def test_page_without_tags():
    assert parse_preview("<html><body>nothing</body></html>", "https://example.com/") == Preview()


def test_long_description_is_cut_at_a_word():
    long = "word " * 200
    p = parse_preview(f'<meta property="og:description" content="{long}">', "https://example.com/")
    assert p.description.endswith("word…")
    assert len(p.description) <= 300


def test_excerpt_without_spaces():
    assert excerpt("x" * 400, 10) == "x" * 9 + "…"


def test_fetch_resolves_against_the_final_url(web):
    web.html("https://short.example/a", fixture("og.html"), final_url="https://example.com/blog/post")
    p = fetch_preview("https://short.example/a")
    assert p.image == "https://example.com/images/cover.png?a=1&b=2"
    assert web.requests == ["https://short.example/a"]


def test_fetch_skips_non_html(web):
    web.html("https://example.com/paper.pdf", "%PDF-1.7", content_type="application/pdf")
    assert fetch_preview("https://example.com/paper.pdf") == Preview()


def test_fetch_decodes_the_declared_charset(web):
    body = '<meta property="og:description" content="caffè">'
    web.routes["https://example.com/latin"] = lambda: FakeResponse(
        body.encode("latin-1"), "text/html; charset=iso-8859-1", "https://example.com/latin"
    )
    assert fetch_preview("https://example.com/latin").description == "caffè"


def test_fetch_survives_an_unknown_charset(web):
    web.html("https://example.com/odd", '<meta property="og:site_name" content="Odd">', "text/html; charset=x-nope")
    assert fetch_preview("https://example.com/odd").site_name == "Odd"


def test_fetch_reads_at_most_max_bytes(web):
    head = '<meta property="og:site_name" content="Big">'
    web.html("https://example.com/big", head + "x" * (MAX_BYTES * 2))
    assert fetch_preview("https://example.com/big").site_name == "Big"


def test_fetch_raises_on_http_errors(web):
    web.status("https://example.com/gone", 404)
    with pytest.raises(OSError):
        fetch_preview("https://example.com/gone")
