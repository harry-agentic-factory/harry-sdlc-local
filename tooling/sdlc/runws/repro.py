"""Repro files given to a fixer run under `in/repro/`: from the trace of a published run or a folder.

Both sources give the same list of `(rel, entry, bytes)`: `rel` is the path under `in/`
(`repro/<p>.md`), `entry` the common manifest entry `{key, version, sha256, size, origin}`.
Only regular `*.md` files are kept; symbolic links are never followed.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from . import layout
from .model import RunError, sha256, validate_run_uid


def _entry(rel: str, data: bytes, version: str | None, origin: str) -> dict:
    return {"key": rel, "version": version, "sha256": sha256(data), "size": len(data), "origin": origin}


def from_trace(backend, uid: str) -> list[tuple[str, dict, bytes]]:
    """`*.md` published by the run `uid` under `out/sources/repro/` (RunError `repro_unknown`)."""
    try:
        validate_run_uid(uid)
    except RunError:
        raise RunError("repro_unknown", str(uid)) from None
    try:
        run = json.loads(backend.get(layout.run_key(uid, "run.json")).decode("utf-8"))
    except (KeyError, ValueError):
        raise RunError("repro_unknown", uid) from None
    if not isinstance(run, dict) or run.get("state") != "published":
        raise RunError("repro_unknown", uid)
    prefix = layout.repro_prefix(uid)
    out: list[tuple[str, dict, bytes]] = []
    for e in backend.list(prefix):
        rel = e["key"][len(prefix):]
        if not e["key"].startswith(prefix) or not rel.endswith(".md") or not layout.safe_segments(rel):
            continue
        data = backend.get(e["key"])
        in_rel = layout.repro_in_key(rel)
        out.append((in_rel, _entry(in_rel, data, e.get("version"), e.get("origin") or e["key"]), data))
    return sorted(out, key=lambda t: t[0])


def _read_regular(path: str) -> bytes | None:
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        return f.read()


def from_dir(path) -> list[tuple[str, dict, bytes]]:
    """Regular `*.md` files of an absolute folder, recursively (RunError `repro_dir_invalid`)."""
    p = os.fspath(path) if path is not None else ""
    try:
        is_dir = bool(p) and os.path.isabs(p) and stat.S_ISDIR(os.lstat(p).st_mode)
    except OSError:
        is_dir = False
    if not is_dir:
        raise RunError("repro_dir_invalid", str(path))
    top = os.path.normpath(p)
    out: list[tuple[str, dict, bytes]] = []
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not os.path.islink(os.path.join(dirpath, d)))
        for n in sorted(filenames):
            if not n.endswith(".md"):
                continue
            full = os.path.join(dirpath, n)
            rel = Path(full).relative_to(top).as_posix()
            data = _read_regular(full)
            if data is None or not layout.safe_segments(rel):
                continue
            in_rel = layout.repro_in_key(rel)
            out.append((in_rel, _entry(in_rel, data, None, full), data))
    if not out:
        raise RunError("repro_dir_invalid", str(path))
    return sorted(out, key=lambda t: t[0])
