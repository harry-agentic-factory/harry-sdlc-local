"""Categories, default rules and exclusions, the glob matcher and the restricted YAML parser.

Matcher: pattern and path are split on `/`; the pattern must cover the WHOLE path; `**` matches
0..n whole segments; `*` matches 0..n characters inside a segment (never `/`); `?` matches one
character other than `/`; `[` and `{` are literal (no classes, no braces).

`brain-map.yaml` (restricted YAML, stdlib only):

    rules:
      - "misc/**": produit
      - per-repo/**: repo
    exclude:
      - drafts/
      - "**/scratch-*.md"

Anything else is rejected with `mapping_unsupported`; an unknown category with
`mapping_invalid_category`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .gitio import BrainError

CATEGORIES: tuple[str, ...] = ("produit", "usage", "archi", "repo", "config", "cicd", "exploit", "observ")
READER_PROFILE: dict[str, str] = {
    c: ("fonctionnel" if c == "produit" else "mixte" if c == "usage" else "technique") for c in CATEGORIES
}
DEFAULT_EXCLUDES: tuple[str, ...] = (".claude/**", "hooks/**")

# Engine defaults (generic), evaluated after the project rules. First match wins;
# `cicd` comes before `exploit` on purpose.
DEFAULT_RULES: tuple[tuple[str, str], ...] = (
    ("README.md", "usage"), ("CLAUDE.md", "usage"),
    ("per-repo/**", "repo"), ("repos/**", "repo"),
    ("**/architecture*.md", "archi"), ("adr/**", "archi"),
    ("**/config*/**", "config"), ("**/config-management*.md", "config"),
    ("**/ci-cd*", "cicd"), ("**/cicd*", "cicd"),
    ("**/kubernetes*", "exploit"), ("**/deploy*/**", "exploit"),
    ("**/observ*", "observ"), ("**/monitoring*", "observ"),
    ("produit/**", "produit"), ("product/**", "produit"),
)

MAP_FILE = "brain-map.yaml"


# --- matcher ---

@lru_cache(maxsize=1024)
def _segment_regex(segment: str) -> re.Pattern:
    rx = re.escape(segment).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    return re.compile(rx)


@lru_cache(maxsize=4096)
def match_glob(pattern: str, path: str) -> bool:
    """True when `pattern` covers the whole `path` (see module docstring)."""
    pseg = pattern.split("/")
    sseg = path.split("/")
    regs = [None if s == "**" else _segment_regex(s) for s in pseg]
    memo: dict[tuple[int, int], bool] = {}

    def m(i: int, j: int) -> bool:
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(pseg):
            res = j == len(sseg)
        elif regs[i] is None:
            res = m(i + 1, j) or (j < len(sseg) and m(i, j + 1))
        else:
            res = j < len(sseg) and regs[i].fullmatch(sseg[j]) is not None and m(i + 1, j + 1)
        memo[key] = res
        return res

    return m(0, 0)


def exclude_pattern(entry: str) -> str:
    """An exclusion ending with `/` is a folder: `<entry>**`."""
    return entry + "**" if entry.endswith("/") else entry


def is_excluded(path: str, excludes: Iterable[str]) -> bool:
    return any(match_glob(exclude_pattern(e), path) for e in excludes)


def deduce(path: str, rules: Iterable[tuple[str, str]]) -> tuple[str, str] | None:
    """(category, rule pattern) of the first matching rule, or None (undecidable)."""
    for pattern, category in rules:
        if match_glob(pattern, path):
            return category, pattern
    return None


# --- restricted YAML ---

@dataclass(frozen=True)
class Mapping:
    rules: tuple[tuple[str, str], ...] = ()
    excludes: tuple[str, ...] = ()

    def effective_rules(self) -> tuple[tuple[str, str], ...]:
        """Project rules first, then the engine defaults (extension, never replacement)."""
        return self.rules + DEFAULT_RULES


_TOKEN = re.compile(r"[A-Za-z0-9_-]+")


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _scalar(text: str, fail) -> tuple[str, str]:
    """Split a leading scalar (bare or quoted) from `text`: (value, rest)."""
    text = text.strip()
    if text[:1] in ("\"", "'"):
        end = text.find(text[0], 1)
        if end < 0:
            fail()
        return text[1:end], text[end + 1:]
    return text, ""


def parse_mapping(data: bytes, source: str = MAP_FILE) -> Mapping:
    """Parse a `brain-map.yaml` document (no I/O)."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise BrainError("mapping_unsupported", f"{source}: not valid UTF-8") from e
    rules: list[tuple[str, str]] = []
    excludes: list[str] = []
    seen: set[str] = set()
    section = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        def fail(_raw=raw, _n=lineno):
            raise BrainError("mapping_unsupported", f"{source}:{_n}: {_raw.strip()[:80]}")

        body = raw.rstrip()
        indent_part = body[:len(body) - len(body.lstrip(" \t"))]
        if "\t" in indent_part:
            fail()
        line = _strip_comment(body).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            if stripped not in ("rules:", "exclude:") or stripped in seen:
                fail()
            seen.add(stripped)
            section = stripped[:-1]
            continue
        if section is None or not stripped.startswith("- "):
            fail()
        item = stripped[2:].strip()
        if not item:
            fail()
        if section == "exclude":
            glob, rest = _scalar(item, fail)
            if rest.strip() or not glob or (item[0] not in "\"'" and (": " in item or item.endswith(":"))):
                fail()
            excludes.append(glob)
            continue
        if item[0] in "\"'":
            glob, rest = _scalar(item, fail)
            rest = rest.strip()
            if not rest.startswith(":"):
                fail()
            value = rest[1:]
        else:
            glob, sep, value = item.partition(":")
            glob = glob.strip()
            if not sep:
                fail()
        category, tail = _scalar(value, fail)
        category = category.strip()
        if tail.strip() or not glob or not category or not _TOKEN.fullmatch(category):
            fail()
        if category not in CATEGORIES:
            raise BrainError("mapping_invalid_category", f"{glob}: {category}")
        rules.append((glob, category))
    return Mapping(tuple(rules), tuple(excludes))


def read_mapping_file(path: str | Path) -> Mapping:
    """Read an explicit `--map` file from disk."""
    p = Path(path).expanduser()
    try:
        data = p.read_bytes()
    except OSError as e:
        raise BrainError("mapping_not_found", f"mapping file not found: {p}") from e
    return parse_mapping(data, p.name)
