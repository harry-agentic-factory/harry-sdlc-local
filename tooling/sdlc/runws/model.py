"""Constants, schemas, identifier validators, run uid and clock of the run workspace.

Every identifier that comes from a caller (scope id, agent, document type, run uid) is validated
here, before any path is built from it.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = 1
# Schema of `in/manifest.json`, DISTINCT from SCHEMA_VERSION on purpose. The latter versions
# `run.json` and is consumed by every run, light ones included; bumping it here would silently move
# every run.json to 2. The manifest alone goes to 2, because v2 breaks its published contract:
# entries leave `files`, neighbours move to `repos`, and the target repository appears.
MANIFEST_SCHEMA_VERSION = 2
# The versions `read_manifest` accepts. Anything else is refused by name, never read halfway: a
# workspace opened by a newer engine must not be parsed by an older one on a best-effort basis.
MANIFEST_VERSIONS: tuple[int, ...] = (1, MANIFEST_SCHEMA_VERSION)
# Warning codes the manifest can carry. They are CONSTANTS and not literals because the platform
# writes the same codes for a light run: a string recopied there would drift silently.
WARN_SCOPE_EMPTY = "scope_empty"
WARN_BASE_DEFAULTED = "base_defaulted"
# Key prefix under which v1 listed a neighbour inside `files`. Kept for READING v1 only; v2 never
# writes it.
V1_NEIGHBOUR_PREFIX = "repos/"
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

    def __init__(self, code: str, detail: str = "", *, diagnostic: str | None = None):
        self.code = code
        self.detail = detail
        # free text for the operator (e.g. the redacted stderr of a failed git call), never part of `str(e)`
        self.diagnostic = diagnostic
        super().__init__(f"{code}:{detail}" if detail else code)


# --- manifest: the one shape every reader sees ---

@dataclass(frozen=True)
class BrainRef:
    """The Brain a run was given: declared repository, branch asked for, commit pinned.

    `repo` comes from the PIN (the declared source), never from the provenance field of the
    resolution: the pin is a superset and carries both, and picking the wrong one would be silent —
    the manifest would say where the resolution came from where a reader expects a repository
    address.
    """
    repo: str
    branch: str
    commit: str


@dataclass(frozen=True)
class RepoRef:
    """A repository mounted for the run, TARGET INCLUDED, at the commit it started from.

    `commit` is the head right after the clone, before any commit of the agent. `branch` is never
    the JSON `null`: the branch of the story for a target, the ref actually resolved for a
    neighbour (`"HEAD"` when the clone fell back to the remote default, which `warnings` says).
    """
    repo: str
    branch: str
    commit: str
    role: str          # "target" | "neighbour"


@dataclass(frozen=True)
class Manifest:
    """A manifest read, v1 or v2, normalised to ONE internal shape.

    Readers never branch on the version: `read_manifest` is the only place that knows there are
    two, and `controls`, `code.check_code`, `docs` and the `run clone` guard all go through it.
    """
    schema_version: int
    run_uid: str | None
    scope: dict
    brain: BrainRef | None
    files: dict[str, dict] = field(default_factory=dict)
    repos: list[RepoRef] = field(default_factory=list)
    dirty: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def subtree_roots(self) -> set[str]:
        """Roots of `in/` that are repositories, hence checked as a whole and never file by file."""
        return {V1_NEIGHBOUR_PREFIX + r.repo for r in self.repos if r.role != "target"}


def _entries(raw) -> dict[str, dict]:
    return {e["key"]: e for e in raw if isinstance(e, dict) and isinstance(e.get("key"), str)}


def _brain_of(raw) -> BrainRef | None:
    """`brain` of either version. A block without a commit is no Brain at all, not an empty one."""
    if not isinstance(raw, dict):
        return None
    commit = raw.get("commit")
    if not isinstance(commit, str) or not commit:
        return None
    # v1 had no `repo`, and its branch was called `ref`. An absent field reads as empty rather than
    # raising: a v1 workspace open at the version bump must stay readable, controllable, publishable.
    branch = raw.get("branch") or raw.get("ref") or ""
    return BrainRef(repo=str(raw.get("repo") or ""), branch=str(branch), commit=commit)


def read_manifest(data) -> Manifest:
    """The ONE door to a manifest. Accepts v1 and v2, refuses anything else by name.

    A bare list is the historical manifest of a light run (a plain array of document entries); it
    reads as a v1 whose scope and repositories are unknown. Unknown keys are IGNORED on purpose —
    that tolerance is the decision, not any particular field: it makes every future additive key
    possible without a new manifest version.
    """
    if isinstance(data, list):
        return Manifest(schema_version=1, run_uid=None, scope={}, brain=None, files=_entries(data))
    if not isinstance(data, dict):
        raise RunError("manifest_unsupported", type(data).__name__)
    version = data.get("schema_version", 1)
    if version not in MANIFEST_VERSIONS:
        raise RunError("manifest_unsupported", str(version))
    scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
    dirty = [d for d in data.get("dirty") or [] if isinstance(d, str)]
    warnings = [w for w in data.get("warnings") or [] if isinstance(w, str)]
    brain = _brain_of(data.get("brain"))
    raw_files = data.get("files") or []
    if version == MANIFEST_SCHEMA_VERSION:
        repos = [
            RepoRef(repo=str(r.get("repo") or ""), branch=str(r.get("branch") or ""),
                    commit=str(r.get("commit") or ""), role=str(r.get("role") or "neighbour"))
            for r in data.get("repos") or [] if isinstance(r, dict)
        ]
        return Manifest(schema_version=version, run_uid=data.get("run_uid"), scope=scope,
                        brain=brain, files=_entries(raw_files), repos=repos, dirty=dirty,
                        warnings=warnings)
    # v1: neighbours were entries of `files` carrying a `commit`, under a `repos/<name>` key, and
    # the target was nowhere — its starting commit only ever reached `code.json`. Reading one back
    # therefore yields neighbours and NO target; that absence is a fact of v1, not a defect here.
    documents, repos = {}, []
    for key, entry in _entries(raw_files).items():
        if "commit" in entry:
            name = key[len(V1_NEIGHBOUR_PREFIX):] if key.startswith(V1_NEIGHBOUR_PREFIX) else key
            repos.append(RepoRef(repo=name, branch=str(entry.get("branch") or ""),
                                 commit=str(entry.get("commit") or ""),
                                 role=str(entry.get("role") or "neighbour")))
        else:
            documents[key] = entry
    return Manifest(schema_version=1, run_uid=data.get("run_uid"), scope=scope, brain=brain,
                    files=documents, repos=repos, dirty=dirty, warnings=warnings)


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
