"""Constants, schemas, identifier validators, run uid and clock of the run workspace.

Every identifier that comes from a caller (scope id, agent, document type, run uid) is validated
here, before any path is built from it.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone

SCHEMA_VERSION = 1
DOC_TYPES: tuple[str, ...] = ("review", "acceptance", "demo", "deploy", "implement", "nonreg",
                              "findings", "report")
RUN_STATES: tuple[str, ...] = ("open", "published", "rejected", "failed", "timeout")
FINAL_STATES: tuple[str, ...] = ("published", "failed", "timeout")
OUTCOMES: tuple[str, ...] = ("failed", "timeout")
RUN_JSON_KEYS: tuple[str, ...] = tuple(sorted((
    "schema_version", "run_uid", "agent", "phase", "feature", "story", "mission", "ticket",
    "created_at", "finished_at", "state", "reasons", "published", "engine",
)))
DOC_MAX_BYTES = 1_048_576
ENGINE_NAME = "harry-sdlc"
# Caps of rw/out/sources/ (published into the trace of a code run): per file and per run.
SOURCE_MAX_BYTES = 50 * 1024 * 1024
RUN_SOURCES_MAX_BYTES = 200 * 1024 * 1024
CODE_OPTIONS: tuple[str, ...] = ("branch", "base", "repro", "repro_dir", "status")

RUN_UID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
ROUND_HEADER_RE = re.compile(
    r"^<!-- round (\d+) · run (\d{8}-\d{6}-[0-9a-f]{6}) · agent ([a-z][a-z0-9-]*) · (\S+) -->$")
# Same pattern on raw bytes: an aggregated document is scanned without ever being decoded.
ROUND_HEADER_BYTES_RE = re.compile(ROUND_HEADER_RE.pattern.encode("utf-8"))

SCOPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
AGENT_RE = re.compile(r"^[a-z][a-z0-9-]*$")
PHASE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
# Branch names accepted by the run workspace (a strict subset of git check-ref-format): no leading
# `-` or `/`, no `..`, `//`, `@{`, whitespace, control or `~^:?*[\` character, no component starting
# with `.`, no trailing `/`, `.` or `.lock`, not `@`.
BRANCH_RE = re.compile(
    r"^(?![-/])(?!.*\.\.)(?!.*//)(?!.*@\{)(?!(?:.*/)?\.)(?!.*(?:/|\.|\.lock)$)(?!@$)"
    r"[^\s~^:?*\[\\\x00-\x1f\x7f]+$")


class RunError(Exception):
    """Refusal of the run workspace library. `str(e)` is `"<code>:<detail>"` (or `"<code>"`)."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


# --- validators ---

def validate_scope_id(value: str | None) -> str:
    if not isinstance(value, str) or not SCOPE_ID_RE.fullmatch(value) or ".." in value:
        raise RunError("scope_invalid", str(value))
    return value


def validate_agent(value: str | None) -> str:
    if value is None or value == "":
        raise RunError("agent_missing", "--agent is required")
    if not isinstance(value, str) or not AGENT_RE.fullmatch(value):
        raise RunError("agent_invalid", str(value))
    return value


def validate_phase(value: str | None, agent: str) -> str:
    if value is None or value == "":
        return agent
    if not isinstance(value, str) or not PHASE_RE.fullmatch(value):
        raise RunError("phase_invalid", str(value))
    return value


def validate_type(value: str | None) -> str:
    if value not in DOC_TYPES:
        raise RunError("type_invalid", f"{value}; allowed: {', '.join(DOC_TYPES)}")
    return value


def validate_run_uid(value: str | None) -> str:
    if not isinstance(value, str) or not RUN_UID_RE.fullmatch(value):
        raise RunError("run_uid_invalid", str(value))
    return value


def validate_branch(value: str | None) -> str:
    if not isinstance(value, str) or not BRANCH_RE.fullmatch(value):
        raise RunError("branch_invalid", str(value))
    return value


def validate_outcome(value: str | None) -> str | None:
    if value is not None and value not in OUTCOMES:
        raise RunError("outcome_invalid", f"{value}; allowed: {', '.join(OUTCOMES)}")
    return value


# --- clock, uid, hashing, JSON ---

def utc_now() -> datetime:
    """The only clock of the package (monkeypatched by tests)."""
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_uid(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump_json(obj) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build_run_json(*, run_uid: str, agent: str, phase: str, feature: str | None, story: str | None,
                   mission: str | None, created_at: str, engine_version: str,
                   ticket: str | None = None) -> dict:
    """`run.json` of a new run (state `open`), keys exactly `RUN_JSON_KEYS`."""
    return {
        "schema_version": SCHEMA_VERSION, "run_uid": run_uid, "agent": agent, "phase": phase,
        "feature": feature, "story": story, "mission": mission, "ticket": ticket,
        "created_at": created_at, "finished_at": None, "state": "open", "reasons": [],
        "published": [], "engine": {"name": ENGINE_NAME, "version": engine_version},
    }
