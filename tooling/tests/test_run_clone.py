"""Code runs (`runWorkspace: true`): `sdlc run init` clones, `sdlc run finish` bundles, pushes, publishes.

Fixture (P): the DEMO project of `test_run_workspace.py` (imported, unchanged) + two bare remotes
`remotes/app-repo.git` and `remotes/web-repo.git` (one commit on `main`), their local copies under
`reposRoot` with `origin` set (`file://` URL for app-repo, plain path for web-repo), `repos: [app-repo,
web-repo]`, `DEMO-E-1.repos = [app-repo]`, story at `implemented`, `GIT_TOKEN` sentinel exported and
the host git configuration isolated (`GIT_CONFIG_GLOBAL` = empty file of the test).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdlc import Sdlc, Workspace
from sdlc.runws import RUN_JSON_KEYS, gitcode
from sdlc.runws.datarepo import DataRepoBackend
from test_run_workspace import GIT_ID, RECAP_DOC, Demo, add, call, git, make_demo, porcelain, write

SENTINEL = "sentinel-7f3a"
BRANCH = "feat/DEMO-E-1"


@dataclass
class CodeDemo:
    demo: Demo
    tmp: Path

    @property
    def data(self) -> Path:
        return self.demo.data

    def remote(self, repo: str = "app-repo") -> Path:
        return self.tmp / "remotes" / f"{repo}.git"

    def local(self, repo: str = "app-repo") -> Path:
        return self.tmp / repo

    def rsha(self, ref: str = BRANCH, repo: str = "app-repo") -> str | None:
        p = subprocess.run(["git", "-C", str(self.remote(repo)), "rev-parse", "--verify", "-q", ref],
                           capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None

    def config(self, **extra) -> None:
        cfg = json.loads((self.data / "sdlc.config.json").read_text())
        cfg.update(extra)
        for k in [k for k, v in extra.items() if v is None]:
            cfg.pop(k)
        (self.data / "sdlc.config.json").write_text(json.dumps(cfg))
        commit(self.data, "config")

    def story_repos(self, *repos: str, story: str = "DEMO-E-1") -> None:
        ws = Workspace(self.data)
        t = ws.load(story)
        t.repos = list(repos)
        ws.save(t)
        commit(self.data, "repos")

    def status(self, story: str = "DEMO-E-1") -> str:
        return Workspace(self.data).load(story).status

    def set_status(self, *statuses: str, story: str = "DEMO-E-1") -> None:
        for st in statuses:
            Sdlc(Workspace(self.data)).set_status(story, st)
        commit(self.data, "status")

    def push_remote(self, repo: str, branch: str, msg: str) -> str:
        """A third party pushes a commit on `branch` of the remote (from a scratch clone)."""
        work = self.tmp / f"third-{repo}-{msg}"
        git(self.tmp, "clone", "-q", str(self.remote(repo)), str(work))
        p = subprocess.run(["git", "-C", str(work), "checkout", "-q", branch], capture_output=True)
        if p.returncode != 0:
            git(work, "checkout", "-q", "-b", branch)
        write(work, f"{msg}.txt", msg.encode())
        git(work, "add", "-A")
        git(work, *GIT_ID, "commit", "-q", "-m", msg)
        git(work, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        return git(work, "rev-parse", "HEAD")


def commit(repo: Path, msg: str) -> None:
    git(repo, "add", "-A")
    subprocess.run(["git", "-C", str(repo), *GIT_ID, "commit", "-q", "-m", msg], capture_output=True)


def make_code_demo(tmp_path: Path, monkeypatch, *, activate: bool = True) -> CodeDemo:
    demo = make_demo(tmp_path, monkeypatch)
    gcfg = tmp_path / "gitconfig"
    gcfg.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gcfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TOKEN", SENTINEL)
    for repo in ("app-repo", "web-repo"):
        bare = tmp_path / "remotes" / f"{repo}.git"
        bare.parent.mkdir(exist_ok=True)
        git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
        local = tmp_path / repo
        git(tmp_path, "init", "-q", "-b", "main", str(local))
        write(local, "README.md", f"# {repo}\n".encode())
        git(local, "add", "-A")
        git(local, *GIT_ID, "commit", "-q", "-m", "init")
        url = ("file://" + str(bare)) if repo == "app-repo" else str(bare)
        git(local, "remote", "add", "origin", url)
        git(local, "push", "-q", "origin", "main")
    cd = CodeDemo(demo, tmp_path)
    cd.config(repos=["app-repo", "web-repo"], **({"runWorkspace": True} if activate else {}))
    cd.story_repos("app-repo")
    cd.set_status("implemented")
    return cd


@pytest.fixture
def cap(capsysbinary):
    return capsysbinary


@pytest.fixture
def cdemo(tmp_path, monkeypatch) -> CodeDemo:
    return make_code_demo(tmp_path, monkeypatch)


# --- helpers ---

def ok(cap, *argv) -> dict:
    rc, out, err = call(cap, *argv)
    assert rc == 0, err
    return json.loads(out)


def refused(cap, *argv) -> str:
    rc, out, err = call(cap, *argv)
    assert rc != 0, out
    return json.loads(err)["error"]


def rinit(cap, *extra, agent: str = "reviewer", story: str = "DEMO-E-1", branch: str | None = BRANCH) -> dict:
    return ok(cap, "run", "init", story, "--agent", agent, *(["--branch", branch] if branch else []), *extra)


def finish(cap, uid: str, *extra) -> tuple[int, dict]:
    rc, out, err = call(cap, "run", "finish", uid, *extra)
    assert out, err
    return rc, json.loads(out)


def code_of(res: dict, repo: str = "app-repo") -> Path:
    return Path(res["repos"][repo]["path"])


def agent_commit(repo: Path, msg: str, name: str | None = None) -> str:
    write(repo, name or f"{msg}.txt", f"{msg}\n".encode())
    git(repo, "add", "-A")
    git(repo, *GIT_ID, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def review(cap, monkeypatch, res: dict, doc_type: str = "review") -> None:
    rc, _, err = add(cap, monkeypatch, doc_type, RECAP_DOC, res["root"])
    assert rc == 0, err


def agentws(cd: CodeDemo, scope: str = "DEMO-E-1") -> list[str]:
    base = cd.tmp / "_agentws" / "DEMO" / scope
    return sorted(os.listdir(base)) if base.is_dir() else []


def spy_git(monkeypatch) -> list[tuple[str, tuple, object]]:
    """Record every (helper, argv, cwd/repo) of gitcode while letting it run."""
    calls: list = []
    trusted, untrusted = gitcode._git_trusted, gitcode._git_untrusted

    def t(*args, cwd=None):
        calls.append(("trusted", args, cwd))
        return trusted(*args, cwd=cwd)

    def u(repo, *args, **kw):
        calls.append(("untrusted", args, repo))
        return untrusted(repo, *args, **kw)

    monkeypatch.setattr(gitcode, "_git_trusted", t)
    monkeypatch.setattr(gitcode, "_git_untrusted", u)
    return calls


# --- AC1: activation per project ---

def test_ac1_config_exposes_key_only_if_present(tmp_path, monkeypatch, cap):
    cd = make_code_demo(tmp_path, monkeypatch, activate=False)
    assert "runWorkspace" not in ok(cap, "config")
    cd.config(runWorkspace=True)
    assert ok(cap, "config")["runWorkspace"] is True
    cd.config(runWorkspace=False)
    assert ok(cap, "config")["runWorkspace"] is False


def test_ac1_off_project_no_clone(tmp_path, monkeypatch, cap):
    cd = make_code_demo(tmp_path, monkeypatch, activate=False)
    res = ok(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer")
    root = Path(res["root"])
    assert os.listdir(root / "rw" / "code") == [] and not (root / "in" / "repos").exists()
    assert not (root / "code.json").exists() and "repos" not in res and "status" not in res
    deny = json.loads(Path(res["settings"]).read_text())["permissions"]["deny"]
    assert "Bash(git push:*)" not in deny and "Bash(git remote:*)" not in deny


@pytest.mark.parametrize("opt", [["--branch", BRANCH], ["--base", "main"], ["--repro", "20260101-000000-aaaaaa"],
                                 ["--repro-dir", "/x"], ["--status", "reviewed"]])
def test_off_options_refused_disabled(tmp_path, monkeypatch, cap, opt):
    cd = make_code_demo(tmp_path, monkeypatch, activate=False)
    err = refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", *opt)
    assert err == f"run_workspace_disabled:{opt[0]}"
    assert agentws(cd) == [] and cd.status() == "implemented"


def test_off_finish_status_refused_disabled(tmp_path, monkeypatch, cap):
    cd = make_code_demo(tmp_path, monkeypatch, activate=False)
    res = ok(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer")
    assert refused(cap, "run", "finish", res["run_uid"], "--status", "reviewed") == "run_workspace_disabled:--status"
    assert Path(res["root"]).is_dir() and cd.status() == "implemented"


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_run_workspace_invalid_value(tmp_path, monkeypatch, cap, value):
    cd = make_code_demo(tmp_path, monkeypatch, activate=False)
    cfg = json.loads((cd.data / "sdlc.config.json").read_text())
    cfg["runWorkspace"] = value
    (cd.data / "sdlc.config.json").write_text(json.dumps(cfg))
    if value is None:                            # explicit null = absent: run without code
        assert "repos" not in ok(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer")
        return
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer").startswith("run_workspace_invalid:")
    assert agentws(cd) == []


# --- AC2: target clone, no remote, no credential ---

def test_ac2_target_clone_branch_base_no_remote(cdemo, cap):
    res = rinit(cap)
    app = code_of(res)
    assert app == Path(res["root"]) / "rw" / "code" / "app-repo"
    assert git(app, "branch", "--show-current") == BRANCH
    assert git(app, "rev-parse", "--verify", "main") == cdemo.rsha("main")
    assert git(app, "remote") == ""
    assert res["repos"]["app-repo"] == {"role": "target", "path": str(app), "branch": BRANCH, "base": "main",
                                        "head": cdemo.rsha("main"), "created": True}
    heads = git(app, "for-each-ref", "--format=%(refname)").splitlines()
    assert sorted(heads) == ["refs/heads/feat/DEMO-E-1", "refs/heads/main"]
    assert git(app, "tag") == ""


def test_ac2_local_config_has_no_remote_credential_http_url(cdemo, cap):
    res = rinit(cap)
    for repo in (code_of(res), code_of(res, "web-repo")):
        lines = git(repo, "config", "--local", "--list").splitlines()
        assert [x for x in lines if re.match(r"^(remote|credential|http|url)\.", x)] == []
        assert not (repo / ".git" / "logs").exists()


# --- AC3: existing branch resumed, absent created from the base ---

def test_ac3_existing_branch_resumed_created_false(cdemo, cap, monkeypatch):
    first = rinit(cap)
    assert first["repos"]["app-repo"]["created"] is True
    assert git(code_of(first), "rev-parse", "HEAD") == cdemo.rsha("main")
    c1 = agent_commit(code_of(first), "c1")
    review(cap, monkeypatch, first)
    rc, fin = finish(cap, first["run_uid"], "--status", "reviewed")
    assert rc == 0 and cdemo.rsha() == c1
    second = rinit(cap)
    assert second["repos"]["app-repo"]["created"] is False
    assert git(code_of(second), "rev-parse", "HEAD") == c1 == second["repos"]["app-repo"]["head"]
    assert git(code_of(second), "rev-parse", "main") == cdemo.rsha("main")


# --- AC4: neighbours read only, pinned in the manifest ---

def test_ac4_neighbour_shallow_manifest_commit(cdemo, cap):
    second = cdemo.push_remote("web-repo", "main", "w2")
    res = rinit(cap)
    web = code_of(res, "web-repo")
    assert web == Path(res["root"]) / "in" / "repos" / "web-repo"
    assert git(web, "rev-list", "--count", "HEAD") == "1" and git(web, "rev-parse", "HEAD") == second
    assert git(web, "remote") == ""
    man = json.loads(Path(res["manifest"]).read_text())
    entry = [e for e in man["files"] if e["key"] == "repos/web-repo"]
    assert entry == [{"key": "repos/web-repo", "commit": second, "role": "neighbour"}]
    assert res["repos"]["web-repo"] == {"role": "neighbour", "path": str(web), "branch": None, "base": "main",
                                        "head": second, "created": False}
    assert not (Path(res["root"]) / "in" / "repos" / "app-repo").exists()
    assert "repos/web-repo" not in man["dirty"]


def test_ac4_bubble_git_deny(cdemo, cap):
    res = rinit(cap)
    deny = json.loads(Path(res["settings"]).read_text())["permissions"]["deny"]
    root = res["root"]
    assert deny[-4:] == [f"Edit(/{root}/in/**)", f"Write(/{root}/in/**)", "Bash(git push:*)", "Bash(git remote:*)"]


def test_neighbour_base_fallback_warning(cdemo, cap):
    cdemo.config(refBranch="release/V0")
    cdemo.push_remote("app-repo", "develop", "d1")
    res = rinit(cap, "--base", "develop")
    assert "neighbour_base_fallback:web-repo" in res["warnings"]
    assert res["repos"]["web-repo"]["base"] is None
    code = json.loads((Path(res["root"]) / "code.json").read_text())
    assert code["repos"]["web-repo"]["ref"] == "HEAD"


def test_neighbour_head_fallback_without_branch_flag(cdemo, cap, monkeypatch):
    cdemo.config(refBranch="release/V0")
    cdemo.push_remote("app-repo", "develop", "d1")
    calls = spy_git(monkeypatch)
    res = rinit(cap, "--base", "develop")
    clones = [a for h, a, _ in calls if h == "trusted" and a[:1] == ("clone",) and "--depth" in a]
    assert len(clones) == 1 and "--branch" not in clones[0]
    assert res["repos"]["web-repo"]["head"] == cdemo.rsha("HEAD", "web-repo")
    # a neighbour holding the base (or refBranch) is cloned on it, `--branch` after its value
    cdemo.config(refBranch="main")
    calls.clear()
    rinit(cap)
    clones = [a for h, a, _ in calls if h == "trusted" and a[:1] == ("clone",) and "--depth" in a]
    assert clones[0][clones[0].index("--branch") + 1] == "main" and clones[0][-3] == "--"


# --- AC5: no remote, unresolved, clone failure: nothing created ---

def test_ac5_no_remote_creates_nothing(cdemo, cap):
    git(cdemo.local(), "remote", "remove", "origin")
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", "--branch", BRANCH) == "no_remote:app-repo"
    assert agentws(cdemo) == []


def test_neighbour_no_remote_refused(cdemo, cap):
    git(cdemo.local("web-repo"), "remote", "remove", "origin")
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", "--branch", BRANCH) == "no_remote:web-repo"
    assert agentws(cdemo) == []


def test_target_unresolved_refused(cdemo, cap):
    cdemo.story_repos("ghost-repo")
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", "--branch", BRANCH) == \
        "repo_unresolved:ghost-repo"
    assert agentws(cdemo) == []


def test_neighbour_unresolved_warning(cdemo, cap):
    cdemo.config(repos={"app-repo": None, "web-repo": None, "gone-repo": str(cdemo.tmp / "nowhere")})
    res = rinit(cap)
    assert "repo_unresolved:gone-repo" in res["warnings"] and "gone-repo" not in res["repos"]


def test_base_unknown_refused(cdemo, cap):
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", "--branch", BRANCH, "--base", "nope") == \
        "base_unknown:app-repo:nope"
    assert agentws(cdemo) == []


def test_clone_failure_leaves_no_partial(cdemo, cap, monkeypatch):
    real = gitcode.clone_neighbour

    def boom(name, url, dest, *, ref):
        real(name, url, dest, ref=ref)
        raise gitcode.RunError("clone_failed", name)

    monkeypatch.setattr(gitcode, "clone_neighbour", boom)
    cdemo.set_status("reviewed", "deployed")
    err = refused(cap, "run", "init", "DEMO-E-1", "--agent", "fixer", "--branch", BRANCH, "--status", "implemented")
    assert err == "clone_failed:web-repo"
    assert agentws(cdemo) == [] and cdemo.status() == "deployed"


def test_branch_required(cdemo, cap):
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer") == "branch_required:DEMO-E-1"
    ws = Workspace(cdemo.data)
    t = ws.load("DEMO-E-1")
    t.branch = BRANCH
    ws.save(t)
    assert rinit(cap, branch=None)["repos"]["app-repo"]["branch"] == BRANCH


def test_branch_protected(cdemo, cap):
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", "--branch", "main") == "branch_protected:main"
    cdemo.push_remote("app-repo", "develop", "d1")
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", "--branch", "develop", "--base",
                   "develop") == "branch_protected:develop"
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", "--branch", "main", "--base",
                   "develop") == "branch_protected:main"
    assert agentws(cdemo) == []


@pytest.mark.parametrize("argv", [["--branch=-oops"], ["--branch", "a..b"], ["--branch", "a b"],
                                  ["--branch", BRANCH, "--base=--upload-pack=x"], ["--branch", "x.lock"]])
def test_branch_option_injection(cdemo, cap, monkeypatch, argv):
    calls = spy_git(monkeypatch)
    err = refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", *argv)
    assert err.startswith("branch_invalid:")
    assert calls == [] and agentws(cdemo) == []


# --- AC6: no token, no URL in the workspace ---

def test_ac6_no_token_no_url_in_workspace(cdemo, cap):
    res = rinit(cap)
    root = Path(res["root"])
    hits = [p for p in root.rglob("*") if p.is_file() and SENTINEL.encode() in p.read_bytes()]
    assert hits == []
    engine = [root / "code.json", root / "run.json", root / "seal.json", root / "in" / "manifest.json",
              root / "in" / "settings.json", code_of(res) / ".git" / "config",
              code_of(res, "web-repo") / ".git" / "config"]
    for f in engine:
        text = f.read_text()
        assert not re.search(r"://|^[^ ]+@[^ ]+:", text, re.M), f
        assert "remotes/" not in text, f
    code = json.loads((root / "code.json").read_text())
    assert set(code) == {"schema_version", "branch", "base", "repos", "bundles"} and code["bundles"] == {}
    assert code["repos"]["app-repo"] == {"role": "target", "ref": BRANCH, "head": cdemo.rsha("main"),
                                         "created": True}
    assert set(code["repos"]["web-repo"]) == {"role", "ref", "head", "created", "config_sha256"}


# --- AC7: finish = bundle, push from a fresh clone, transition, trace ---

def test_ac7_finish_bundle_push_status_trace(cdemo, cap, monkeypatch):
    res = rinit(cap)
    c1 = agent_commit(code_of(res), "c1")
    review(cap, monkeypatch, res)
    write(Path(res["out"]), "sources/notes/log.txt", b"trace\n")
    rc, fin = finish(cap, res["run_uid"], "--status", "reviewed")
    uid = res["run_uid"]
    assert rc == 0 and fin["state"] == "published"
    assert fin["git"] == {"app-repo": {"pushed": True, "sha": c1, "branch": BRANCH}}
    assert fin["status"] == {"from": "implemented", "to": "reviewed", "applied": True}
    assert "sources_not_published" not in fin["warnings"]
    assert cdemo.rsha() == c1 and cdemo.status() == "reviewed"
    trace = cdemo.data / "runs" / uid
    heads = git(cdemo.tmp, "bundle", "list-heads", str(trace / "out" / "git" / "app-repo.bundle")).splitlines()
    assert heads == [f"{c1} refs/heads/{BRANCH}"]
    assert (trace / "out" / "sources" / "notes" / "log.txt").read_bytes() == b"trace\n"
    run = json.loads((trace / "run.json").read_text())
    assert run["state"] == "published" and run["story"] == "DEMO-E-1" and tuple(sorted(run)) == RUN_JSON_KEYS
    assert not Path(res["root"]).exists() and not (cdemo.tmp / "_agentws" / "DEMO" / "DEMO-E-1" / "_push").exists()
    assert not (Path(res["root"]).parent.parent / "_push").exists()


# --- AC8: the agent's .git is never used ---

def test_ac8_agent_git_config_and_hooks_ignored(cdemo, cap, monkeypatch):
    res = rinit(cap)
    app = code_of(res)
    scratch = Path(res["scratch"])
    pwned = scratch / "pwned"
    hook = f"#!/bin/sh\necho x > {pwned}\nexit 1\n"
    for d in (app / ".git" / "hooks", scratch):
        write(d, "pre-push", hook.encode()).chmod(0o755)
    git(app, "config", "core.hooksPath", str(scratch))
    git(app, "config", f"url.file:///nowhere/.insteadOf", "file://" + str(cdemo.remote()))
    git(app, "config", "core.fsmonitor", f"{scratch}/pre-push")
    c2 = agent_commit(app, "c2")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 0, fin
    assert not pwned.exists() and cdemo.rsha() == c2


def test_push_never_uses_agent_git_dir(cdemo, cap, monkeypatch):
    res = rinit(cap)
    agent_commit(code_of(res), "c1")
    calls = spy_git(monkeypatch)
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 0 and fin["git"]["app-repo"]["pushed"] is True
    push_dir = Path(res["root"]).parent / "_push" / res["run_uid"]
    net = [(a, c) for h, a, c in calls if {"push", "fetch", "clone"} & set(a)]
    assert {x for a, _ in net for x in a} >= {"push", "fetch", "clone"}
    for args, cwd in net:
        if "clone" in args:
            assert Path(args[-1]).parent == push_dir
        else:
            assert Path(cwd).parent == push_dir, (args, cwd)
    for h, a, repo in calls:
        if h == "untrusted":
            assert a[0] in {"rev-parse", "for-each-ref", "bundle", "status"}
            assert a[0] != "status" or "in/repos/" in str(repo)


def test_untrusted_whitelist_and_options(tmp_path, monkeypatch):
    with pytest.raises(gitcode.RunError) as e:
        gitcode._git_untrusted(tmp_path, "push", "x")
    assert e.value.code == "git_refused"
    seen = []
    monkeypatch.setattr(gitcode, "subprocess", SimpleNamespace(
        run=lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0, b"", b"")))
    for sub in ("rev-parse", "for-each-ref", "bundle", "status"):
        gitcode._git_untrusted(tmp_path, sub)
    for argv in seen:
        assert argv[:9] == ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c",
                            f"core.hooksPath={os.devnull}", "-c", "core.untrackedCache=false", "-C"]


def test_git_argv_env_no_credentials(cdemo, cap, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(argv, **kw):
        seen.append((list(argv), kw.get("env", None)))
        return real(argv, **kw)

    monkeypatch.setattr(gitcode, "subprocess", SimpleNamespace(run=spy))     # gitcode calls only
    res = rinit(cap)
    agent_commit(code_of(res), "c1")
    assert finish(cap, res["run_uid"])[0] == 0
    assert len(seen) > 10
    for argv, env in seen:
        joined = " ".join(argv)
        assert not re.search(r"-c (credential|http|url)\.", joined), joined
        # nothing added; only the variables locating a repository are removed (D4)
        assert env == {k: v for k, v in os.environ.items() if k not in gitcode.LOCATION_ENV}
        assert SENTINEL in env.values()
        assert SENTINEL not in joined


# --- AC9: only the story branch, never forced ---

def test_ac9_only_story_branch_extra_refs_ignored(cdemo, cap, monkeypatch):
    res = rinit(cap)
    app = code_of(res)
    agent_commit(app, "c1")
    git(app, "branch", "hack")
    git(app, "tag", "t1")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 0 and "extra_refs_ignored:app-repo" in fin["warnings"]
    shown = git(cdemo.remote(), "show-ref")
    assert not re.search(r"hack|t1", shown)
    bundle = cdemo.data / "runs" / res["run_uid"] / "out" / "git" / "app-repo.bundle"
    assert len(git(cdemo.tmp, "bundle", "list-heads", str(bundle)).splitlines()) == 1


def test_ac9_non_fast_forward_nothing_published(cdemo, cap, monkeypatch):
    first = rinit(cap)
    agent_commit(code_of(first), "c1")
    assert finish(cap, first["run_uid"])[0] == 0
    res = rinit(cap)
    c9 = cdemo.push_remote("app-repo", BRANCH, "c9")
    app = code_of(res)
    write(app, "amend.txt", b"amended\n")
    git(app, "add", "-A")
    git(app, *GIT_ID, "commit", "-q", "--amend", "-m", "c1 rewritten")
    review(cap, monkeypatch, res)
    before = porcelain(cdemo.data)
    rc, fin = finish(cap, res["run_uid"], "--status", "reviewed")
    assert rc == 1 and fin["state"] == "rejected" and fin["reasons"] == ["non_fast_forward:app-repo"]
    assert cdemo.rsha() == c9 and porcelain(cdemo.data) == before
    assert Path(res["root"]).is_dir() and cdemo.status() == "implemented"
    assert not (cdemo.data / "runs" / res["run_uid"]).exists()


def test_non_ff_on_second_repo_blocks_all_pushes(cdemo, cap, monkeypatch):
    cdemo.story_repos("app-repo", "web-repo")
    first = rinit(cap)
    agent_commit(code_of(first), "a1")
    agent_commit(code_of(first, "web-repo"), "w1")
    rc, fin = finish(cap, first["run_uid"])
    assert rc == 0 and set(fin["git"]) == {"app-repo", "web-repo"}
    res = rinit(cap)
    a2 = agent_commit(code_of(res), "a2")
    agent_commit(code_of(res, "web-repo"), "w2")
    app_before = cdemo.rsha()
    w9 = cdemo.push_remote("web-repo", BRANCH, "w9")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["non_fast_forward:web-repo"]
    assert cdemo.rsha() == app_before != a2 and cdemo.rsha(repo="web-repo") == w9


def test_rewritten_base_is_non_fast_forward(cdemo, cap):
    res = rinit(cap)
    agent_commit(code_of(res), "c1")
    work = cdemo.tmp / "rewrite"
    git(cdemo.tmp, "init", "-q", "-b", "main", str(work))
    write(work, "new.txt", b"new root\n")
    git(work, "add", "-A")
    git(work, *GIT_ID, "commit", "-q", "-m", "new root")
    git(work, "push", "-q", "--force", str(cdemo.remote()), "main")
    git(cdemo.remote(), "reflog", "expire", "--expire=now", "--all")
    git(cdemo.remote(), "gc", "-q", "--prune=now")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["non_fast_forward:app-repo"] and cdemo.rsha() is None


# --- AC10: nothing to push; agent file in rw/out/git ---

def test_ac10_no_commit_unchanged(cdemo, cap, monkeypatch):
    res = rinit(cap)
    review(cap, monkeypatch, res)
    rc, fin = finish(cap, res["run_uid"], "--status", "reviewed")
    assert rc == 0 and fin["git"] == {"app-repo": "unchanged"} and cdemo.rsha() is None
    assert not (cdemo.data / "runs" / res["run_uid"] / "out" / "git").exists()
    assert cdemo.status() == "reviewed"


def test_ac10_agent_bundle_rejected(cdemo, cap):
    res = rinit(cap)
    agent_commit(code_of(res), "c1")
    write(Path(res["out"]), "git/x.bundle", b"forged")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["unexpected_file:git/x.bundle"] and cdemo.rsha() is None


def test_forged_recorded_bundle_rejected(cdemo, cap):
    first = rinit(cap)
    agent_commit(code_of(first), "c1")
    assert finish(cap, first["run_uid"])[0] == 0
    res = rinit(cap)
    agent_commit(code_of(res), "c2")
    c9 = cdemo.push_remote("app-repo", BRANCH, "c9")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["non_fast_forward:app-repo"]
    bundle = Path(res["out"]) / "git" / "app-repo.bundle"
    assert bundle.is_file()                           # engine bundle, recorded: admitted on replay
    rc, fin = finish(cap, res["run_uid"])
    assert fin["reasons"] == ["non_fast_forward:app-repo"]
    bundle.write_bytes(bundle.read_bytes() + b"x")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["unexpected_file:git/app-repo.bundle"] and cdemo.rsha() == c9


# --- AC11: modified neighbour ---

def test_ac11_neighbour_modified_rejected(cdemo, cap):
    res = rinit(cap)
    agent_commit(code_of(res), "c1")
    with open(code_of(res, "web-repo") / "README.md", "a") as f:
        f.write("x\n")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["in_modified:repos/web-repo"] and cdemo.rsha() is None


def test_ac11_neighbour_head_moved_or_ignored_file(cdemo, cap):
    res = rinit(cap)
    web = code_of(res, "web-repo")
    write(web, "build/out.o", b"x")
    write(web, ".git/info/exclude", b"build/\n")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["in_modified:repos/web-repo"]


def test_neighbour_fsmonitor_never_runs(cdemo, cap):
    res = rinit(cap)
    web = code_of(res, "web-repo")
    witness = Path(res["scratch"]) / "witness"
    script = write(Path(res["scratch"]), "mon.sh", f"#!/bin/sh\necho x > {witness}\n".encode())
    script.chmod(0o755)
    with open(web / ".git" / "config", "a") as f:
        f.write(f"[core]\n\tfsmonitor = {script}\n")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["in_modified:repos/web-repo"] and not witness.exists()


@pytest.mark.parametrize("case", ["target_git_file", "target_alternates", "target_link", "neighbour_alternates",
                                  "neighbour_commondir"])
def test_git_dir_file_or_alternates_rejected(cdemo, cap, monkeypatch, case):
    res = rinit(cap)
    app, web = code_of(res), code_of(res, "web-repo")
    if case == "target_git_file":
        os.rename(app / ".git", Path(res["scratch"]) / "moved.git")
        write(app, ".git", f"gitdir: {Path(res['scratch']) / 'moved.git'}\n".encode())
    elif case == "target_alternates":
        write(app, ".git/objects/info/alternates", str(cdemo.remote() / "objects").encode())
    elif case == "target_link":
        os.rename(app / ".git", Path(res["scratch"]) / "moved.git")
        os.symlink(Path(res["scratch"]) / "moved.git", app / ".git")
    elif case == "neighbour_alternates":
        write(web, ".git/objects/info/alternates", b"/elsewhere\n")
    else:
        write(web, ".git/commondir", b"/elsewhere\n")
    calls = spy_git(monkeypatch)
    rc, fin = finish(cap, res["run_uid"])
    expected = "code_invalid:app-repo" if case.startswith("target") else "in_modified:repos/web-repo"
    assert rc == 1 and expected in fin["reasons"]
    touched = app if case.startswith("target") else web
    assert not [c for c in calls if c[0] == "untrusted" and Path(c[2]) == touched]


def test_branch_deleted(cdemo, cap):
    res = rinit(cap)
    app = code_of(res)
    git(app, "checkout", "-q", "main")
    git(app, "branch", "-D", BRANCH)
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["branch_deleted:app-repo"]


# --- AC12: repro of the tester given to the fixer ---

def test_ac12_repro_from_trace_to_fixer(cdemo, cap, monkeypatch):
    cdemo.set_status("reviewed", "deployed")
    rec = rinit(cap, agent="recetteur")
    write(Path(rec["out"]), "sources/repro/steps.md", b"# steps\n1. login\n")
    write(Path(rec["out"]), "sources/repro/deep/env.md", b"# env\n")
    write(Path(rec["out"]), "sources/repro/trace.bin", b"\x00\x01")
    review(cap, monkeypatch, rec, "acceptance")
    rc, fin = finish(cap, rec["run_uid"])
    assert rc == 0
    uid = rec["run_uid"]
    fx = rinit(cap, "--repro", uid, "--status", "implemented", agent="fixer")
    root = Path(fx["root"])
    published = cdemo.data / "runs" / uid / "out" / "sources" / "repro"
    assert (root / "in" / "repro" / "steps.md").read_bytes() == (published / "steps.md").read_bytes()
    assert (root / "in" / "repro" / "deep" / "env.md").is_file() and not (root / "in" / "repro" / "trace.bin").exists()
    man = json.loads(Path(fx["manifest"]).read_text())
    entry = [e for e in man["files"] if e["key"] == "repro/steps.md"][0]
    assert entry["origin"].endswith(f"runs/{uid}/out/sources/repro/steps.md") and entry["version"] == uid
    assert set(entry) == {"key", "version", "sha256", "size", "origin"} and "repro/steps.md" not in man["dirty"]
    assert fx["status"] == {"from": "deployed", "to": "implemented", "applied": True}
    assert cdemo.status() == "implemented"
    listed = {d["path"] for d in json.loads(call(cap, "doc", "list", "--run", str(root))[1])}
    assert {"repro/steps.md", "repro/deep/env.md"} <= listed
    rc, out, _ = call(cap, "doc", "read", "repro/steps", "--run", str(root))
    assert rc == 0 and out == b"# steps\n1. login\n"


def test_repro_unknown_and_empty(cdemo, cap, monkeypatch):
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "fixer", "--branch", BRANCH, "--repro",
                   "20260101-000000-abcdef") == "repro_unknown:20260101-000000-abcdef"
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "fixer", "--branch", BRANCH, "--repro",
                   "../x") == "repro_unknown:../x"
    rec = rinit(cap, agent="recetteur")
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "fixer", "--branch", BRANCH, "--repro",
                   rec["run_uid"]) == f"repro_unknown:{rec['run_uid']}"     # open run: not a trace
    assert finish(cap, rec["run_uid"])[0] == 0
    fx = rinit(cap, "--repro", rec["run_uid"], agent="fixer")
    assert "repro_empty" in fx["warnings"] and not (Path(fx["root"]) / "in" / "repro").exists()


# --- AC17: caps of rw/out/sources/ ---

def test_ac17_source_file_cap(cdemo, cap):
    res = rinit(cap)
    agent_commit(code_of(res), "c1")
    with open(Path(res["out"]) / "sources" / "big.bin", "wb") as f:
        f.truncate(51 * 1024 * 1024)
    before = porcelain(cdemo.data)
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["source_too_large:big.bin"]
    assert cdemo.rsha() is None and porcelain(cdemo.data) == before and Path(res["root"]).is_dir()


def test_ac17_sources_total_cap(cdemo, cap):
    res = rinit(cap)
    agent_commit(code_of(res), "c1")
    for i in range(5):
        with open(Path(res["out"]) / "sources" / f"part{i}.bin", "wb") as f:
            f.truncate(45 * 1024 * 1024)
    before = porcelain(cdemo.data)
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["sources_total_too_large"]
    assert cdemo.rsha() is None and porcelain(cdemo.data) == before and Path(res["root"]).is_dir()


def test_sources_non_regular_rejected(cdemo, cap):
    res = rinit(cap)
    os.mkfifo(Path(res["out"]) / "sources" / "pipe")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 1 and fin["reasons"] == ["unexpected_file:sources/pipe"]


# --- AC18: external repro folder ---

def test_ac18_repro_dir_md_only_origin(cdemo, cap):
    d = cdemo.tmp / "scratch" / "repro-manual"
    write(d, "steps.md", b"# manual steps\n")
    write(d, "trace.bin", b"\x00")
    os.symlink(d / "steps.md", d / "link.md")
    res = rinit(cap, "--repro-dir", str(d), "--status", "implemented", agent="fixer")
    root = Path(res["root"])
    assert (root / "in" / "repro" / "steps.md").read_bytes() == b"# manual steps\n"
    assert not (root / "in" / "repro" / "trace.bin").exists() and not (root / "in" / "repro" / "link.md").exists()
    man = json.loads(Path(res["manifest"]).read_text())
    entry = [e for e in man["files"] if e["key"] == "repro/steps.md"][0]
    assert entry["origin"] == str(d / "steps.md") and entry["version"] is None
    assert res["status"] == {"from": "implemented", "to": "implemented", "applied": False}


def test_ac18_repro_conflict_and_invalid_dir(cdemo, cap):
    d = cdemo.tmp / "scratch" / "empty"
    d.mkdir(parents=True)
    base = ["run", "init", "DEMO-E-1", "--agent", "fixer", "--branch", BRANCH]
    assert refused(cap, *base, "--repro", "20260101-000000-abcdef", "--repro-dir", str(d)).startswith("repro_conflict")
    assert refused(cap, *base, "--repro-dir", str(d)).startswith("repro_dir_invalid")
    assert refused(cap, *base, "--repro-dir", "relative/dir").startswith("repro_dir_invalid")
    assert refused(cap, *base, "--repro-dir", str(cdemo.tmp / "absent")).startswith("repro_dir_invalid")
    assert agentws(cdemo) == []


# --- AC20: minimal mission scope ---

def _mission(cd: CodeDemo) -> None:
    write(cd.data, "missions/inc-042/brief.md", b"# Incident 42\n")
    write(cd.data, "missions/inc-042/sources/log.md", b"# log\n")
    commit(cd.data, "mission")


def test_ac20_mission_scope_minimal(cdemo, cap, monkeypatch):
    _mission(cdemo)
    res = ok(cap, "run", "init", "--mission", "inc-042", "--agent", "reviewer")
    root = Path(res["root"])
    assert root.parent == cdemo.tmp / "_agentws" / "DEMO" / "inc-042"
    assert (root / "in" / "mission" / "brief.md").read_bytes() == b"# Incident 42\n"
    assert (root / "in" / "mission" / "sources" / "log.md").is_file()
    run = json.loads((root / "run.json").read_text())
    assert run["mission"] == "inc-042" and run["story"] is None
    assert os.listdir(root / "rw" / "code") == [] and not (root / "in" / "repos").exists()
    assert res["repos"] == {} and json.loads((root / "code.json").read_text())["repos"] == {}
    write(Path(res["out"]), "sources/notes.md", b"# notes\n")
    before = porcelain(cdemo.data, "DEMO-E")
    review(cap, monkeypatch, res)
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 0 and fin["git"] == {} and "status" not in fin
    trace = cdemo.data / "runs" / res["run_uid"] / "out"
    assert (trace / "docs" / "review.md").is_file() and (trace / "sources" / "notes.md").is_file()
    assert porcelain(cdemo.data, "DEMO-E") == before


def test_ac20_mission_unknown_and_unsupported_options(cdemo, cap):
    _mission(cdemo)
    assert refused(cap, "run", "init", "--mission", "inc-999", "--agent", "reviewer") == "mission_unknown:inc-999"
    for opt in (["--status", "reviewed"], ["--branch", BRANCH], ["--repro", "20260101-000000-abcdef"],
                ["--repro-dir", "/x"], ["--base", "main"]):
        err = refused(cap, "run", "init", "--mission", "inc-042", "--agent", "reviewer", *opt)
        assert err == f"mission_scope_unsupported:{opt[0]}"
    res = ok(cap, "run", "init", "--mission", "inc-042", "--agent", "reviewer")
    assert refused(cap, "run", "finish", res["run_uid"], "--status", "reviewed") == \
        "mission_scope_unsupported:--status"
    assert agentws(cdemo, "inc-999") == []


# --- safety, contracts ---

def test_status_noop_when_equal(cdemo, cap, monkeypatch):
    res = rinit(cap, "--status", "implemented", agent="fixer")
    assert res["status"] == {"from": "implemented", "to": "implemented", "applied": False}
    review(cap, monkeypatch, res, "implement")
    rc, fin = finish(cap, res["run_uid"], "--status", "implemented")
    assert rc == 0 and fin["status"] == {"from": "implemented", "to": "implemented", "applied": False}


def test_status_invalid_refused_before_writes(cdemo, cap, monkeypatch):
    calls = spy_git(monkeypatch)
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", "--branch", BRANCH, "--status", "done") == \
        "status_invalid:implemented->done"
    assert refused(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer", "--branch", BRANCH, "--status",
                   "bogus") == "status_invalid:implemented->bogus"
    assert agentws(cdemo) == [] and not [c for c in calls if "clone" in c[1]]
    res = rinit(cap)
    agent_commit(code_of(res), "c1")
    before = porcelain(cdemo.data)
    rc, fin = finish(cap, res["run_uid"], "--status", "recette_ok")
    assert rc == 1 and fin["reasons"] == ["status_invalid:implemented->recette_ok"]
    assert cdemo.rsha() is None and porcelain(cdemo.data) == before


def test_status_changed_concurrently_rejected(cdemo, cap, monkeypatch):
    res = rinit(cap)
    review(cap, monkeypatch, res)
    real = DataRepoBackend.put

    def put(self, key, content, meta):
        if key.endswith("/manifest.json"):          # a third party moves the story meanwhile
            ws = Workspace(cdemo.data)
            t = ws.load("DEMO-E-1")
            t.status = "deployed"
            ws.save(t)
        return real(self, key, content, meta)

    monkeypatch.setattr(DataRepoBackend, "put", put)
    rc, fin = finish(cap, res["run_uid"], "--status", "reviewed")
    assert rc == 1 and fin["reasons"] == ["status_invalid:deployed->reviewed"]
    assert not (cdemo.data / "runs" / res["run_uid"] / "run.json").exists() and Path(res["root"]).is_dir()


def test_push_failed_replay_safe(cdemo, cap, monkeypatch):
    res = rinit(cap)
    c1 = agent_commit(code_of(res), "c1")
    review(cap, monkeypatch, res)
    refs = cdemo.remote() / "refs" / "heads"
    refs.chmod(0o555)
    try:
        rc, fin = finish(cap, res["run_uid"], "--status", "reviewed")
    finally:
        refs.chmod(0o755)
    assert rc == 1 and fin["reasons"] == ["push_failed:app-repo"]
    assert cdemo.rsha() is None and cdemo.status() == "implemented"
    assert not (cdemo.data / "runs" / res["run_uid"]).exists()
    calls = spy_git(monkeypatch)
    rc, fin = finish(cap, res["run_uid"], "--status", "reviewed")
    assert rc == 0 and cdemo.rsha() == c1 and cdemo.status() == "reviewed"
    assert len([a for h, a, _ in calls if "push" in a]) == 1


@pytest.mark.parametrize("crash_on", ["docs", "manifest", "run"])
def test_finish_replay_after_crash_code(cdemo, cap, monkeypatch, crash_on):
    res = rinit(cap)
    c1 = agent_commit(code_of(res), "c1")
    review(cap, monkeypatch, res)
    real = DataRepoBackend.put
    target = {"docs": "/out/docs/review.md", "manifest": "/manifest.json", "run": "/run.json"}[crash_on]
    state = {"crashed": False}

    def put(self, key, content, meta):
        if key.endswith(target) and not state["crashed"]:
            state["crashed"] = True
            raise OSError("simulated crash")
        return real(self, key, content, meta)

    monkeypatch.setattr(DataRepoBackend, "put", put)
    rc, _, err = call(cap, "run", "finish", res["run_uid"], "--status", "reviewed")
    assert rc == 1 and "simulated crash" in err and cdemo.rsha() == c1
    assert cdemo.status() == ("reviewed" if crash_on == "run" else "implemented")
    calls = spy_git(monkeypatch)
    rc, fin = finish(cap, res["run_uid"], "--status", "reviewed")
    assert rc == 0 and fin["state"] == "published" and fin["git"]["app-repo"]["pushed"] is True
    assert not [a for h, a, _ in calls if "push" in a]
    doc = (cdemo.data / "DEMO-E" / "stories" / "DEMO-E-1" / "review.md").read_text()
    assert len([x for x in doc.splitlines() if res["run_uid"] in x and x.startswith("<!-- round")]) == 1
    assert cdemo.status() == "reviewed"


def test_publication_order(cdemo, cap, monkeypatch):
    res = rinit(cap)
    agent_commit(code_of(res), "c1")
    review(cap, monkeypatch, res)
    write(Path(res["out"]), "sources/a.md", b"a\n")
    order: list[str] = []
    real_put, real_tr, real_push = DataRepoBackend.put, DataRepoBackend.transition, gitcode.push

    def put(self, key, content, meta):
        order.append("put:" + key.split("/", 2)[2])
        return real_put(self, key, content, meta)

    def tr(self, story, target):
        order.append("transition")
        return real_tr(self, story, target)

    def push(*a, **kw):
        order.append("push")
        return real_push(*a, **kw)

    monkeypatch.setattr(DataRepoBackend, "put", put)
    monkeypatch.setattr(DataRepoBackend, "transition", tr)
    monkeypatch.setattr(gitcode, "push", push)
    assert finish(cap, res["run_uid"], "--status", "reviewed")[0] == 0
    assert order == ["push", "put:out/docs/review.md", "put:out/sources/a.md", "put:out/git/app-repo.bundle",
                     "put:manifest.json", "transition", "put:run.json"]


def test_clone_command_on_open_run(tmp_path, monkeypatch, cap):
    cd = make_code_demo(tmp_path, monkeypatch, activate=False)
    res = ok(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer")
    assert refused(cap, "clone", "--run", res["root"], "--branch", BRANCH) == "run_workspace_disabled:clone"
    cd.config(runWorkspace=True)
    out = ok(cap, "clone", "--run", res["root"], "--branch", BRANCH)
    assert set(out["repos"]) == {"app-repo", "web-repo"} and out["repos"]["app-repo"]["created"] is True
    root = Path(res["root"])
    assert git(root / "rw" / "code" / "app-repo", "branch", "--show-current") == BRANCH
    deny = json.loads((root / "in" / "settings.json").read_text())["permissions"]["deny"]
    assert "Bash(git push:*)" in deny
    assert refused(cap, "clone", "--run", res["root"], "--branch", BRANCH) == f"clone_exists:{res['run_uid']}"
    c1 = agent_commit(root / "rw" / "code" / "app-repo", "c1")
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 0 and fin["git"]["app-repo"]["sha"] == c1 and cd.rsha() == c1


def test_off_run_zero_gitcode_calls(tmp_path, monkeypatch, cap):
    make_code_demo(tmp_path, monkeypatch, activate=False)
    calls = spy_git(monkeypatch)
    res = ok(cap, "run", "init", "DEMO-E-1", "--agent", "reviewer")
    assert set(res) == {"run_uid", "root", "in", "rw", "out", "code", "scratch", "settings", "manifest",
                        "brain", "warnings"}
    rc, fin = finish(cap, res["run_uid"])
    assert rc == 0 and set(fin) == {"run_uid", "state", "published", "warnings"}
    assert calls == []
    mb = DataRepoBackend.from_project("DEMO")
    assert mb.run_workspace is None
