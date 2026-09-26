"""Brain ref resolution, without any fetch.

Order for a name `r`: `refs/remotes/origin/r` (source `origin`), `refs/heads/r` (`local`),
`refs/tags/r` (`tag`, annotated tags peeled), then any revision `r` (`sha`: a sha, `origin/main`,
`HEAD~1`...). `HEAD` resolves locally. No ref given: `main`, then `master`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import gitio
from .gitio import Brain, BrainRefUnresolved

DEFAULT_REFS = ("main", "master")


@dataclass(frozen=True)
class ResolvedRef:
    ref: str       # the ref that was resolved (the requested one, or the default retained)
    commit: str    # full sha of the commit
    source: str    # origin | local | tag | sha


def _resolve_one(brain: Brain, name: str) -> ResolvedRef | None:
    if not name or name.startswith("-") or any(c.isspace() for c in name):
        return None
    if name == "HEAD":
        sha = gitio.verify_commit(brain.top, "HEAD^{commit}")
        return ResolvedRef(name, sha, "local") if sha else None
    forms = ((f"refs/remotes/origin/{name}", "origin"), (f"refs/heads/{name}", "local"),
             (f"refs/tags/{name}", "tag"), (name, "sha"))
    for full, source in forms:
        sha = gitio.verify_commit(brain.top, f"{full}^{{commit}}")
        if sha:
            return ResolvedRef(name, sha, source)
    return None


def resolve_in(brain: Brain, ref: str | None = None) -> ResolvedRef:
    """Resolve `ref` (None = `main` then `master`) in an already opened brain."""
    for name in ([ref] if ref is not None else list(DEFAULT_REFS)):
        found = _resolve_one(brain, name)
        if found:
            return found
    wanted = ref if ref is not None else " or ".join(DEFAULT_REFS)
    raise BrainRefUnresolved(f"cannot resolve brain ref {wanted!r} in {brain.root}")


def resolve_brain_ref(repo: str | Path, ref: str | None = None) -> ResolvedRef:
    """Public entry point: open the brain at `repo` and resolve `ref` (see module docstring)."""
    return resolve_in(gitio.open_brain(repo), ref)
