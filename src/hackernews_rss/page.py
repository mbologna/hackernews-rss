"""index.html: the feeds to subscribe to."""

from __future__ import annotations

from html import escape

from .config import Feed


def describe(feed: Feed) -> str:
    if feed.ranked:
        parts = [f"stories tagged {feed.tags} in HN's current ranking"]
    elif feed.follows_front_page:
        parts = ["the current front page"]
    else:
        parts = [f"newest stories tagged {feed.tags}"]
    if feed.min_points:
        parts.append(f"at least {feed.min_points} points")
    if feed.min_comments:
        parts.append(f"at least {feed.min_comments} comments")
    parts.append(f"kept {feed.window_hours} hours, up to {feed.max_items} items")
    return ", ".join(parts)


def render_page(feeds: list[tuple[Feed, str]]) -> str:
    """feeds pairs each feed with its published URL."""
    rows = "\n".join(
        f'    <li><a href="{escape(url)}">{escape(feed.title)}</a><br>'
        f"<code>{escape(url)}</code><br><small>{escape(describe(feed))}</small></li>"
        for feed, url in feeds
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hacker News RSS</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 40rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    li {{ margin-bottom: 1rem; }}
    code {{ user-select: all; }}
  </style>
</head>
<body>
  <h1>Hacker News RSS</h1>
  <p>Hacker News feeds whose items carry the linked page's image and excerpt, plus the article and comments links.
  Rebuilt every 30 minutes. Source: <a href="https://github.com/mbologna/hackernews-rss">mbologna/hackernews-rss</a>.</p>
  <ul>
{rows}
  </ul>
</body>
</html>
"""
