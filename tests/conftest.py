"""A fake network: urlopen answers from a table of URL -> response, and fails on anything else."""

from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.request

import pytest


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8", url: str = ""):
        super().__init__(body)
        self.headers = email.message.Message()
        self.headers["Content-Type"] = content_type
        self.url = url

    def geturl(self) -> str:
        return self.url


class FakeWeb:
    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.requests: list[str] = []

    def html(self, url: str, body: str, content_type: str = "text/html; charset=utf-8", final_url: str | None = None):
        self.routes[url] = lambda: FakeResponse(body.encode("utf-8"), content_type, final_url or url)

    def json(self, url_prefix: str, data: dict):
        self.routes[url_prefix] = lambda: FakeResponse(json.dumps(data).encode(), "application/json", url_prefix)

    def error(self, url: str, exc: Exception):
        def raise_it():
            raise exc

        self.routes[url] = raise_it

    def status(self, url: str, code: int):
        self.error(url, urllib.error.HTTPError(url, code, "status", email.message.Message(), None))

    def urlopen(self, req, timeout=None):
        url = req.full_url if isinstance(req, urllib.request.Request) else req
        self.requests.append(url)
        # Exact URL first, then the longest matching prefix (API queries carry a timestamp).
        route = self.routes.get(url)
        if route is None:
            prefixes = [p for p in self.routes if url.startswith(p)]
            if not prefixes:
                raise urllib.error.URLError(f"no route for {url}")
            route = self.routes[max(prefixes, key=len)]
        return route()


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    return fake


def hit(id: int, title: str = "", url: str | None = "", points: int = 10, comments: int = 2, created: int = 0, **extra):
    """An Algolia search hit."""
    return {
        "objectID": str(id),
        "title": title or f"Story {id}",
        "url": f"https://example.com/{id}" if url == "" else url,
        "points": points,
        "num_comments": comments,
        "created_at_i": created,
        "author": f"user{id}",
        **extra,
    }
