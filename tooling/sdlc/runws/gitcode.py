"""Git of a code run: clone, check, bundle and push. With `datarepo.py`, the only module that runs a process.

Every git call goes through one of two helpers:

- `_git_trusted(*args, cwd=None)`: the declared local repositories (read) and the fresh clones made
  by the engine (the clones of `run init`, before the agent runs; the bare clones of the push);
- `_git_untrusted(repo, *args)`: any repository the agent could have touched (`rw/code/<repo>`,
  `in/repos/<repo>`). Only `rev-parse`, `for-each-ref`, `bundle` and `status` are allowed, always with
  optional locks, the file system monitor, hooks and the untracked cache disabled.

No credential is ever read, written or passed: the environment is inherited, minus the git variables
that locate a repository (`LOCATION_ENV`, which would redirect every call to another repository), and
the host git configuration authenticates clones and pushes. Clones of the agent are left without any remote. A push
is only made from a fresh bare clone, with a plain `<sha>:refs/heads/<branch>` refspec, never forced.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from .model import RunError, sha256

UNTRUSTED_SUBCOMMANDS = frozenset({"rev-parse", "for-each-ref", "bundle", "status"})
FORBIDDEN_CONFIG_PREFIXES = ("remote.", "credential.", "http.", "url.")
# hooksPath of untrusted calls: a path under which no hook can exist (nothing is written for it).
NO_HOOKS = os.devnull
# the only variables removed from the inherited environment (nothing is ever added)
LOCATION_ENV = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                          "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR"})


# working directory of the trusted calls that name no repository (`clone`, `ls-remote`): git discovers
# a repository from its working directory even for these, and dies on an unreadable one (e.g. a
# worktree whose `.git` file points to a path absent from the container that runs the engine).
NEUTRAL_CWD = os.path.abspath(os.sep)
# userinfo of a URL (`scheme://user:secret@host`), redacted from any diagnostic
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s]+@")
DIAGNOSTIC_MAX = 2000


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in LOCATION_ENV}


def _git_trusted(*args: str, cwd=None) -> subprocess.CompletedProcess:
    argv = ["git", *(["-C", str(cwd)] if cwd is not None else []), *args]
    return subprocess.run(argv, capture_output=True, env=_env(), check=False,
                          cwd=NEUTRAL_CWD if cwd is None else None)


def _git_untrusted(repo, *args: str, hooks: str = NO_HOOKS) -> subprocess.CompletedProcess:
    if not args or args[0] not in UNTRUSTED_SUBCOMMANDS:
        raise RunError("git_refused", f"git sub-command not allowed on an agent repository: {args[:1]}")
    argv = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", f"core.hooksPath={hooks}",
            "-c", "core.untrackedCache=false", "-C", str(repo), *args]
    return subprocess.run(argv, capture_output=True, env=_env(), check=False)


def diagnostic(p: subprocess.CompletedProcess) -> str:
    """Redacted, bounded stderr of a failed git call, for the operator."""
    err = (p.stderr or b"").decode("utf-8", "replace").strip()
    args, sub = list(p.args[1:]) if isinstance(p.args, list) else [], "?"
    while args:
        a = args.pop(0)
        if a in ("-C", "-c"):
            args = args[1:]
        elif not a.startswith("-"):
            sub = a
            break
    text = _URL_USERINFO.sub(r"\1***@", f"git {sub} (rc={p.returncode}): {err}")
    return text[:DIAGNOSTIC_MAX]


def _check(p: subprocess.CompletedProcess, name: str) -> subprocess.CompletedProcess:
    if p.returncode != 0:
        raise RunError("clone_failed", name, diagnostic=diagnostic(p))
    return p


def _out(p: subprocess.CompletedProcess) -> str:
    return p.stdout.decode("utf-8", "replace").strip()


# --- declared repositories and remotes (trusted) ---

def origin_url(local: str | os.PathLike) -> str | None:
    """`remote.origin.url` of a declared local repository, None when it has none."""
    p = _git_trusted("config", "--local", "--get", "remote.origin.url", cwd=local)
    url = _out(p)
    return url if p.returncode == 0 and url else None


def ls_remote(name: str, url: str) -> dict[str, str]:
    """`{"HEAD": sha, "refs/heads/<b>": sha, ...}` of a remote (RunError `clone_failed` when it cannot
    be listed or has no ref)."""
    p = _check(_git_trusted("ls-remote", "--", url), name)
    refs: dict[str, str] = {}
    for line in _out(p).splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "HEAD" or ref.startswith("refs/heads/"):
            refs[ref] = sha
    if not refs:
        raise RunError("clone_failed", name, diagnostic=f"remote of {name} has no branch")
    return refs


def _clone_url(url: str) -> str:
    """A local path becomes a `file://` URL so that `--depth` is honoured."""
    return "file://" + url if os.path.isabs(url) else url


def _drop_logs(dest: Path) -> None:
    """Reflogs of a fresh clone name its source: the agent never sees them."""
    shutil.rmtree(dest / ".git" / "logs", ignore_errors=True)
    try:
        os.unlink(dest / ".git" / "FETCH_HEAD")
    except OSError:
        pass


def _clean_config(dest: Path) -> bool:
    """True when the local configuration of a fresh clone has no remote/credential/http/url key."""
    p = _git_trusted("config", "--local", "--list", cwd=dest)
    if p.returncode != 0:
        return False
    keys = [line.split("=", 1)[0].lower() for line in _out(p).splitlines()]
    return not any(k.startswith(FORBIDDEN_CONFIG_PREFIXES) for k in keys) and scan_repo(dest) is None


def _local_heads(dest: Path) -> list[str]:
    p = _git_trusted("for-each-ref", "--format=%(refname)", "refs/heads/", cwd=dest)
    return [x for x in _out(p).splitlines() if x] if p.returncode == 0 else []


def clone_target(name: str, url: str, dest: Path, *, branch: str, base: str, created: bool) -> str:
    """Clone a target on `branch` (from the remote branch, else from `base`), `base` as a local branch,
    no remote left. Returns the commit checked out (RunError `clone_failed` otherwise)."""
    start = f"refs/remotes/origin/{base if created else branch}"
    steps = [
        (("clone", "-q", "--no-tags", "--no-checkout", "--origin", "origin", "--", url, str(dest)), None),
        (("checkout", "-q", "--no-track", "-B", branch, start), dest),
        (("update-ref", f"refs/heads/{base}", f"refs/remotes/origin/{base}"), dest),
    ]
    for args, cwd in steps:
        _check(_git_trusted(*args, cwd=cwd), name)
    for ref in _local_heads(dest):
        if ref not in (f"refs/heads/{branch}", f"refs/heads/{base}"):
            _check(_git_trusted("update-ref", "-d", ref, cwd=dest), name)
    _check(_git_trusted("remote", "remove", "origin", cwd=dest), name)
    _drop_logs(dest)
    head = _check(_git_trusted("rev-parse", "--verify", "-q", "HEAD", cwd=dest), name)
    if not _clean_config(dest):
        raise RunError("clone_failed", name, diagnostic="local configuration of the clone not clean")
    return _out(head)


def clone_neighbour(name: str, url: str, dest: Path, *, ref: str | None) -> tuple[str, str]:
    """Shallow clone of a neighbour at `ref` (remote HEAD when None), no remote left.
    Returns (commit, sha256 of .git/config)."""
    args = ["clone", "-q", "--depth", "1", "--single-branch", "--no-tags", "--origin", "origin"]
    if ref is not None:
        args += ["--branch", ref]
    _check(_git_trusted(*args, "--", _clone_url(url), str(dest)), name)
    _check(_git_trusted("remote", "remove", "origin", cwd=dest), name)
    _drop_logs(dest)
    head = _check(_git_trusted("rev-parse", "--verify", "-q", "HEAD", cwd=dest), name)
    config = _read_regular(dest / ".git" / "config")
    if config is None or not _clean_config(dest):
        raise RunError("clone_failed", name, diagnostic="local configuration of the clone not clean")
    return _out(head), sha256(config)


# --- checks of a repository the agent could have touched (no git call before the structure) ---

def _read_regular(path: Path) -> bytes | None:
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        return f.read()


def scan_repo(repo: Path) -> str | None:
    """None when `repo` is a real folder with a real `.git` folder that borrows no object store."""
    try:
        if not stat.S_ISDIR(os.lstat(repo).st_mode) or not stat.S_ISDIR(os.lstat(repo / ".git").st_mode):
            return "not_a_repository"
    except OSError:
        return "not_a_repository"
    for rel in ("commondir", "objects/info/alternates", "objects/info/http-alternates"):
        if os.path.lexists(repo / ".git" / rel):
            return "borrowed_objects"
    return None


def config_sha256(repo: Path) -> str | None:
    data = _read_regular(repo / ".git" / "config")
    return sha256(data) if data is not None else None


def head_commit(repo: Path) -> str | None:
    p = _git_untrusted(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    return _out(p) if p.returncode == 0 else None


def neighbour_clean(repo: Path) -> bool:
    """`status --porcelain --ignored` is empty (call only once `.git/config` is known intact)."""
    p = _git_untrusted(repo, "status", "--porcelain", "--ignored")
    return p.returncode == 0 and not p.stdout.strip()


def refs(repo: Path) -> dict[str, str] | None:
    """`{refname: sha}` of `refs/heads/*` and `refs/tags/*`."""
    p = _git_untrusted(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads/", "refs/tags/")
    if p.returncode != 0:
        return None
    out: dict[str, str] = {}
    for line in _out(p).splitlines():
        ref, _, sha = line.rpartition(" ")
        if ref:
            out[ref] = sha
    return out


def write_bundle(repo: Path, tmp: Path, *, branch: str, head: str) -> bool:
    """Bundle of the only story branch, with `head` (recorded by the engine) as prerequisite."""
    try:
        os.unlink(tmp)
    except OSError:
        pass
    p = _git_untrusted(repo, "bundle", "create", "-q", str(tmp), f"refs/heads/{branch}", f"^{head}")
    return p.returncode == 0 and os.path.isfile(tmp)


# --- push, from a fresh bare clone only ---

def prepare_push(name: str, url: str, clone: Path, bundle: Path, *, branch: str, sha: str,
                 hooks: Path) -> tuple[str, str | None]:
    """Fresh bare clone of the remote, bundle fetched into it, fast-forward checked.

    Returns (action, reason): action "push" | "none" (remote already at `sha`) | "refused"."""
    h = f"core.hooksPath={hooks}"
    if _git_trusted("-c", h, "clone", "-q", "--bare", "--no-tags", "--", url, str(clone)).returncode != 0:
        return "refused", f"push_failed:{name}"
    if _git_trusted("-c", h, "bundle", "verify", "-q", str(bundle), cwd=clone).returncode != 0:
        return "refused", f"non_fast_forward:{name}"
    fetch = _git_trusted("-c", h, "fetch", "-q", "--no-tags", "--no-write-fetch-head", str(bundle),
                         f"refs/heads/{branch}:refs/run/{branch}", cwd=clone)
    if fetch.returncode != 0:
        return "refused", f"non_fast_forward:{name}"
    got = _git_trusted("rev-parse", "--verify", "-q", f"refs/run/{branch}", cwd=clone)
    if got.returncode != 0 or _out(got) != sha:
        return "refused", f"code_invalid:{name}"
    remote = _git_trusted("rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}", cwd=clone)
    if remote.returncode != 0:
        return "push", None
    if _out(remote) == sha:
        return "none", None
    if _git_trusted("merge-base", "--is-ancestor", _out(remote), sha, cwd=clone).returncode == 0:
        return "push", None
    return "refused", f"non_fast_forward:{name}"


def push(clone: Path, url: str, *, sha: str, branch: str) -> bool:
    # `--no-verify` skips the client hooks; no `-c core.hooksPath`: it would reach the receive-pack of a
    # local remote (GIT_CONFIG_PARAMETERS) and disable its server hooks
    p = _git_trusted("push", "--no-verify", "--porcelain", "--", url, f"{sha}:refs/heads/{branch}", cwd=clone)
    return p.returncode == 0
