"""Agent side of a run: `doc read`, `doc list`, `doc add`.

Only `<run>/in/manifest.json`, `<run>/in/` and `<run>/rw/out/` are used: no project, no registry,
no storage backend. This works in a container where only the run workspace is mounted.
A key is resolved only among the file entries of the manifest (never a free path).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import layout
from .model import RunError, sha256, validate_type


def run_root(run: str | os.PathLike | None = None) -> Path:
    value = run if run is not None else os.environ.get("SDLC_RUN")
    if not value:
        raise RunError("run_not_set", "pass --run <root> or set SDLC_RUN")
    return Path(os.path.abspath(os.fspath(value)))


def _manifest(root: Path) -> dict:
    try:
        data = json.loads((root / "in" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RunError("run_invalid", f"{root}: no readable in/manifest.json") from e
    if not isinstance(data, dict):
        raise RunError("run_invalid", f"{root}: in/manifest.json is not an object")
    return data


def _file_entries(man: dict) -> dict[str, dict]:
    return {e["key"]: e for e in man.get("files", [])
            if isinstance(e, dict) and isinstance(e.get("key"), str) and "sha256" in e}


def _resolve(key: str, man: dict) -> str:
    entries = _file_entries(man)
    story = (man.get("scope") or {}).get("story")
    for cand in layout.alias_candidates(key, story):
        if cand in entries:
            return cand
    available = sorted(layout.canonical_key(k) for k in entries)
    raise RunError("unknown_key", f"{key}; available: {', '.join(available)}")


def doc_read(key: str, *, run: str | os.PathLike | None = None) -> bytes:
    """Raw bytes of the document `key` of the run."""
    root = run_root(run)
    in_key = _resolve(key, _manifest(root))
    path = root / "in" / in_key
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as e:
        raise RunError("run_invalid", f"{in_key}: not a readable regular file") from e
    with os.fdopen(fd, "rb") as f:
        return f.read()


def doc_list(*, run: str | os.PathLike | None = None) -> list[dict]:
    """Every file entry of the run: `[{key, path, version}]`, sorted by key."""
    root = run_root(run)
    entries = _file_entries(_manifest(root))
    out = [{"key": layout.canonical_key(k), "path": k, "version": e.get("version")}
           for k, e in entries.items()]
    return sorted(out, key=lambda d: (d["key"], d["path"]))


def doc_add(doc_type: str, content: bytes, *, run: str | os.PathLike | None = None) -> dict:
    """Add `rw/out/<docs>/<type>.md` once (a second add of the same type is refused)."""
    validate_type(doc_type)
    root = run_root(run)
    _manifest(root)
    rel = layout.doc_rel(doc_type)
    path = root / "rw" / "out" / rel
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise RunError("run_invalid", f"{root}: rw/out/docs is missing")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError as e:
        raise RunError("doc_exists", doc_type) from e
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return {"added": doc_type, "path": str(path), "sha256": sha256(content)}
