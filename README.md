# Hacker News RSS

[![CI](https://github.com/mbologna/hackernews-rss/actions/workflows/ci.yml/badge.svg)](https://github.com/mbologna/hackernews-rss/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Hacker News RSS feeds whose items carry the linked page's image and excerpt, next to the article and comments links. [hnrss](https://github.com/hnrss/hnrss) gives you only the links. This repo builds the feeds with a scheduled GitHub Actions workflow and publishes them as static files on GitHub Pages.

**Subscribe:** <https://hackernews-rss.michelebologna.net/>

The feeds are published on GitHub Pages and served at `hackernews-rss.michelebologna.net` by a Cloudflare Worker, so the URLs above keep working wherever the files are hosted. `https://hackernews-rss.michelebologna.net/health` answers 200 `{"status":"ok",…}`, or 503 when the last build is over 3 hours old or a feed's items mostly lack an image.

| Feed | URL |
| --- | --- |
| The current front page | `https://hackernews-rss.michelebologna.net/frontpage.xml` |
| Stories with 100+ points | `https://hackernews-rss.michelebologna.net/best.xml` |
| Ranked stories with 150+ points, as the [@hacker_news_feed](https://t.me/hacker_news_feed) Telegram bot posts them | `https://hackernews-rss.michelebologna.net/top.xml` |
| A daily digest: the 20 stories with the most points of each UTC day, one item per day at 06:00 UTC | `https://hackernews-rss.michelebologna.net/digest.xml` |

Each item has:

- the title, linking to the article (Ask HN and other text posts link to the thread);
- the page's `og:image` (falling back to `twitter:image`), also as `media:thumbnail` for list views;
- the site name (or the domain) and the page's description, cut to about 300 characters. A page without a description gets its first real paragraph instead (inside `<article>` or `<main>` when it has one);
- the submitter's own text, for Show HN and other posts that have some, quoted below the page's description (or in its place);
- the top comment, as HN ranks it, cut to about 300 characters, with a link to it;
- links to the article and the HN thread, the comment count, the points, and the story's age and author, as `150 points · 🔥 2 hours ago by pg`. As in the Telegram bot, 🔥 marks a story at most 4 hours old and ❄️ one at least 2 days old;
- `<comments>` set to the HN thread, as in hnrss;
- `<category>` tags with the post kind (Show HN, Ask HN, Launch HN, Tell HN) and the linked domain, for reader filters and rules.

Each feed carries an icon (`<image>`), so readers show one next to its name.

The counts are a snapshot from when the item was built. A page that blocks bots (`403`), times out or isn't HTML gets an item without the image and excerpt.

## Feeds

[`feeds.toml`](feeds.toml) lists the feeds. Each `[[feed]]` table has:

- `file`: the published file name, ending in `.xml`.
- `title`: the feed's title.
- `tags`: [Algolia tags](https://hn.algolia.com/api) such as `front_page`, `story`, `show_hn` or `ask_hn`. A feed with `front_page` follows the current front page. Any other feed takes the newest matching stories created within its window.
- `min_points`, `min_comments`: only stories with at least that many (default 0).
- `window_hours`: how long a story stays in the feed after it first appeared there (default 48). A story the API still returns for the feed stays however old it is: Algolia's `front_page` tag sometimes lists stories posted days ago.
- `max_items`: the most items the feed holds (default 150).
- `ranked`: `true` keeps only stories in HN's current ranking, the ~500 ids of [`topstories.json`](https://github.com/HackerNews/API#new-top-and-best-stories), at any age (default `false`). This is the list [hackernewsbot](https://github.com/phil-r/hackernewsbot) reads; with `min_points = 150`, `top.xml` holds the stories it posts. The bot posts at most one story per 10 minutes; a feed doesn't need that limit.

Each `[[digest]]` table publishes one item per UTC day, listing that day's top stories by points, each with its image, excerpt and counts:

- `file`, `title`: as for a feed.
- `top`: stories per day (default 20).
- `days`: days kept (default 7).
- `publish_hour`: the UTC hour of the next day when a day appears (default 6), by when late stories have had time to score. A day's list is frozen once published.

A push to `main` republishes the feeds. An unknown key or a duplicate `file` fails the build.

An item's `pubDate` is when that feed first listed the story, not when it was posted. A story that crosses 100 points a day after it was posted is new to `best.xml` then, and a reader sorting by date shows it at the top. A new feed's first batch is the exception: it carries the stories' post times.

## How it's published

The [CI workflow](.github/workflows/ci.yml) runs the tests on every push and pull request. On `main` it then builds the feeds and deploys them to GitHub Pages:

- on every push;
- every 30 minutes (at :07 and :37), dispatched by a Cron Trigger on the Worker that serves the feeds: GitHub's own schedule ran hours late, or not at all. Those runs skip the tests;
- every Monday at 06:00 UTC, on GitHub's own schedule;
- on a manual run.

A build:

1. Reads the previous run's `state.json` from the published site. It holds every listed story with its preview, and when each feed first listed it.
2. Asks the [Algolia HN API](https://hn.algolia.com/api), the one hnrss uses, for each feed's stories. Feeds that share a query share one request. A ranked feed first reads `topstories.json` from the [HN API](https://github.com/HackerNews/API), then asks Algolia for those ids, 100 per request.
3. Then refreshes the counts of the stories a feed still holds but the API no longer lists for it (off the front page, out of the ranking), 100 per request.
4. Fetches the previews still missing, eight pages at a time: the first 512 KB of each, with a 10-second timeout. It retries a failed page on the next two runs, except for permanent errors such as `403` and `404`.
5. Looks up the top comment of every listed story that has comments, at most every 2 hours per story: the first live reply in the story's `kids` from the HN API, which lists them in HN's order.
6. Writes each feed, `state.json`, `index.html` and `health.json`, and deploys them.

`health.json` is for outside monitoring: the build time (`built`, Unix seconds) and, per feed, its item count and how many items have an image and an excerpt. When fewer than 30% of a feed's items have an image, the build also leaves a warning on the run's summary page: a sign the runner is being blocked or the page parser broke.

The generated files are never committed. Losing `state.json` only means fetching the previews again.

After deploying, the workflow fetches every published feed and fails if one is missing or its `lastBuildDate` is more than 3 hours old. If the dispatches stop, the freshness check can't notice (it runs in the same workflow); the outside check of `health.json` through the Worker does, and alerts.

## Run it yourself

The script needs Python 3.15 or later (uv, below, downloads it if the machine has none) and network access to the HN APIs and the linked pages, but no other packages. It reads the feed list from `feeds.toml` in the working directory, so start from a copy of this repo's file. With [uv](https://docs.astral.sh/uv/):

```sh
curl -O https://raw.githubusercontent.com/mbologna/hackernews-rss/main/feeds.toml
uvx --from git+https://github.com/mbologna/hackernews-rss hackernews-rss build \
  --output-dir public --page-url https://hn.example.com/ --previous-state public/state.json
```

From a clone, `uv run hackernews-rss build` takes the same options. The `build` options:

- `--config`: the feed list (default `feeds.toml`);
- `--output-dir`: where to write the feeds, `index.html`, `health.json`, `state.json` and the icons (default `public`);
- `--page-url`: the URL the folder is served from, used for the links in the feeds and on the index page (default: this site's address);
- `--previous-state`: the previous run's `state.json`, as a path or URL. Without the option the build fetches `state.json` from `--page-url`; an empty string starts fresh.

Keep the output directory between runs and point `--previous-state` at the `state.json` inside it: the build reads it before writing the new one. The digest's frozen days, the fetched previews and the time each feed first listed a story all live there. A missing or unreadable file starts an empty state, as on the first run, so every preview is fetched again.

Serve the folder with any static web server, such as nginx, Caddy or `python3 -m http.server`. The published site rebuilds every 30 minutes, at :07 and :37, from the directory that holds `feeds.toml`:

```cron
# Every 30 minutes, at :07 and :37
7,37 * * * *  cd /srv/hackernews-rss && uvx --from git+https://github.com/mbologna/hackernews-rss hackernews-rss build --output-dir /var/www/hn --page-url https://hn.example.com/ --previous-state /var/www/hn/state.json
```

Give cron the full path to `uvx` if its `PATH` does not include it. `hackernews-rss check --page-url https://hn.example.com/`, run from the same directory, exits with status 1 when a configured feed is missing or was built more than 3 hours ago (`--max-age-hours`).

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run pre-commit run --all-files  # ruff, mypy, bandit and file checks; `uv run pre-commit install` runs them on each commit

# Build into public/ against the live APIs, starting from no state
uv run hackernews-rss build --output-dir public --previous-state ''

# Check the published feeds' age
uv run hackernews-rss check --max-age-hours 3
```

The tests never touch the network: they swap `urlopen` for a table of canned responses.

Dependencies resolve only to releases at least 7 days old (`exclude-newer` in `pyproject.toml`). The script itself needs none, only the standard library.

## Versioning

`main` is what runs: every push to it, and every 30-minute dispatch, deploys the feeds to GitHub Pages. Releases follow SemVer as a changelog: the Monday run's [auto-release](https://github.com/mbologna/auto-release) tags `vX.Y.Z` from the [Conventional Commit](https://www.conventionalcommits.org/) types merged since the last tag (`feat` minor; `fix`, `perf`, `revert` patch; a breaking change major), or cuts a maintenance release when only dependency updates landed; the 30-minute dispatches never release. The tag builds and deploys nothing; its [GitHub Release](https://github.com/mbologna/hackernews-rss/releases) lists the changes. See the [versioning standard](https://github.com/mbologna/.github/blob/main/VERSIONING.md).

## License

MIT, see [LICENSE](LICENSE).
