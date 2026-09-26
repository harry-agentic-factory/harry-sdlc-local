"""Notes of a brain at a given commit.

A note is a regular `*.md` file tracked at the commit, under the brain prefix, not excluded.
Everything is read from git objects: the working copy, the index and `git status` are never
consulted (an untracked, ignored or modified-but-uncommitted file is invisible).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import gitio
from .gitio import Brain, BrainError
from .mapping import DEFAULT_EXCLUDES, MAP_FILE, Mapping, is_excluded, parse_mapping, read_mapping_file


@dataclass(frozen=True)
class Note:
    path: str   # relative to the brain root
    blob: str   # git blob sha (the note version)
    mode: str   # git file mode (100644 / 100755)


@dataclass(frozen=True)
class NoteSet:
    brain: Brain
    commit: str
    mapping: Mapping
    excludes: tuple[str, ...]
    notes: list[Note]


def tree_files(brain: Brain, commit: str) -> list[Note]:
    """Every regular file of `commit` under the brain prefix (paths relative to the brain)."""
    files = []
    for mode, sha, full in gitio.ls_tree(brain.top, commit, brain.prefix):
        if brain.prefix and not full.startswith(brain.prefix):
            continue
        files.append(Note(full[len(brain.prefix):], sha, mode))
    return files


def load_mapping(brain: Brain, files: list[Note], map_path: str | Path | None = None) -> Mapping:
    """`--map` file when given, else `brain-map.yaml` read AT THE COMMIT, else no project rules."""
    if map_path is not None:
        return read_mapping_file(map_path)
    for f in files:
        if f.path == MAP_FILE:
            data = gitio.cat_file(brain.top, [f.blob])[0]
            return parse_mapping(data or b"", MAP_FILE)
    return Mapping()


def collect(brain: Brain, commit: str, *, excludes: Iterable[str] = (),
            map_path: str | Path | None = None) -> NoteSet:
    files = tree_files(brain, commit)
    mapping = load_mapping(brain, files, map_path)
    effective = tuple(DEFAULT_EXCLUDES) + mapping.excludes + tuple(excludes)
    notes = sorted((f for f in files if f.path.endswith(".md") and not is_excluded(f.path, effective)),
                   key=lambda n: n.path)
    return NoteSet(brain, commit, mapping, effective, notes)


def read_blobs(brain: Brain, notes: Iterable[Note]) -> dict[str, bytes]:
    notes = list(notes)
    contents = gitio.cat_file(brain.top, [n.blob for n in notes])
    return {n.path: (c if c is not None else b"") for n, c in zip(notes, contents)}


# --- public API ---

def list_notes(repo: str | Path, commit: str, *, excludes: Iterable[str] = (),
               map_path: str | Path | None = None) -> list[Note]:
    """Notes at `commit` (any revision), sorted by path."""
    return collect(gitio.open_brain(repo), commit, excludes=excludes, map_path=map_path).notes


def read_notes(repo: str | Path, commit: str, paths: Iterable[str]) -> dict[str, bytes]:
    """Raw bytes of `paths` (relative to the brain) at `commit`, through one `cat-file --batch`."""
    brain = gitio.open_brain(repo)
    paths = list(paths)
    contents = gitio.cat_file(brain.top, [f"{commit}:{brain.prefix}{p}" for p in paths])
    out: dict[str, bytes] = {}
    for p, c in zip(paths, contents):
        if c is None:
            raise BrainError("note_not_found", f"note not found at {commit}: {p}")
        out[p] = c
    return out


def effective_excludes(repo: str | Path, commit: str, *, excludes: Iterable[str] = (),
                       map_path: str | Path | None = None) -> tuple[str, ...]:
    """Default exclusions + `exclude:` of the mapping + explicit ones (always added)."""
    return collect(gitio.open_brain(repo), commit, excludes=excludes, map_path=map_path).excludes
