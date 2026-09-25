"""`snapshot`: write the exact notes of one commit + `manifest.json` + `links.json`.

The only disk writes are under `out`; the only disk read is the emptiness check of `out`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from . import gitio
from .frontmatter import parse_frontmatter
from .gitio import BrainError
from .links import broken, links_for
from .notes import collect, read_blobs
from .ref import resolve_in


def _manifest(brain, rr, ns, contents: dict[str, bytes]) -> dict:
    files = []
    for note in ns.notes:
        fm = parse_frontmatter(contents[note.path])
        last = gitio.last_change(brain.top, rr.commit, brain.prefix + note.path)
        files.append({
            "path": note.path,
            "category": None if fm.error else fm.category,
            "blob": note.blob,
            "last_commit": last[0] if last else None,
            "date": last[1] if last else None,
        })
    return {"repo_ref": rr.ref, "commit": rr.commit, "date": gitio.commit_date(brain.top, rr.commit),
            "files": files}


def build_manifest(repo: str | Path, ref: str | None, *, excludes: Iterable[str] = (),
                   map_path: str | Path | None = None) -> dict:
    """`manifest.json` of the brain at `ref` (None = `main` then `master`)."""
    brain = gitio.open_brain(repo)
    rr = resolve_in(brain, ref)
    ns = collect(brain, rr.commit, excludes=excludes, map_path=map_path)
    return _manifest(brain, rr, ns, read_blobs(brain, ns.notes))


def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _check_out(out: Path) -> None:
    if out.exists():
        if not out.is_dir():
            raise BrainError("out_not_empty", f"output path exists and is not a folder: {out}")
        with os.scandir(out) as it:
            if next(it, None) is not None:
                raise BrainError("out_not_empty", f"output folder is not empty: {out}")


def snapshot(repo: str | Path, ref: str | None, out: str | Path, *, excludes: Iterable[str] = (),
             map_path: str | Path | None = None) -> dict:
    """Write the snapshot under `out` (created; must be empty) and return the summary."""
    out = Path(out).expanduser()
    brain = gitio.open_brain(repo)
    rr = resolve_in(brain, ref)
    _check_out(out)
    ns = collect(brain, rr.commit, excludes=excludes, map_path=map_path)
    contents = read_blobs(brain, ns.notes)
    root = out.absolute()
    for path in contents:
        # Defence in depth: git already rejects such tree entries, but a snapshot must never
        # write outside `out`, whatever repository it is pointed at.
        parts = path.split("/")
        if path.startswith("/") or ".." in parts or not (root / path).absolute().is_relative_to(root):
            raise BrainError("git_failed", f"unsafe note path in tree: {path!r}")
    manifest = _manifest(brain, rr, ns, contents)
    links = links_for(contents, brain.repo_names)
    out.mkdir(parents=True, exist_ok=True)
    for path, data in contents.items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _dump(out / "manifest.json", manifest)
    _dump(out / "links.json", links)
    return {"repo_ref": rr.ref, "commit": rr.commit, "out": str(out.absolute()),
            "files": len(manifest["files"]), "links": len(links), "broken_links": len(broken(links))}
