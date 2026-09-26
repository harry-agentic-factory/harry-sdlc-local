"""Life cycle of a run workspace: `run_init`, `run_finish`, `run_clean`, `run_list`.

Backend agnostic: everything is read and published through the port (`port.py`). Workspace
discovery (`default_root`, `find_workspace`, `iter_workspaces`) is used when the backend offers it;
otherwise an explicit `root=` (init) or a workspace path (finish, clean) is required.

A code run (`code=True`, or a backend whose `run_workspace` is true) also clones the repositories of
its scope (`code.py`), may apply a story transition (`status=`, through `backend.transition`) and, at
finish, bundles and pushes the story branch before publication. `code_clone` is `sdlc clone`.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path, PurePosixPath

from . import code as codemod
from . import controls, layout, repro as repromod
from .model import (CODE_OPTIONS, FINAL_STATES, RUN_UID_RE, SCHEMA_VERSION, RunError, build_run_json,
                    dump_json, iso, new_run_uid, sha256, utc_now, validate_agent, validate_branch,
                    validate_outcome, validate_phase, validate_run_uid, validate_scope_id)
from .port import CodeHost, Scope


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


# Fields of run.json that name the run; sealed at init, checked by finish (the workspace run.json is
# writable by the agent, `seal.json` is the reference).
IDENTITY_KEYS = ("run_uid", "agent", "phase", "feature", "story", "mission", "ticket")


def _identity(run: dict) -> dict:
    return {k: run.get(k) for k in IDENTITY_KEYS}


def _write(path: Path, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    _write(tmp, data)
    os.replace(tmp, path)


# --- code run helpers ---

def _code_enabled(backend, code) -> bool:
    """`code` given by the caller, else the raw `run_workspace` of the backend (absent = False)."""
    if code is not None:
        return bool(code)
    raw = getattr(backend, "run_workspace", None)
    if raw is None or raw is False:
        return False
    if raw is True:
        return True
    raise RunError("run_workspace_invalid", repr(raw))


def _code_host(backend, code_host) -> CodeHost:
    host = code_host if code_host is not None else backend
    if not (callable(getattr(host, "code_repos", None)) and callable(getattr(host, "default_base", None))):
        raise RunError("code_host_required", "a code run needs a CodeHost (code_host= or the backend)")
    return host


def _check_status(backend, story: str, target: str) -> dict:
    """Validate the transition `story -> target` without writing: `{from, to, applied}`."""
    from ..status import InvalidTransition, validate_transition
    if not callable(getattr(backend, "transition", None)) or not callable(getattr(backend, "story_status", None)):
        raise RunError("status_unsupported", "this backend cannot apply a story transition")
    current = backend.story_status(story)
    if current == target:
        return {"from": current, "to": target, "applied": False}
    try:
        validate_transition(current, target)
    except (InvalidTransition, ValueError):
        raise RunError("status_invalid", f"{current}->{target}") from None
    return {"from": current, "to": target, "applied": True}


# --- init ---

def run_init(project: str | None = None, *, agent: str | None, story: str | None = None,
             mission: str | None = None, phase: str | None = None, root=None, backend=None,
             run_uid: str | None = None, agent_root: str | None = None, branch: str | None = None,
             base: str | None = None, repro: str | None = None, repro_dir=None, status: str | None = None,
             code: bool | None = None, code_host=None) -> dict:
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
    options = {"branch": branch, "base": base, "repro": repro, "repro_dir": repro_dir, "status": status}
    given = [o for o in CODE_OPTIONS if options[o] is not None]
    is_code = _code_enabled(backend, code)
    if given and not is_code:
        raise RunError("run_workspace_disabled", "--" + given[0].replace("_", "-"))
    host = None
    if is_code:
        if mission is not None and given:
            raise RunError("mission_scope_unsupported", "--" + given[0].replace("_", "-"))
        if repro is not None and repro_dir is not None:
            raise RunError("repro_conflict", "--repro and --repro-dir are exclusive")
        for value in (branch, base):
            if value is not None:
                validate_branch(value)
        host = _code_host(backend, code_host)

    # 2. reads (before any write)
    scope: Scope = backend.locate(story=story, mission=mission)
    plan = None
    status_res = None
    repro_files: list = []
    code_warnings: list[str] = []
    if is_code:
        specs = list(host.code_repos(scope)) if scope.story is not None else []
        default_base = host.default_base()
        if scope.story is not None:
            if branch is None:
                finder = getattr(backend, "story_branch", None)
                branch = finder(scope.story) if callable(finder) else None
                if branch is not None:
                    validate_branch(branch)
            base = base if base is not None else validate_branch(default_base)
            if any(s.role == "target" for s in specs):
                if branch is None:
                    raise RunError("branch_required", scope.story)
                if branch in (base, default_base):
                    raise RunError("branch_protected", branch)
            if status is not None:
                status_res = _check_status(backend, scope.story, status)
        plan = codemod.plan(specs, branch=branch if scope.story else None, base=base if scope.story else None,
                            default_base=default_base)
        code_warnings += plan.warnings
        if repro is not None:
            repro_files = repromod.from_trace(backend, repro)
            if not repro_files:
                code_warnings.append("repro_empty")
        elif repro_dir is not None:
            repro_files = repromod.from_dir(repro_dir)
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
    for rel, entry, data in repro_files:          # repro entries: common form, never "dirty"
        files[rel] = entry
        contents[rel] = data

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

    def manifest_bytes_of(extra: list[dict]) -> bytes:
        entries = {**{k: files[k] for k in files}, **{e["key"]: e for e in extra}}
        return dump_json({
            "schema_version": SCHEMA_VERSION, "run_uid": uid,
            "scope": {"feature": scope.feature, "story": scope.story, "mission": scope.mission},
            "files": [entries[k] for k in sorted(entries)],
            "brain": {"ref": pin.ref, "commit": pin.commit}, "dirty": dirty,
        })

    settings_bytes = dump_json(layout.settings(a, bubble, code=is_code))
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
        neighbours: list[dict] = []
        repos_json: dict = {}
        if is_code:
            repos_json, neighbours, code_json = codemod.prepare_code(partial, plan, final=final)
            _write(partial / codemod.CODE_JSON, dump_json(code_json))
        manifest_bytes = manifest_bytes_of(neighbours)
        _write(partial / "in" / "manifest.json", manifest_bytes)
        _write(partial / "in" / "settings.json", settings_bytes)
        _write(partial / "seal.json", dump_json({"manifest_sha256": sha256(manifest_bytes),
                                                 "settings_sha256": sha256(settings_bytes),
                                                 "run": _identity(run)}))
        _write(partial / "run.json", dump_json(run))
        if status_res is not None and status_res["applied"]:
            try:
                backend.transition(scope.story, status)
            except Exception as e:
                raise RunError("status_invalid", f"{status_res['from']}->{status}") from e
        os.rename(partial, final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise

    res = {
        "run_uid": uid, **{k: v for k, v in layout.workspace_paths(final).items()},
        "brain": {"ref": pin.ref, "commit": pin.commit, "from": pin.source, "files": len(brain_rels),
                  "bytes": sum(files[r]["size"] for r in brain_rels)},
        "warnings": sorted(set(pin.warnings) | set(code_warnings)),
    }
    if is_code:
        res["repos"] = repos_json
    if status_res is not None:
        res["status"] = status_res
    return res


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

def _check_identity(uid: str, current: dict, seal: dict) -> dict:
    """Sealed identity of the run; `run_invalid` when the workspace run.json no longer matches it."""
    sealed = seal.get("run")
    if not isinstance(sealed, dict) or set(sealed) != set(IDENTITY_KEYS):
        raise RunError("run_invalid", "seal.json: no sealed run identity")
    if sealed.get("run_uid") != uid:
        raise RunError("run_invalid", "seal.json: run_uid differs from the workspace")
    diff = sorted(k for k in IDENTITY_KEYS if current.get(k) != sealed[k])
    if diff:
        raise RunError("run_invalid", "run.json differs from seal.json: " + ",".join(diff))
    validate_agent(sealed["agent"])
    validate_phase(sealed["phase"], sealed["agent"])
    for k in ("feature", "story", "mission"):
        if sealed[k] is not None:
            validate_scope_id(sealed[k])
    return sealed


def _check_scope(sealed: dict, manifest: dict | None) -> None:
    """The sealed identity names the scope the sealed manifest was pulled for."""
    scope = manifest.get("scope") if isinstance(manifest, dict) else None
    if not isinstance(scope, dict) or manifest.get("run_uid") != sealed["run_uid"] \
            or any(scope.get(k) != sealed[k] for k in ("feature", "story", "mission")):
        raise RunError("run_invalid", "run identity differs from the scope of in/manifest.json")


def _reject(root: Path, current: dict, uid: str, reasons: list[str], warnings: list[str]) -> dict:
    current["state"] = "rejected"
    current["reasons"] = sorted(set(reasons))
    _write(root / "run.json", dump_json(current))
    return {"run_uid": uid, "state": "rejected", "published": [], "warnings": sorted(set(warnings)),
            "reasons": current["reasons"]}


def run_finish(run, *, backend=None, keep: bool = False, outcome: str | None = None,
               status: str | None = None, code_host=None) -> dict:
    """Checks, then publication through the backend, then clean (unless `keep`). All or nothing.

    A code run (workspace with `code.json`) also checks its repositories, bundles the story branch,
    pushes it from a fresh clone (not with `outcome`), publishes sources and bundles into the trace and
    applies `status` (a story transition) just before the final `run.json`."""
    outcome = validate_outcome(outcome)
    if outcome is not None and status is not None:
        raise RunError("outcome_status_conflict", "a failed/timeout run applies no transition")
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

    seal = _read_json(root / "seal.json")
    sealed = _check_identity(uid, current, seal) if seal is not None else None
    code = codemod.load(root)
    if code is None and status is not None:
        raise RunError("run_workspace_disabled", "--status")
    host = None
    status_res = None
    reasons: list[str] = []
    if code is not None:
        if status is not None and sealed is not None:     # unsealed: rejected by the checks below
            if sealed["story"] is None:
                raise RunError("mission_scope_unsupported", "--status")
            try:
                status_res = _check_status(backend, sealed["story"], status)
            except RunError as e:
                if e.code != "status_invalid":
                    raise
                reasons.append(str(e))
        if outcome is None:
            host = _code_host(backend, code_host)
        res = controls.check(root, engine_files=codemod.engine_files(code), publish_sources=True)
    else:
        res = controls.check(root)
    reasons += res.reasons
    warnings = list(res.warnings)
    if code is not None and not reasons:
        more, warn = codemod.check_code(root, code, res.manifest)
        reasons += more
        warnings += warn
    if reasons:
        return _reject(root, current, uid, reasons, warnings)

    if sealed is None or res.manifest_data is None:    # unreachable: the checks reject both
        raise RunError("run_invalid", f"{root}: unsealed workspace")
    _check_scope(sealed, res.manifest)

    # code: bundles, then every push prepared before the first one (never with an outcome)
    git: dict | None = None
    if code is not None:
        heads, more = codemod.bundle_code(root, code)
        if more:
            return _reject(root, current, uid, more, warnings)
        if outcome is not None:
            git = codemod.unpushed(code, heads)
        else:
            scope = Scope(sealed["feature"], sealed["story"], sealed["mission"])
            urls = {s.name: s.url for s in host.code_repos(scope)} if any(v != "unchanged" for v in heads.values()) else {}
            git, more = codemod.push_code(root, uid, code, heads, urls)
            if more:
                return _reject(root, current, uid, more, warnings)

    # publication: only the sealed identity and the bytes the checks read (never read again)
    at = iso(utc_now())
    published = []
    for doc_type in res.docs:
        meta = {"category": "artifact", "kind": doc_type, **{k: sealed[k] for k in IDENTITY_KEYS}, "at": at}
        key = layout.doc_key(uid, doc_type)
        put = backend.put(key, res.doc_data[doc_type], meta)
        published.append({"type": doc_type, "round": put.get("round"), "path": key})
    if code is not None:
        for rel in sorted(res.source_data):
            backend.put(layout.source_key(uid, rel), res.source_data[rel],
                        {"category": "source", "run_uid": uid})
        for repo in sorted(code["bundles"]):
            if isinstance(git.get(repo), dict) and git[repo]["sha"] == code["bundles"][repo].get("sha"):
                data = (root / "rw" / "out" / layout.bundle_rel(repo)).read_bytes()
                backend.put(layout.bundle_key(uid, repo), data, {"category": "bundle", "run_uid": uid})
    backend.put(layout.run_key(uid, "manifest.json"), res.manifest_data,
                {"category": "run_meta", "run_uid": uid})
    if status_res is not None:
        again = _check_status(backend, sealed["story"], status) if status_res["applied"] else status_res
        if again["applied"]:
            try:
                backend.transition(sealed["story"], status)
            except Exception:
                return _reject(root, current, uid, [f"status_invalid:{again['from']}->{status}"], warnings)
    final = dict(current)
    final.update({"state": outcome or "published", "finished_at": at, "reasons": [], "published": published})
    final_bytes = dump_json(final)
    backend.put(layout.run_key(uid, "run.json"), final_bytes, {"category": "run_meta", "run_uid": uid})
    _write(root / "run.json", final_bytes)
    if not keep:
        shutil.rmtree(root)
    out = {"run_uid": uid, "state": final["state"], "published": published, "warnings": sorted(set(warnings))}
    if code is not None:
        out["git"] = git
    if status_res is not None:
        out["status"] = status_res
    return out


# --- sdlc clone ---

def code_clone(root, *, backend=None, code_host=None, branch: str | None = None,
               base: str | None = None) -> dict:
    """Clone the code of an existing open story run whose `rw/code/` is still empty (`sdlc clone`)."""
    for value in (branch, base):
        if value is not None:
            validate_branch(value)
    root = Path(os.path.abspath(os.fspath(root)))
    if backend is None:
        backend = _default_backend(None)
    if not _code_enabled(backend, None if code_host is None else True):
        raise RunError("run_workspace_disabled", "clone")
    host = _code_host(backend, code_host)
    current = _read_json(root / "run.json")
    if current is None:
        raise RunError("run_unknown", str(root))
    uid = validate_run_uid(current.get("run_uid"))
    if root.name != uid:
        raise RunError("run_invalid", f"{root}: folder name differs from run_uid {uid}")
    if current.get("state") != "open":
        raise RunError("run_state_invalid", str(current.get("state")))
    seal = _read_json(root / "seal.json")
    if seal is None:
        raise RunError("run_invalid", f"{root}: unsealed workspace")
    sealed = _check_identity(uid, current, seal)
    if sealed["story"] is None:
        raise RunError("mission_scope_unsupported", "clone")
    man_path, set_path = root / "in" / "manifest.json", root / "in" / "settings.json"
    man_bytes, set_bytes = man_path.read_bytes(), set_path.read_bytes()
    if sha256(man_bytes) != seal.get("manifest_sha256") or sha256(set_bytes) != seal.get("settings_sha256"):
        raise RunError("run_invalid", f"{root}: in/ differs from seal.json")
    manifest = json.loads(man_bytes.decode("utf-8"))
    existing = codemod.load(root)
    code_dir = root / "rw" / "code"
    if any(True for _ in os.scandir(code_dir)) or any("commit" in e for e in manifest.get("files", [])) \
            or (existing is not None and existing.get("repos")):
        raise RunError("clone_exists", uid)

    scope = Scope(sealed["feature"], sealed["story"], sealed["mission"])
    specs = list(host.code_repos(scope))
    default_base = host.default_base()
    if branch is None:
        finder = getattr(backend, "story_branch", None)
        branch = finder(scope.story) if callable(finder) else None
        if branch is not None:
            validate_branch(branch)
    base = base if base is not None else validate_branch(default_base)
    if any(s.role == "target" for s in specs):
        if branch is None:
            raise RunError("branch_required", scope.story)
        if branch in (base, default_base):
            raise RunError("branch_protected", branch)
    plan = codemod.plan(specs, branch=branch, base=base, default_base=default_base)

    created = [(code_dir if r.role == "target" else root / "in" / "repos") / r.name for r in plan.repos]
    had_repos_dir = os.path.lexists(root / "in" / "repos")
    try:
        repos_json, neighbours, code_json = codemod.prepare_code(root, plan, final=root)
        entries = {e["key"]: e for e in manifest.get("files", []) if isinstance(e, dict) and "key" in e}
        entries.update({e["key"]: e for e in neighbours})
        manifest["files"] = [entries[k] for k in sorted(entries)]
        new_man = dump_json(manifest)
        settings = json.loads(set_bytes.decode("utf-8"))
        deny = settings.setdefault("permissions", {}).setdefault("deny", [])
        deny += [d for d in layout.GIT_DENY if d not in deny]
        new_set = dump_json(settings)
        new_seal = dict(seal, manifest_sha256=sha256(new_man), settings_sha256=sha256(new_set))
        codemod.save(root, code_json)
        _write_atomic(man_path, new_man)
        _write_atomic(set_path, new_set)
        _write_atomic(root / "seal.json", dump_json(new_seal))
    except BaseException:
        for p in created:
            shutil.rmtree(p, ignore_errors=True)
        if not had_repos_dir:
            shutil.rmtree(root / "in" / "repos", ignore_errors=True)
        raise
    return {"run_uid": uid, "repos": repos_json, "warnings": sorted(set(plan.warnings))}


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
