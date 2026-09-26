"""`diff`: file by file comparison, from git (two refs) or from two `manifest.json`.

One algorithm (`diff_files`) for both modes: same path + same blob = `unchanged`; same path,
other blob = `modified`; a deleted and an added file with the SAME blob = `renamed` (paired in
path order); the rest is `added` / `deleted`. A rename with modification is therefore
`deleted` + `added` in both modes.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import gitio
from .gitio import BrainError
from .notes import collect
from .ref import resolve_in


def diff_files(a: list[dict], b: list[dict]) -> list[dict]:
    """Compare two lists of {path, blob}; result sorted by path."""
    old = {f["path"]: f["blob"] for f in a}
    new = {f["path"]: f["blob"] for f in b}
    files: list[dict] = []
    for path in sorted(old.keys() & new.keys()):
        files.append({"path": path, "status": "unchanged" if old[path] == new[path] else "modified"})
    deleted = sorted(old.keys() - new.keys())
    added = sorted(new.keys() - old.keys())
    used: set[str] = set()
    for path in added:
        match = next((d for d in deleted if d not in used and old[d] == new[path]), None)
        if match is None:
            files.append({"path": path, "status": "added"})
        else:
            used.add(match)
            files.append({"path": path, "status": "renamed", "old_path": match})
    files += [{"path": d, "status": "deleted"} for d in deleted if d not in used]
    return sorted(files, key=lambda f: f["path"])


def diff_refs(repo: str | Path, ref_a: str, ref_b: str) -> dict:
    brain = gitio.open_brain(repo)
    ca = resolve_in(brain, ref_a).commit
    cb = resolve_in(brain, ref_b).commit
    fa = [{"path": n.path, "blob": n.blob} for n in collect(brain, ca).notes]
    fb = [{"path": n.path, "blob": n.blob} for n in collect(brain, cb).notes]
    return {"from": ca, "to": cb, "files": diff_files(fa, fb)}


def _check_manifest(m, label: str) -> list[dict]:
    files = m.get("files") if isinstance(m, dict) else None
    if not isinstance(files, list) or not all(
            isinstance(f, dict) and isinstance(f.get("path"), str) and isinstance(f.get("blob"), str)
            for f in files):
        raise BrainError("manifest_invalid", f"{label}: not a brain manifest (files[{{path, blob}}])")
    return files


def diff_manifests(a: dict, b: dict) -> dict:
    fa = _check_manifest(a, "first manifest")
    fb = _check_manifest(b, "second manifest")
    return {"from": a.get("commit"), "to": b.get("commit"), "files": diff_files(fa, fb)}


def load_manifest(path: str | Path) -> dict:
    """The only disk read of this module: one `manifest.json`."""
    p = Path(path).expanduser()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BrainError("manifest_invalid", f"cannot read manifest {p}: {e}") from e
