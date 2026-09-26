"""The storage port of the run workspace (no I/O here).

`DocumentRepository` is what the core reads and publishes through; `RunSource` is what `run_init`
needs beyond documents (scope lookup, brain pin, agent allow/deny rules). A backend implements both.
`CodeHost` is what a code run needs to clone and push the repositories of its scope.
Keys are logical storage keys (see `docs/run-workspace.md`), never paths of a data repository.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, TypedDict, runtime_checkable


class Entry(TypedDict):
    key: str
    version: str | None
    sha256: str
    size: int
    origin: str


@dataclass(frozen=True)
class Scope:
    feature: str | None
    story: str | None
    mission: str | None


@dataclass(frozen=True)
class BrainPin:
    ref: str | None                    # ref retained (requested or default), None when unknown
    commit: str | None                 # resolved commit, None when not resolved / not git
    source: str | None                 # where the resolution came from (origin|local|tag|sha)
    prefix: str | None                 # storage prefix to list, None = nothing to pull
    files_hint: int | None = None      # informational: number of notes the backend saw
    warnings: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class DocumentRepository(Protocol):
    def get(self, key: str, version: str | None = None) -> bytes:
        """Bytes of `key` (KeyError when absent)."""

    def list(self, prefix: str) -> list[Entry]:
        """Entries under `prefix`, sorted by key."""

    def versions(self, key: str) -> list[str]:
        """Known versions of `key`, newest first ([] when unknown)."""

    def put(self, key: str, content: bytes, meta: dict) -> dict:
        """Add-only write: `{key, version}` (+ `round` for a run document).

        Same bytes on an existing key is a no-op; different bytes raise `put_conflict`."""


@runtime_checkable
class RunSource(Protocol):
    def locate(self, *, story: str | None, mission: str | None) -> Scope:
        """Scope of the run (RunError `story_unknown` / `mission_unknown`)."""

    def brain(self) -> BrainPin:
        """Brain pin of the run (commit resolved without fetch)."""

    def bubble(self, agent: str) -> dict:
        """`{"allow": [...], "deny": [...]}` rules of the project for this agent role."""


@dataclass(frozen=True)
class RepoSpec:
    """A code repository of the scope of a run.

    `url` is the clone and push source: it is resolved when needed and never written in the run.
    `missing` says why it is unresolved: "path" (no declared local copy), "remote" (local copy
    without an origin), None when resolved."""
    name: str
    role: str                          # "target" | "neighbour"
    url: str | None
    missing: str | None = None


@runtime_checkable
class CodeHost(Protocol):
    def code_repos(self, scope: Scope) -> list[RepoSpec]:
        """Targets = repositories of the story, neighbours = the other repositories ([] for a mission)."""

    def default_base(self) -> str:
        """Default base branch of the project."""
