"""Checks run by `finish` before anything is published. Read only.

- `in/` intact: `seal.json` protects `in/manifest.json` and `in/settings.json`; every other file
  under `in/` must be a file entry of the manifest with the same sha256 (neighbour subtrees
  `repos/<repo>/` are delegated to their own git check). Symbolic links are never followed.
- `rw/out/`: only `docs/<type>.md` (regular file, known type) and the content of `sources/`.
- size of each document; warnings `no_recap` and `sources_not_published`.

Only `in/` and `rw/out/` are walked: the agent's other folders are never read.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .layout import META_FILES
from .model import DOC_MAX_BYTES, DOC_TYPES, sha256


@dataclass
class CheckResult:
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)      # types to publish, sorted


def _read_regular(path: Path) -> bytes | None:
    """Bytes of a regular file, None for anything else (link, fifo, unreadable...)."""
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _walk(top: Path, prune: set[str]) -> list[tuple[str, bool]]:
    """Every non-directory entry under `top` as (relative path, is_symlink_dir).

    Symbolic links to directories are reported as entries (never descended). `prune` = relative
    directories whose content is not walked."""
    out: list[tuple[str, bool]] = []
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        rel_dir = os.path.relpath(dirpath, top)
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        keep = []
        for d in dirnames:
            rel = rel_dir + d
            if os.path.islink(os.path.join(dirpath, d)):
                out.append((rel, True))
            elif rel not in prune:
                keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            out.append((rel_dir + f, False))
    return out


def _check_in(root: Path, manifest: dict | None, res: CheckResult) -> None:
    in_dir = root / "in"
    seal = None
    try:
        seal = json.loads((root / "seal.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        res.reasons.append("seal_invalid")
    for name, key in (("manifest.json", "manifest_sha256"), ("settings.json", "settings_sha256")):
        data = _read_regular(in_dir / name)
        if data is None or not isinstance(seal, dict) or sha256(data) != seal.get(key):
            res.reasons.append(f"in_modified:{name}")
    if manifest is None:
        return
    files = {e["key"]: e for e in manifest.get("files", []) if isinstance(e, dict) and "sha256" in e}
    neighbours = {e["key"] for e in manifest.get("files", []) if isinstance(e, dict) and "commit" in e}
    seen: set[str] = set()
    for rel, is_link_dir in _walk(in_dir, neighbours):
        if is_link_dir:
            res.reasons.append(f"in_modified:{rel}")
            continue
        if rel in META_FILES:
            continue
        entry = files.get(rel)
        if entry is None:
            res.reasons.append(f"in_modified:{rel}")
            continue
        seen.add(rel)
        data = _read_regular(in_dir / rel)
        if data is None or sha256(data) != entry.get("sha256"):
            res.reasons.append(f"in_modified:{rel}")
    for key in sorted(set(files) - seen):
        res.reasons.append(f"in_modified:{key}")


def _check_out(root: Path, res: CheckResult) -> None:
    out_dir = root / "rw" / "out"
    try:
        st = os.lstat(out_dir)
    except OSError:
        res.reasons.append("unexpected_file:.")
        return
    if not stat.S_ISDIR(st.st_mode):
        res.reasons.append("unexpected_file:.")
        return
    recap_missing = False
    sources = False
    for rel, is_link_dir in _walk(out_dir, set()):
        path = out_dir / rel
        if is_link_dir or os.path.islink(path):
            res.reasons.append(f"unexpected_file:{rel}")
            continue
        parts = rel.split("/")
        if parts[0] == "sources" and len(parts) > 1:
            sources = True
            continue
        if len(parts) == 2 and parts[0] == "docs" and parts[1].endswith(".md") \
                and parts[1][:-3] in DOC_TYPES:
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode):
                res.reasons.append(f"unexpected_file:{rel}")
                continue
            if st.st_size > DOC_MAX_BYTES:
                res.reasons.append(f"too_large:{rel}")
                continue
            data = _read_regular(path)
            if data is None:
                res.reasons.append(f"unexpected_file:{rel}")
                continue
            if not any(line.strip().lower().startswith("## recap")
                       for line in data.decode("utf-8", errors="ignore").splitlines()):
                recap_missing = True
            res.docs.append(parts[1][:-3])
            continue
        res.reasons.append(f"unexpected_file:{rel}")
    try:
        if any(True for _ in os.scandir(out_dir / "sources")):
            sources = True
    except OSError:
        pass
    if recap_missing:
        res.warnings.append("no_recap")
    if sources:
        res.warnings.append("sources_not_published")


def check(root: Path, manifest: dict | None) -> CheckResult:
    """Run every check of `finish` on the workspace `root` (`manifest` = parsed `in/manifest.json`)."""
    res = CheckResult()
    _check_in(root, manifest, res)
    _check_out(root, res)
    res.reasons = sorted(set(res.reasons))
    res.warnings = sorted(set(res.warnings))
    res.docs = sorted(set(res.docs))
    return res
