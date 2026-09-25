"""Link extraction, normalisation and resolution: the single link algorithm shared by
`lint`, `snapshot` (`links.json`), `normalize` (`broken_links`) and library callers.

Passes, in order (a span taken by a pass is masked for the next ones):
1. `md-link`: `[text](target "title")` (images `![..](..)` are masked and ignored) and reference
   definitions `[ref]: target`. A `http(s)://` / `mailto:` target is `external`.
2. `external`: bare `http://`, `https://`, `mailto:` URLs (including `<https://...>`).
3. `path-mention`: a `*.md` path token anywhere else (text, inline code, code blocks).

Normalisation of `to`: relative to the note folder (a `path-mention` falls back to the brain
root when the first form is not a note); then a leading `../<repo-name>/` is removed when
`<repo-name>` names the brain repository. A target outside the brain keeps its `../`.
"""
from __future__ import annotations

import bisect
import posixpath
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote

from . import gitio
from .notes import collect, read_blobs

_INLINE = re.compile(
    r"(!?)\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]"
    r"\(\s*(<[^<>\n]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)"
    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\)")
_REFDEF = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]*(<[^<>\n]*>|\S+)", re.MULTILINE)
_URL = re.compile(r"<?((?:https?://|mailto:)[^\s<>()\[\]\"'`]+)>?")
_MENTION = re.compile(r"(?<![\w./-])(?:\.{1,2}/)*[\w.-]+(?:/[\w.-]+)*\.md(?![\w/-])")
_EXTERNAL = ("http://", "https://", "mailto:")
_TRAILING = ".,;:!?"


def _mask(chars: list[str], start: int, end: int) -> None:
    for i in range(start, end):
        if chars[i] != "\n":
            chars[i] = " "


def _clean_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1].strip()
    return raw


def _strip_repo_prefix(path: str, repo_names: frozenset[str]) -> str:
    if path.startswith("../"):
        name, sep, rest = path[3:].partition("/")
        if sep and name in repo_names:
            return rest
    return path


def _normalise(base_dir: str, target: str) -> str:
    joined = posixpath.join(base_dir, target) if base_dir else target
    return posixpath.normpath(joined)


def note_links(path: str, data: bytes, notes: set[str], repo_names: frozenset[str]) -> list[dict]:
    """Links of one note: [{from, to, target, kind, line, resolved}] sorted by (line, column)."""
    text = data.decode("utf-8", errors="replace")
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    base_dir = posixpath.dirname(path)
    chars = list(text)
    found: list[tuple[int, dict]] = []

    def line_of(offset: int) -> int:
        return bisect.bisect_right(line_starts, offset)

    def add(offset: int, target: str, kind: str, candidates: list[str] | None) -> None:
        if kind == "external":
            to, resolved = target, None
        else:
            forms = [_strip_repo_prefix(c, repo_names) for c in candidates or []]
            to = next((f for f in forms if f in notes), forms[0])
            resolved = to in notes
        found.append((offset, {"from": path, "to": to, "target": target, "kind": kind,
                               "line": line_of(offset), "resolved": resolved}))

    def md_target(offset: int, raw: str) -> None:
        target = _clean_target(raw)
        if target.lower().startswith(_EXTERNAL):
            add(offset, target, "external", None)
            return
        bare = target.split("#", 1)[0].split("?", 1)[0]
        if not bare or not bare.endswith(".md"):
            return                                      # anchor only, image, script...: not a note
        add(offset, target, "md-link", [_normalise(base_dir, unquote(bare))])

    # 1. markdown links (inline + reference definitions)
    for m in _INLINE.finditer(text):
        if not m.group(1):
            md_target(m.start(), m.group(2))
        _mask(chars, m.start(), m.end())
    masked = "".join(chars)
    for m in _REFDEF.finditer(masked):
        md_target(m.start(), m.group(1))
        _mask(chars, m.start(), m.end())
    masked = "".join(chars)
    # 2. bare external URLs
    for m in _URL.finditer(masked):
        url = m.group(1).rstrip(_TRAILING)
        add(m.start(1), url, "external", None)
        _mask(chars, m.start(), m.end())
    masked = "".join(chars)
    # 3. path mentions
    for m in _MENTION.finditer(masked):
        target = m.group(0)
        clean = unquote(target)
        add(m.start(), target, "path-mention", [_normalise(base_dir, clean), posixpath.normpath(clean)])
    found.sort(key=lambda t: t[0])
    return [d for _, d in found]


def links_for(contents: dict[str, bytes], repo_names: frozenset[str]) -> list[dict]:
    """Links of a set of notes {path: bytes}, sorted by (from, line, column)."""
    notes = set(contents)
    out: list[dict] = []
    for path in sorted(contents):
        out.extend(note_links(path, contents[path], notes, repo_names))
    return out


def broken(links: Iterable[dict]) -> list[dict]:
    """Broken links = non external and not resolved, as {from, to, target, kind, line}."""
    return [{k: link[k] for k in ("from", "to", "target", "kind", "line")}
            for link in links if link["kind"] != "external" and link["resolved"] is False]


def extract_links(repo: str | Path, commit: str, *, excludes: Iterable[str] = (),
                  map_path: str | Path | None = None) -> list[dict]:
    """`links.json` of the brain at `commit` (any revision)."""
    brain = gitio.open_brain(repo)
    ns = collect(brain, commit, excludes=excludes, map_path=map_path)
    return links_for(read_blobs(brain, ns.notes), brain.repo_names)
