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


REQUIRED = ("file", "title", "tags")
FLAGS = ("ranked",)
KNOWN = {f.name for f in fields(Feed)}
NUMBERS = KNOWN - set(REQUIRED) - set(FLAGS)


def parse(text: str) -> list[Feed]:
    """The feeds a feeds.toml declares. Raises ConfigError on anything it doesn't expect."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"not valid TOML: {e}") from e
    unknown = set(data) - {"feed"}
    if unknown:
        raise ConfigError(f"unknown top-level keys: {', '.join(sorted(unknown))}")
    tables = data.get("feed")
    if not isinstance(tables, list) or not tables:
        raise ConfigError("no [[feed]] tables")

    feeds: list[Feed] = []
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
        if not FILE_RE.match(feed.file) or feed.file == STATE_NAME:
            raise ConfigError(f"{where}: file must be a lowercase name ending in .xml, not {feed.file!r}")
        if feed.window_hours < 1 or feed.max_items < 1:
            raise ConfigError(f"{where}: window_hours and max_items must be at least 1")
        if any(f.file == feed.file for f in feeds):
            raise ConfigError(f"{where}: {feed.file} is already used by another feed")
        feeds.append(feed)
    return feeds


def load(path: Path) -> list[Feed]:
    return parse(path.read_text(encoding="utf-8"))
