"""`sdlc.brain`: read a brain (a git knowledge repository) at a commit.

Public, side-effect free library API (stable for 0.7.x: keys may be added, never renamed or
removed). The `sdlc brain` CLI only wraps it. See `docs/brain.md`.
"""
from __future__ import annotations

from .diff import diff_files, diff_manifests, diff_refs
from .frontmatter import Frontmatter, parse_frontmatter
from .gitio import BrainError, BrainNotGit, BrainRefUnresolved
from .history import history
from .links import extract_links
from .lint import lint
from .mapping import (CATEGORIES, DEFAULT_EXCLUDES, DEFAULT_RULES, READER_PROFILE, Mapping, deduce,
                      is_excluded, match_glob, parse_mapping)
from .normalize import normalize
from .notes import Note, effective_excludes, list_notes, read_notes
from .ref import ResolvedRef, resolve_brain_ref
from .snapshot import build_manifest, snapshot

__all__ = [
    "CATEGORIES", "READER_PROFILE", "DEFAULT_EXCLUDES", "DEFAULT_RULES",
    "BrainError", "BrainNotGit", "BrainRefUnresolved",
    "ResolvedRef", "Note", "Frontmatter", "Mapping",
    "resolve_brain_ref", "list_notes", "read_notes", "effective_excludes", "extract_links",
    "lint", "build_manifest", "snapshot", "diff_refs", "diff_manifests", "diff_files", "history",
    "normalize", "parse_frontmatter", "match_glob", "is_excluded", "parse_mapping", "deduce",
]
