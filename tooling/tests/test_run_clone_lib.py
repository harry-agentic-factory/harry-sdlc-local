"""Code run library contracts: injected `CodeHost` + in-memory backend (the worker case), no project."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import sdlc.runws as runws
from sdlc.runws import CodeHost, RepoSpec, RunError, Scope, doc_add, run_finish, run_init
from test_run_workspace import GIT_ID, RECAP_DOC, git, write
from test_run_workspace_lib import MemoryBackend

BRANCH = "feat/DEMO-E-1"


class FakeHost:
    """`CodeHost` over bare remotes of the test (targets / neighbours given by name)."""

    def __init__(self, remotes: Path, targets=("app-repo",), neighbours=("web-repo",)):
        self.remotes = remotes
        self.targets, self.neighbours = targets, neighbours
        self.calls = 0

    def code_repos(self, scope: Scope):
        self.calls += 1
        if scope.story is None:
            return []
        return [RepoSpec(n, "target", str(self.remotes / f"{n}.git")) for n in self.targets] + \
               [RepoSpec(n, "neighbour", str(self.remotes / f"{n}.git")) for n in self.neighbours]

    def default_base(self):
        return "main"


def remotes(tmp_path: Path, monkeypatch) -> Path:
    gcfg = tmp_path / "gitconfig"
    gcfg.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gcfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    base = tmp_path / "remotes"
    for repo in ("app-repo", "web-repo"):
        bare = base / f"{repo}.git"
        bare.parent.mkdir(exist_ok=True)
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
        work = tmp_path / f"seed-{repo}"
        git(tmp_path, "init", "-q", "-b", "main", str(work))
        write(work, "README.md", b"# seed\n")
        git(work, "add", "-A")
        git(work, *GIT_ID, "commit", "-q", "-m", "init")
        git(work, "push", "-q", str(bare), "main")
    return base


def rsha(base: Path, ref=BRANCH, repo="app-repo"):
    import subprocess
    p = subprocess.run(["git", "-C", str(base / f"{repo}.git"), "rev-parse", "--verify", "-q", ref],
                       capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def commit(repo: Path, msg: str) -> str:
    write(repo, f"{msg}.txt", msg.encode())
    git(repo, "add", "-A")
    git(repo, *GIT_ID, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def worker_init(tmp_path, mb, host, **kw):
    kw.setdefault("story", "DEMO-E-1")
    return run_init(None, agent="dev", root=tmp_path / "worker", backend=mb, code=True, code_host=host,
                    branch=BRANCH, base="main", **kw)


def test_code_host_injected_without_project(tmp_path, monkeypatch):
    base = remotes(tmp_path, monkeypatch)
    before = sorted(os.listdir(tmp_path))
    mb, host = MemoryBackend(), FakeHost(base)
    res = worker_init(tmp_path, mb, host)
    root = Path(res["root"])
    assert set(res["repos"]) == {"app-repo", "web-repo"} and res["repos"]["app-repo"]["created"] is True
    assert (root / "code.json").is_file() and (root / "in" / "repos" / "web-repo" / "README.md").is_file()
    c1 = commit(root / "rw" / "code" / "app-repo", "c1")
    doc_add("implement", RECAP_DOC, run=root)
    write(root / "rw" / "out", "sources/x.md", b"# x\n")
    fin = run_finish(root, backend=mb, code_host=host)
    uid = res["run_uid"]
    assert fin["state"] == "published" and fin["git"] == {"app-repo": {"pushed": True, "sha": c1, "branch": BRANCH}}
    assert rsha(base) == c1 and host.calls == 2         # re-resolved at finish, never read in the run
    keys = [k for k, _ in mb.puts]
    assert keys == [f"runs/{uid}/out/docs/implement.md", f"runs/{uid}/out/sources/x.md",
                    f"runs/{uid}/out/git/app-repo.bundle", f"runs/{uid}/manifest.json", f"runs/{uid}/run.json"]
    assert [m["category"] for _, m in mb.puts] == ["artifact", "source", "bundle", "run_meta", "run_meta"]
    assert sorted(os.listdir(tmp_path)) == sorted(before + ["worker"])
    assert os.listdir(tmp_path / "worker") == []          # workspace cleaned, _push removed


def test_outcome_publishes_bundle_without_push(tmp_path, monkeypatch):
    base = remotes(tmp_path, monkeypatch)
    mb, host = MemoryBackend(), FakeHost(base)
    res = worker_init(tmp_path, mb, host)
    c1 = commit(Path(res["root"]) / "rw" / "code" / "app-repo", "c1")
    fin = run_finish(res["root"], backend=mb, outcome="failed")        # container stopped: no CodeHost needed
    assert fin["state"] == "failed" and fin["git"] == {"app-repo": {"pushed": False, "sha": c1, "branch": BRANCH}}
    assert rsha(base) is None
    bundle = mb.store[f"runs/{res['run_uid']}/out/git/app-repo.bundle"]
    assert bundle.startswith(b"# v2 git bundle") or bundle.startswith(b"# v3 git bundle")
    assert json.loads(mb.store[f"runs/{res['run_uid']}/run.json"])["state"] == "failed"


def test_code_true_requires_code_host(tmp_path, monkeypatch):
    mb = MemoryBackend()
    with pytest.raises(RunError) as e:
        run_init(None, agent="dev", story="DEMO-E-1", root=tmp_path / "w", backend=mb, code=True, branch=BRANCH)
    assert e.value.code == "code_host_required" and not (tmp_path / "w").exists()
    with pytest.raises(RunError) as e:            # a code option on a backend without run workspace
        run_init(None, agent="dev", story="DEMO-E-1", root=tmp_path / "w", backend=mb, branch=BRANCH)
    assert e.value.code == "run_workspace_disabled"
    with pytest.raises(RunError) as e:            # a transition needs backend.transition
        run_init(None, agent="dev", story="DEMO-E-1", root=tmp_path / "w", backend=mb, code=True,
                 code_host=FakeHost(tmp_path, targets=(), neighbours=()), status="reviewed")
    assert e.value.code == "status_unsupported" and not (tmp_path / "w").exists()


def test_outcome_status_conflict(tmp_path, monkeypatch):
    base = remotes(tmp_path, monkeypatch)
    mb, host = MemoryBackend(), FakeHost(base)
    res = worker_init(tmp_path, mb, host)
    with pytest.raises(RunError) as e:
        run_finish(res["root"], backend=mb, outcome="failed", status="reviewed")
    assert e.value.code == "outcome_status_conflict" and Path(res["root"]).is_dir() and mb.puts == []


def test_mission_code_run_publishes_sources(tmp_path, monkeypatch):
    mb = MemoryBackend({"missions/inc-1/brief.md": b"# brief\n"}, scope=Scope(None, None, "inc-1"))
    host = FakeHost(tmp_path)
    res = run_init(None, agent="ops", mission="inc-1", root=tmp_path / "w", backend=mb, code=True, code_host=host)
    assert res["repos"] == {} and host.calls == 0
    write(Path(res["root"]) / "rw" / "out", "sources/a.md", b"a\n")
    fin = run_finish(res["root"], backend=mb, code_host=host)
    assert fin["git"] == {} and f"runs/{res['run_uid']}/out/sources/a.md" in mb.store


def test_public_api_additions():
    for name in ("code_clone", "CodeHost", "RepoSpec", "SOURCE_MAX_BYTES", "RUN_SOURCES_MAX_BYTES"):
        assert name in runws.__all__ and hasattr(runws, name)
    assert runws.SOURCE_MAX_BYTES == 50 * 1024 * 1024 and runws.RUN_SOURCES_MAX_BYTES == 200 * 1024 * 1024
    assert isinstance(FakeHost(Path(".")), CodeHost)
    assert RepoSpec("r", "target", None).missing is None
    import inspect
    init = inspect.signature(runws.run_init).parameters
    for p in ("branch", "base", "repro", "repro_dir", "status", "code", "code_host"):
        assert init[p].default is None and init[p].kind is inspect.Parameter.KEYWORD_ONLY
    fin = inspect.signature(runws.run_finish).parameters
    assert fin["status"].default is None and fin["code_host"].default is None
