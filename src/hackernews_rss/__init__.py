"""Hacker News RSS feeds whose items carry the linked page's image and excerpt."""

# The feeds Worker serves this repo's GitHub Pages site on its own hostname
# (mbologna/infra, terraform/dns-michelebologna.net/feeds.tf), so subscriptions
# outlive the hosting.
PAGE_URL = "https://hackernews-rss.michelebologna.net/"
STATE_NAME = "state.json"
USER_AGENT = "Mozilla/5.0 (compatible; hackernews-rss; +https://github.com/mbologna/hackernews-rss)"
