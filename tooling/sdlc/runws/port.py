"""The storage port of the run workspace (no I/O here).

`DocumentRepository` is what the core reads and publishes through; `RunSource` is what `run_init`
needs beyond documents (scope lookup, brain pin, agent allow/deny rules). A backend implements both.
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
