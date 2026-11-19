"""feeds.toml: which feeds to publish."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from . import STATE_NAME

FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*\.xml$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Feed:
    file: str
    title: str
    tags: str
    min_points: int = 0
    min_comments: int = 0
    window_hours: int = 48
    max_items: int = 150
    ranked: bool = False  # only stories in HN's current ranking (topstories)

    @property
    def follows_front_page(self) -> bool:
        return "front_page" in self.tags.split(",")


@dataclass(frozen=True)
class Digest:
    """One item per UTC day with that day's top stories."""

    file: str
    title: str
    top: int = 20  # stories per day
    days: int = 7  # days kept
    publish_hour: int = 6  # UTC hour of the next day when a day's item appears


@dataclass(frozen=True)
class Config:
    feeds: list[Feed]
    digests: list[Digest]

    @property
    def files(self) -> list[str]:
        return [f.file for f in self.feeds] + [d.file for d in self.digests]


REQUIRED = ("file", "title", "tags")
FLAGS = ("ranked",)
KNOWN = {f.name for f in fields(Feed)}
NUMBERS = KNOWN - set(REQUIRED) - set(FLAGS)
DIGEST_KNOWN = {f.name for f in fields(Digest)}


def _check_file(where: str, file: object, used: list[str]) -> None:
    if not isinstance(file, str) or not FILE_RE.match(file) or file == STATE_NAME:
        raise ConfigError(f"{where}: file must be a lowercase name ending in .xml, not {file!r}")
    if file in used:
        raise ConfigError(f"{where}: {file} is already used by another feed")


def _parse_digest(where: str, table: dict, used: list[str]) -> Digest:
    unknown = set(table) - DIGEST_KNOWN
    if unknown:
        raise ConfigError(f"{where}: unknown keys: {', '.join(sorted(unknown))}")
    missing = [k for k in ("file", "title") if k not in table]
    if missing:
        raise ConfigError(f"{where}: missing {', '.join(missing)}")
    if not isinstance(table["title"], str) or not table["title"].strip():
        raise ConfigError(f"{where}: title must be a non-empty string")
    for key, low, high in (("top", 1, 100), ("days", 1, 60), ("publish_hour", 0, 23)):
        value = table.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high):
            raise ConfigError(f"{where}: {key} must be a whole number from {low} to {high}")
    _check_file(where, table["file"], used)
    return Digest(**table)


def parse(text: str) -> Config:
    """The feeds a feeds.toml declares. Raises ConfigError on anything it doesn't expect."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"not valid TOML: {e}") from e
    unknown = set(data) - {"feed", "digest"}
    if unknown:
        raise ConfigError(f"unknown top-level keys: {', '.join(sorted(unknown))}")
    tables = data.get("feed", [])
    digest_tables = data.get("digest", [])
    if not isinstance(tables, list) or not isinstance(digest_tables, list) or not (tables or digest_tables):
        raise ConfigError("no [[feed]] or [[digest]] tables")

    feeds: list[Feed] = []
    used: list[str] = []
    for n, table in enumerate(tables, 1):
        where = f"feed #{n}"
        unknown = set(table) - KNOWN
        if unknown:
            raise ConfigError(f"{where}: unknown keys: {', '.join(sorted(unknown))}")
        missing = [k for k in REQUIRED if k not in table]
        if missing:
            raise ConfigError(f"{where}: missing {', '.join(missing)}")
        for key in REQUIRED:
            if not isinstance(table[key], str) or not table[key].strip():
                raise ConfigError(f"{where}: {key} must be a non-empty string")
        for key in NUMBERS:
            value = table.get(key)
            # bool is an int subclass: reject it explicitly.
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ConfigError(f"{where}: {key} must be a whole number of at least 0")
        for key in FLAGS:
            if key in table and not isinstance(table[key], bool):
                raise ConfigError(f"{where}: {key} must be true or false")
        feed = Feed(**table)
        _check_file(where, feed.file, used)
        if feed.window_hours < 1 or feed.max_items < 1:
            raise ConfigError(f"{where}: window_hours and max_items must be at least 1")
        feeds.append(feed)
        used.append(feed.file)
    digests = []
    for n, table in enumerate(digest_tables, 1):
        digest = _parse_digest(f"digest #{n}", table, used)
        digests.append(digest)
        used.append(digest.file)
    return Config(feeds, digests)


def load(path: Path) -> Config:
    return parse(path.read_text(encoding="utf-8"))
