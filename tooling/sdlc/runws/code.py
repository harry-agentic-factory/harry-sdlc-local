"""Code of a run: plan of the repositories, clones (`run init`, `sdlc clone`), checks, bundles and push
(`run finish`). No direct git call here: everything goes through `gitcode.py`.

`<root>/code.json` (engine file, next to `run.json` and `seal.json`, never published, not for the agent)
marks a code run. It never holds a URL nor an identifier:

    {schema_version: 1, branch, base,
     repos: {<repo>: {role: "target"|"neighbour", ref, head, created, config_sha256?}},
     bundles: {<repo>: {sha, sha256, size}}}
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import gitcode, layout
from .model import RunError, dump_json
from .port import RepoSpec

CODE_JSON = "code.json"
CODE_SCHEMA_VERSION = 1


@dataclass
class RepoPlan:
    name: str
    role: str                 # "target" | "neighbour"
    url: str
    ref: str | None           # target: story branch; neighbour: branch cloned, None = remote HEAD
    created: bool = False     # target: branch absent from the remote


@dataclass
class CodePlan:
    branch: str | None
    base: str | None
    repos: list[RepoPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def targets(self) -> list[RepoPlan]:
        return [r for r in self.repos if r.role == "target"]

    @property
    def neighbours(self) -> list[RepoPlan]:
        return [r for r in self.repos if r.role == "neighbour"]


def validate_repo_name(name) -> str:
    if not isinstance(name, str) or "/" in name or not layout.safe_segments(name) or name.startswith("-"):
        raise RunError("repo_invalid", str(name))
    return name


def ordered(specs: list[RepoSpec]) -> list[RepoSpec]:
    """Targets first, then neighbours, each sorted by name (the order of every refusal)."""
    for s in specs:
        validate_repo_name(s.name)
    return sorted(specs, key=lambda s: (s.role != "target", s.name))


def plan(specs: list[RepoSpec], *, branch: str | None, base: str | None, default_base: str | None) -> CodePlan:
    """Resolve every repository against its remote (reads only; RunError on the first refusal)."""
    p = CodePlan(branch, base)
    for s in ordered(specs):
        target = s.role == "target"
        if s.missing == "remote":
            raise RunError("no_remote", s.name)
        if s.missing == "path" or s.url is None:
            if target:
                raise RunError("repo_unresolved", s.name)
            p.warnings.append(f"repo_unresolved:{s.name}")
            continue
        heads = gitcode.ls_remote(s.url)
        if heads is None or not heads:
            raise RunError("clone_failed", s.name)
        if target:
            if f"refs/heads/{base}" not in heads:
                raise RunError("base_unknown", f"{s.name}:{base}")
            p.repos.append(RepoPlan(s.name, "target", s.url, branch,
                                    created=f"refs/heads/{branch}" not in heads))
            continue
        ref = next((b for b in (base, default_base) if b and f"refs/heads/{b}" in heads), None)
        if ref is None:
            if "HEAD" not in heads:
                raise RunError("clone_failed", s.name)
            p.warnings.append(f"neighbour_base_fallback:{s.name}")
        p.repos.append(RepoPlan(s.name, "neighbour", s.url, ref))
    return p


def prepare_code(dest: Path, p: CodePlan, *, final: Path) -> tuple[dict, list[dict], dict]:
    """Clone the plan into the workspace being built at `dest` (paths reported under `final`).

    Returns (repos block of the JSON, neighbour manifest entries, code.json)."""
    repos_json: dict[str, dict] = {}
    entries: list[dict] = []
    code = {"schema_version": CODE_SCHEMA_VERSION, "branch": p.branch, "base": p.base, "repos": {},
            "bundles": {}}
    if p.neighbours:
        (dest / "in" / "repos").mkdir(parents=True, exist_ok=True)
    for r in p.repos:
        if r.role == "target":
            head = gitcode.clone_target(r.name, r.url, dest / "rw" / "code" / r.name, branch=p.branch,
                                        base=p.base, created=r.created)
            repos_json[r.name] = {"role": "target", "path": str(final / "rw" / "code" / r.name),
                                  "branch": p.branch, "base": p.base, "head": head, "created": r.created}
            code["repos"][r.name] = {"role": "target", "ref": p.branch, "head": head, "created": r.created}
        else:
            head, cfg = gitcode.clone_neighbour(r.name, r.url, dest / "in" / "repos" / r.name, ref=r.ref)
            repos_json[r.name] = {"role": "neighbour", "path": str(final / "in" / "repos" / r.name),
                                  "branch": None, "base": r.ref, "head": head, "created": False}
            code["repos"][r.name] = {"role": "neighbour", "ref": r.ref or "HEAD", "head": head,
                                     "created": False, "config_sha256": cfg}
            entries.append({"key": layout.neighbour_key(r.name), "commit": head, "role": "neighbour"})
    return repos_json, entries, code


# --- code.json ---

def load(root: Path) -> dict | None:
    """code.json of a workspace, None when absent (a run without code). RunError when unreadable."""
    path = root / CODE_JSON
    if not os.path.lexists(path):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("repos"), dict) \
            or not isinstance(data.get("bundles", {}), dict):
        raise RunError("run_invalid", f"{root}: unreadable {CODE_JSON}")
    data.setdefault("bundles", {})
    return data


def save(root: Path, code: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{CODE_JSON}.", dir=root)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dump_json(code))
        os.replace(tmp, root / CODE_JSON)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def engine_files(code: dict) -> dict[str, str]:
    """`{"git/<repo>.bundle": sha256}` of the bundles recorded by the engine."""
    out = {}
    for repo, b in (code.get("bundles") or {}).items():
        if isinstance(b, dict) and isinstance(b.get("sha256"), str):
            out[layout.bundle_rel(validate_repo_name(repo))] = b["sha256"]
    return out


def targets(code: dict) -> list[str]:
    return sorted(r for r, v in code["repos"].items() if isinstance(v, dict) and v.get("role") == "target")


# --- checks (read only) ---

def check_code(root: Path, code: dict, manifest: dict | None) -> tuple[list[str], list[str]]:
    """Neighbours intact, targets well formed with their story branch. (reasons, warnings)."""
    reasons: list[str] = []
    warnings: list[str] = []
    entries = {e["key"]: e for e in (manifest or {}).get("files", [])
               if isinstance(e, dict) and "commit" in e and isinstance(e.get("key"), str)}
    for key in sorted(entries):
        repo = key.split("/", 1)[1] if key.startswith("repos/") else key
        path = root / "in" / key
        recorded = (code["repos"].get(repo) or {}) if isinstance(code["repos"].get(repo), dict) else {}
        ok = gitcode.scan_repo(path) is None and recorded.get("config_sha256") is not None \
            and gitcode.config_sha256(path) == recorded["config_sha256"]
        ok = ok and gitcode.head_commit(path) == entries[key]["commit"] and gitcode.neighbour_clean(path)
        if not ok:
            reasons.append(f"in_modified:{key}")
    branch = code.get("branch")
    base = code.get("base")
    for repo in targets(code):
        path = root / "rw" / "code" / repo
        if gitcode.scan_repo(path) is not None:
            reasons.append(f"code_invalid:{repo}")
            continue
        refs = gitcode.refs(path)
        if refs is None:
            reasons.append(f"code_invalid:{repo}")
            continue
        if f"refs/heads/{branch}" not in refs:
            reasons.append(f"branch_deleted:{repo}")
        if set(refs) - {f"refs/heads/{branch}", f"refs/heads/{base}"}:
            warnings.append(f"extra_refs_ignored:{repo}")
    return reasons, warnings


# --- bundles ---

def _file_sha256(path: Path) -> tuple[str, int] | None:
    h = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)
    except OSError:
        return None
    return h.hexdigest(), size


def bundle_code(root: Path, code: dict) -> tuple[dict, list[str]]:
    """Write `rw/out/git/<repo>.bundle` for every target with new commits (idempotent).

    Returns ({repo: sha | "unchanged"}, reasons); records each bundle in code.json."""
    heads: dict[str, str] = {}
    reasons: list[str] = []
    branch = code["branch"]
    for repo in targets(code):
        path = root / "rw" / "code" / repo
        refs = gitcode.refs(path) or {}
        sha = refs.get(f"refs/heads/{branch}")
        head = code["repos"][repo].get("head")
        if sha is None or not isinstance(head, str):
            reasons.append(f"code_invalid:{repo}")
            continue
        if sha == head:
            heads[repo] = "unchanged"
            continue
        heads[repo] = sha
        final = root / "rw" / "out" / layout.bundle_rel(repo)
        rec = code["bundles"].get(repo)
        if isinstance(rec, dict) and rec.get("sha") == sha and _file_sha256(final) == (rec.get("sha256"), rec.get("size")):
            continue
        tmp = root / f".{repo}.bundle.tmp"
        if not gitcode.write_bundle(path, tmp, branch=branch, head=head):
            reasons.append(f"code_invalid:{repo}")
            continue
        digest = _file_sha256(tmp)
        if digest is None:
            reasons.append(f"code_invalid:{repo}")
            continue
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, final)
        code["bundles"][repo] = {"sha": sha, "sha256": digest[0], "size": digest[1]}
        save(root, code)
    return heads, sorted(reasons)


# --- push (all repositories checked before the first push) ---

def push_code(root: Path, uid: str, code: dict, heads: dict, urls: dict[str, str | None]) -> tuple[dict, list[str]]:
    """Push every changed target from a fresh bare clone under `<root>/../_push/<uid>/`.

    Returns ({repo: {pushed, sha, branch} | "unchanged"}, reasons). Nothing is pushed on any repository
    when one of them is refused; the push folder is removed in every case."""
    branch = code["branch"]
    work = root.parent / "_push" / uid
    result: dict = {}
    reasons: list[str] = []
    try:
        shutil.rmtree(work, ignore_errors=True)
        hooks = work / ".hooks"
        hooks.mkdir(parents=True)
        todo: list[tuple[str, Path, str, str]] = []
        for repo in sorted(heads):
            sha = heads[repo]
            if sha == "unchanged":
                result[repo] = "unchanged"
                continue
            url = urls.get(repo)
            if not url:
                reasons.append(f"push_failed:{repo}")
                continue
            clone = work / f"{repo}.git"
            bundle = root / "rw" / "out" / layout.bundle_rel(repo)
            action, reason = gitcode.prepare_push(repo, url, clone, bundle, branch=branch, sha=sha, hooks=hooks)
            if reason:
                reasons.append(reason)
                continue
            result[repo] = {"pushed": True, "sha": sha, "branch": branch}
            if action == "push":
                todo.append((repo, clone, url, sha))
        if reasons:
            return result, sorted(reasons)
        for repo, clone, url, sha in todo:
            if not gitcode.push(clone, url, sha=sha, branch=branch, hooks=hooks):
                reasons.append(f"push_failed:{repo}")
        return result, sorted(reasons)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            os.rmdir(work.parent)
        except OSError:
            pass


def unpushed(code: dict, heads: dict) -> dict:
    """`git` block of a run that ends without push (outcome failed/timeout)."""
    return {repo: ("unchanged" if sha == "unchanged" else {"pushed": False, "sha": sha, "branch": code["branch"]})
            for repo, sha in sorted(heads.items())}
