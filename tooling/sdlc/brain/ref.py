"""Brain ref resolution, without any fetch.

Two regimes, chosen by the caller through `prefer`:

- `prefer="origin"` (the default) — the **pushed** version wins. It belongs to `sdlc config` and to
  a run workspace, local or not: a run is a replayable artefact, so its commit must be one the
  others can see.
- `prefer="local"` — the head of the **local** branch wins. It belongs to the bubble of an agent on
  a workstation, so that a commit made minutes earlier is what the agent reads.

Order for a name `r`: `refs/remotes/origin/r` (source `origin`) then `refs/heads/r` (`local`) —
these two swapped under `prefer="local"` — then `refs/tags/r` (`tag`, annotated tags peeled), then
any revision `r` (`sha`: a sha, `origin/main`, `HEAD~1`...). `HEAD` resolves locally, whatever the
regime. No ref given: `main`, then `master`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import gitio
from .gitio import Brain, BrainRefUnresolved

DEFAULT_REFS = ("main", "master")

PREFER_ORIGIN = "origin"      # the pushed version wins (default: config, run workspaces)
PREFER_LOCAL = "local"        # the local branch head wins (the bubble of an agent on a workstation)


@dataclass(frozen=True)
class ResolvedRef:
    ref: str       # the ref that was resolved (the requested one, or the default retained)
    commit: str    # full sha of the commit
    source: str    # origin | local | tag | sha


def _resolve_one(brain: Brain, name: str, *, prefer: str = PREFER_ORIGIN) -> ResolvedRef | None:
    if not name or name.startswith("-") or any(c.isspace() for c in name):
        return None
    if name == "HEAD":
        sha = gitio.verify_commit(brain.top, "HEAD^{commit}")
        return ResolvedRef(name, sha, "local") if sha else None
    branches = ((f"refs/remotes/origin/{name}", "origin"), (f"refs/heads/{name}", "local"))
    if prefer == PREFER_LOCAL:
        branches = branches[::-1]
    forms = (*branches, (f"refs/tags/{name}", "tag"), (name, "sha"))
    for full, source in forms:
        sha = gitio.verify_commit(brain.top, f"{full}^{{commit}}")
        if sha:
            return ResolvedRef(name, sha, source)
    return None


def resolve_in(brain: Brain, ref: str | None = None, *,
               prefer: str = PREFER_ORIGIN) -> ResolvedRef:
    """Resolve `ref` (None = `main` then `master`) in an already opened brain, under `prefer`."""
    for name in ([ref] if ref is not None else list(DEFAULT_REFS)):
        found = _resolve_one(brain, name, prefer=prefer)
        if found:
            return found
    wanted = ref if ref is not None else " or ".join(DEFAULT_REFS)
    raise BrainRefUnresolved(f"cannot resolve brain ref {wanted!r} in {brain.root}")


def resolve_brain_ref(repo: str | Path, ref: str | None = None, *,
                      prefer: str = PREFER_ORIGIN) -> ResolvedRef:
    """Public entry point: open the brain at `repo` and resolve `ref` (see module docstring)."""
    return resolve_in(gitio.open_brain(repo), ref, prefer=prefer)
