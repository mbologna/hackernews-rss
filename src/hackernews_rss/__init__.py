"""Hacker News RSS feeds whose items carry the linked page's image and excerpt."""

# feeds.michelebologna.net proxies to this repo's GitHub Pages site (mbologna/infra,
# terraform/dns-michelebologna.net/feeds.tf), so subscriptions outlive the hosting.
PAGE_URL = "https://feeds.michelebologna.net/hackernews-rss/"
STATE_NAME = "state.json"
USER_AGENT = "Mozilla/5.0 (compatible; hackernews-rss; +https://github.com/mbologna/hackernews-rss)"
