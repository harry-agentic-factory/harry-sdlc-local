"""Life cycle of a run workspace: `run_init`, `run_finish`, `run_clean`, `run_list`.

Backend agnostic: everything is read and published through the port (`port.py`). Workspace
discovery (`default_root`, `find_workspace`, `iter_workspaces`) is used when the backend offers it;
otherwise an explicit `root=` (init) or a workspace path (finish, clean) is required.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path, PurePosixPath

from . import controls, layout
from .model import (FINAL_STATES, RUN_UID_RE, SCHEMA_VERSION, RunError, build_run_json, dump_json, iso,
                    new_run_uid, sha256, utc_now, validate_agent, validate_outcome, validate_phase,
                    validate_run_uid, validate_scope_id)
from .port import Scope


def _default_backend(project: str | None):
    from .datarepo import DataRepoBackend
    return DataRepoBackend.from_project(project)


def _engine_version() -> str:
    from ..migrations import engine_version
    return engine_version()


def _trace(backend, uid: str) -> dict | None:
    try:
        data = backend.get(layout.run_key(uid, "run.json"))
    except KeyError:
        return None
    try:
        run = json.loads(data.decode("utf-8"))
    except ValueError:
        return None
    return run if isinstance(run, dict) else None


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


# --- init ---

def run_init(project: str | None = None, *, agent: str | None, story: str | None = None,
             mission: str | None = None, phase: str | None = None, root=None, backend=None,
             run_uid: str | None = None, agent_root: str | None = None) -> dict:
    """Create a run workspace (see `docs/run-workspace.md`). Nothing is written on refusal."""
    # 1. validations
    agent = validate_agent(agent)
    if (story is None) == (mission is None):
        raise RunError("scope_invalid", "exactly one of story or mission is required")
    scope_id = validate_scope_id(story if story is not None else mission)
    phase = validate_phase(phase, agent)
    if run_uid is not None:
        validate_run_uid(run_uid)
    if agent_root is not None:
        a = str(agent_root).rstrip("/")
        if not a or not PurePosixPath(a).is_absolute() or not layout.safe_segments(a[1:]):
            raise RunError("agent_root_invalid", str(agent_root))
        agent_root = a
    if backend is None:
        backend = _default_backend(project)
    if root is None and not hasattr(backend, "default_root"):
        raise RunError("root_required", "this backend has no default workspace root")

    # 2. reads (before any write)
    scope: Scope = backend.locate(story=story, mission=mission)
    pin = backend.brain()
    bubble = backend.bubble(agent)
    prefixes = layout.pull_prefixes(scope) + ([pin.prefix] if pin.prefix else [])
    files: dict[str, dict] = {}
    contents: dict[str, bytes] = {}
    for prefix in prefixes:
        for entry in backend.list(prefix):
            rel = layout.in_path(entry["key"], scope, pin.prefix)
            if rel is None or rel in files:
                continue
            data = backend.get(entry["key"])
            contents[rel] = data
            files[rel] = {"key": rel, "version": entry.get("version"), "sha256": sha256(data),
                          "size": len(data), "origin": entry.get("origin")}
    brain_rels = [r for r in files if r.startswith("brain/")]
    dirty = sorted(r for r, e in files.items() if e["version"] is None and not r.startswith("brain/"))

    # 3. uid and location
    parent = Path(os.path.abspath(root if root is not None else backend.default_root(scope_id)))
    if run_uid is not None:
        if os.path.lexists(parent / run_uid) or _trace(backend, run_uid) is not None:
            raise RunError("run_exists", run_uid)
        uid = run_uid
    else:
        while True:
            uid = new_run_uid(utc_now())
            if not os.path.lexists(parent / uid) and _trace(backend, uid) is None:
                break
    final = parent / uid
    a = agent_root or str(final)

    manifest = {
        "schema_version": SCHEMA_VERSION, "run_uid": uid,
        "scope": {"feature": scope.feature, "story": scope.story, "mission": scope.mission},
        "files": [files[k] for k in sorted(files)],
        "brain": {"ref": pin.ref, "commit": pin.commit}, "dirty": dirty,
    }
    manifest_bytes = dump_json(manifest)
    settings_bytes = dump_json(layout.settings(a, bubble))
    run = build_run_json(run_uid=uid, agent=agent, phase=phase, feature=scope.feature, story=scope.story,
                         mission=scope.mission, created_at=iso(utc_now()), engine_version=_engine_version())

    # 4. build in a hidden partial folder, then rename (never a half visible run)
    parent.mkdir(parents=True, exist_ok=True)
    partial = parent / f".{uid}.partial"
    try:
        partial.mkdir()
        for d in layout.in_dirs(scope):
            (partial / d).mkdir(parents=True, exist_ok=True)
        for rel in sorted(contents):
            target = partial / "in" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            _write(target, contents[rel])
        _write(partial / "in" / "manifest.json", manifest_bytes)
        _write(partial / "in" / "settings.json", settings_bytes)
        _write(partial / "seal.json", dump_json({"manifest_sha256": sha256(manifest_bytes),
                                                 "settings_sha256": sha256(settings_bytes)}))
        _write(partial / "run.json", dump_json(run))
        os.rename(partial, final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise

    return {
        "run_uid": uid, **{k: v for k, v in layout.workspace_paths(final).items()},
        "brain": {"ref": pin.ref, "commit": pin.commit, "from": pin.source, "files": len(brain_rels),
                  "bytes": sum(files[r]["size"] for r in brain_rels)},
        "warnings": sorted(set(pin.warnings)),
    }


# --- workspace resolution (finish, clean) ---

def _is_uid(run) -> bool:
    return isinstance(run, str) and RUN_UID_RE.fullmatch(run) is not None


def _locate(run, backend) -> tuple[str, Path | None]:
    """(run uid, workspace or None) of a run given by uid or by workspace path."""
    if _is_uid(run):
        finder = getattr(backend, "find_workspace", None)
        if finder is None:
            raise RunError("root_required", "pass the workspace path: this backend cannot find workspaces")
        return run, finder(run)
    root = Path(os.path.abspath(os.fspath(run)))
    data = _read_json(root / "run.json")
    if data is None:
        raise RunError("run_unknown", str(run))
    uid = validate_run_uid(data.get("run_uid"))
    if root.name != uid:
        raise RunError("run_invalid", f"{root}: folder name differs from run_uid {uid}")
    return uid, root


# --- finish ---

def run_finish(run, *, backend=None, keep: bool = False, outcome: str | None = None) -> dict:
    """Checks, then publication through the backend, then clean (unless `keep`). All or nothing."""
    outcome = validate_outcome(outcome)
    if backend is None:
        backend = _default_backend(None)
    uid, root = _locate(run, backend)
    trace = _trace(backend, uid)
    if trace is not None and trace.get("state") in FINAL_STATES:
        return {"run_uid": uid, "already": trace["state"]}
    if root is None:
        raise RunError("run_unknown", uid)
    current = _read_json(root / "run.json")
    if current is None:
        raise RunError("run_invalid", f"{root}: unreadable run.json")
    if current.get("state") not in ("open", "rejected"):
        raise RunError("run_state_invalid", str(current.get("state")))

    manifest = _read_json(root / "in" / "manifest.json")
    res = controls.check(root, manifest)
    if res.reasons:
        current["state"] = "rejected"
        current["reasons"] = res.reasons
        _write(root / "run.json", dump_json(current))
        return {"run_uid": uid, "state": "rejected", "published": [], "warnings": res.warnings,
                "reasons": res.reasons}

    at = iso(utc_now())
    published = []
    for doc_type in res.docs:
        data = (root / "rw" / "out" / layout.doc_rel(doc_type)).read_bytes()
        meta = {"category": "artifact", "kind": doc_type, "run_uid": uid, "agent": current.get("agent"),
                "phase": current.get("phase"), "feature": current.get("feature"),
                "story": current.get("story"), "mission": current.get("mission"),
                "ticket": current.get("ticket"), "at": at}
        key = layout.doc_key(uid, doc_type)
        put = backend.put(key, data, meta)
        published.append({"type": doc_type, "round": put.get("round"), "path": key})
    backend.put(layout.run_key(uid, "manifest.json"), (root / "in" / "manifest.json").read_bytes(),
                {"category": "run_meta", "run_uid": uid})
    final = dict(current)
    final.update({"state": outcome or "published", "finished_at": at, "reasons": [], "published": published})
    final_bytes = dump_json(final)
    backend.put(layout.run_key(uid, "run.json"), final_bytes, {"category": "run_meta", "run_uid": uid})
    _write(root / "run.json", final_bytes)
    if not keep:
        shutil.rmtree(root)
    return {"run_uid": uid, "state": final["state"], "published": published, "warnings": res.warnings}


# --- clean, list ---

def run_clean(run, *, backend=None) -> dict:
    """Remove a run workspace without publishing anything."""
    if backend is None and _is_uid(run):
        backend = _default_backend(None)
    if _is_uid(run):
        uid, root = _locate(run, backend)
    else:
        uid, root = _locate(run, None)
    if root is None or not root.is_dir():
        raise RunError("run_unknown", str(run))
    shutil.rmtree(root)
    return {"run_uid": uid, "cleaned": True}


def run_list(project: str | None = None, *, story: str | None = None, mission: str | None = None,
             backend=None) -> list[dict]:
    """Open/rejected workspaces and published traces, sorted by run uid (a trace wins over a kept
    workspace of the same run)."""
    if story is not None:
        validate_scope_id(story)
    if mission is not None:
        validate_scope_id(mission)
    if backend is None:
        backend = _default_backend(project)
    rows: dict[str, dict] = {}
    roots: dict[str, str] = {}
    for w in getattr(backend, "iter_workspaces", lambda: [])():
        data = _read_json(w / "run.json")
        if data is None or data.get("run_uid") != w.name:
            continue
        rows[w.name] = data
        roots[w.name] = str(w)
    for entry in backend.list(layout.RUNS_PREFIX):
        uid = layout.trace_uid(entry["key"])
        if uid is None:
            continue
        data = _trace(backend, uid)
        if data is not None:
            rows[uid] = data
    out = []
    for uid in sorted(rows):
        r = rows[uid]
        if story is not None and r.get("story") != story:
            continue
        if mission is not None and r.get("mission") != mission:
            continue
        out.append({"run_uid": uid, "story": r.get("story"), "mission": r.get("mission"),
                    "agent": r.get("agent"), "state": r.get("state"), "created_at": r.get("created_at"),
                    "root": roots.get(uid)})
    return out
