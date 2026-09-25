"""`lint`: check the notes of one commit.

Errors (exit 1): `missing_category`, `invalid_category`, `frontmatter_unreadable`.
Warnings (exit 0 alone, 1 with `strict`): broken internal links, from the shared link algorithm.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from . import gitio
from .frontmatter import parse_frontmatter
from .links import broken, links_for
from .mapping import CATEGORIES
from .notes import collect, read_blobs
from .ref import resolve_in


def note_error(data: bytes) -> str | None:
    fm = parse_frontmatter(data)
    if fm.error:
        return fm.error
    if fm.category is None:
        return "missing_category"
    if fm.category not in CATEGORIES:
        return "invalid_category"
    return None


def lint(repo: str | Path, ref: str | None = None, *, excludes: Iterable[str] = (),
         map_path: str | Path | None = None, strict: bool = False) -> dict:
    """Lint the brain at `ref` (None = `HEAD`).

    Returns {commit, notes, errors:[{path, code}], warnings:[{from, to, target, kind, line}], exit}.
    """
    brain = gitio.open_brain(repo)
    commit = resolve_in(brain, ref if ref is not None else "HEAD").commit
    ns = collect(brain, commit, excludes=excludes, map_path=map_path)
    contents = read_blobs(brain, ns.notes)
    errors = []
    for path in sorted(contents):
        code = note_error(contents[path])
        if code:
            errors.append({"path": path, "code": code})
    warnings = broken(links_for(contents, brain.repo_names))
    failed = bool(errors) or (strict and bool(warnings))
    return {"commit": commit, "notes": len(contents), "errors": errors, "warnings": warnings,
            "exit": 1 if failed else 0}


def format_text(result: dict) -> str:
    lines = [f"error {e['path']}: {e['code']}" for e in result["errors"]]
    lines += [f"warning {w['from']}:{w['line']}: broken {w['kind']} -> {w['target']}"
              for w in result["warnings"]]
    lines.append(f"lint: {result['notes']} notes, {len(result['errors'])} errors, "
                 f"{len(result['warnings'])} warnings ({result['commit']})")
    return "\n".join(lines)
