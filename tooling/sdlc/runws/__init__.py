"""Run workspace of an autonomous agent: create it, let the agent read and add, publish, remove.

Public, side-effect free library API (stable for 0.7.x: keys and parameters may be added, never
renamed or removed). The `sdlc run` / `sdlc doc` CLI only wraps it. See `docs/run-workspace.md`.
"""
from __future__ import annotations

from .datarepo import DataRepoBackend
from .docs import doc_add, doc_list, doc_read
from .lifecycle import code_clone, run_clean, run_finish, run_init, run_list
from .model import (DOC_MAX_BYTES, DOC_TYPES, ROUND_HEADER_RE, RUN_JSON_KEYS, RUN_SOURCES_MAX_BYTES,
                    RUN_STATES, RUN_UID_RE, SCHEMA_VERSION, SOURCE_MAX_BYTES, RunError)
from .port import BrainPin, CodeHost, DocumentRepository, Entry, RepoSpec, RunSource, Scope

__all__ = [
    "run_init", "run_finish", "run_clean", "run_list", "doc_read", "doc_list", "doc_add",
    "DocumentRepository", "RunSource", "Entry", "Scope", "BrainPin", "DataRepoBackend", "RunError",
    "DOC_TYPES", "RUN_STATES", "RUN_JSON_KEYS", "RUN_UID_RE", "ROUND_HEADER_RE", "SCHEMA_VERSION",
    "DOC_MAX_BYTES", "code_clone", "CodeHost", "RepoSpec", "SOURCE_MAX_BYTES", "RUN_SOURCES_MAX_BYTES",
]
