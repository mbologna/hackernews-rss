"""Link previews: the image, description and site name a page declares in its <head>."""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from . import USER_AGENT
from .text import excerpt

MAX_BYTES = 512 * 1024  # the <head> comes first; no need for the whole page
HTML_TYPES = {"text/html", "application/xhtml+xml"}
IMAGE_KEYS = ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src")
DESCRIPTION_KEYS = ("og:description", "twitter:description", "description")


@dataclass(frozen=True)
class Preview:
    image: str | None = None
    description: str | None = None
    site_name: str | None = None


class _MetaParser(HTMLParser):
    """Collects <meta property|name=... content=...> up to the end of <head>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.done:
            return
        if tag == "body":
            self.done = True
            return
        if tag != "meta":
            return
        a = {k.lower(): v for k, v in attrs if v is not None}
        key = (a.get("property") or a.get("name") or "").strip().lower()
        content = (a.get("content") or "").strip()
        if key and content:
            self.meta.setdefault(key, content)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.done = True


def _first(meta: dict[str, str], keys: tuple[str, ...]) -> str | None:
    return next((meta[k] for k in keys if k in meta), None)


def parse_preview(html: str, base_url: str) -> Preview:
    parser = _MetaParser()
    parser.feed(html)
    parser.close()
    meta = parser.meta

    # The first image that resolves to a web URL: skip data: and javascript: ones.
    candidates = (urljoin(base_url, meta[k]) for k in IMAGE_KEYS if k in meta)
    image = next((u for u in candidates if urlsplit(u).scheme in ("http", "https")), None)
    description = _first(meta, DESCRIPTION_KEYS)
    site_name = meta.get("og:site_name")
    return Preview(
        image=image,
        description=excerpt(description) if description else None,
        site_name=excerpt(site_name, 80) if site_name else None,
    )


def fetch_preview(url: str, timeout: float = 10) -> Preview:
    """The page's preview. A response that isn't HTML (a PDF, an image) has none.

    Raises on network and HTTP errors, so the caller can retry on a later run.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.headers.get_content_type() not in HTML_TYPES:
            return Preview()
        body = r.read(MAX_BYTES)
        charset = r.headers.get_content_charset() or "utf-8"
        final_url = r.geturl()
    try:
        html = body.decode(charset, errors="replace")
    except LookupError:  # a charset Python doesn't know
        html = body.decode("utf-8", errors="replace")
    return parse_preview(html, final_url)
