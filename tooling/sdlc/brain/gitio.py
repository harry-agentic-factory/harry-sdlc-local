"""The only place where the brain library talks to git.

Every call goes through `run_git`, which enforces a whitelist of plumbing sub-commands:
reads (`rev-parse`, `ls-tree`, `cat-file`, `log`, `config --get`, `check-ref-format`,
`symbolic-ref`) and, for `normalize` only, object/ref writes (`hash-object`, `read-tree`,
`update-index`, `write-tree`, `commit-tree`, `update-ref`). Nothing here touches the network,
the working copy, the repository index or `HEAD`: `read-tree`/`update-index`/`write-tree` always
run against a temporary index file (`GIT_INDEX_FILE`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

READ_SUBCOMMANDS = frozenset({
    "rev-parse", "ls-tree", "cat-file", "log", "config", "check-ref-format", "symbolic-ref",
})
WRITE_SUBCOMMANDS = frozenset({
    "hash-object", "read-tree", "update-index", "write-tree", "commit-tree", "update-ref",
})
ALLOWED_SUBCOMMANDS = READ_SUBCOMMANDS | WRITE_SUBCOMMANDS

# Variables inherited from a calling git process (hooks, aliases) that would redirect our calls.
_SCRUBBED_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX")


class BrainError(Exception):
    """Error of the brain library. `code` is stable (machine readable); the CLI exits with 2."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class BrainNotGit(BrainError):
    """The brain folder is not inside a git work tree."""

    def __init__(self, message: str = ""):
        super().__init__("brain_not_git", message or "brain is not a git repository")


class BrainRefUnresolved(BrainError):
    """No ref, branch, tag or sha matches the requested brain ref."""

    def __init__(self, message: str = ""):
        super().__init__("brain_ref_unresolved", message or "brain ref cannot be resolved")


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_ENV}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LITERAL_PATHSPECS"] = "1"
    if extra:
        env.update(extra)
    return env


def run_git(cwd: str | Path, args: list[str], *, data: bytes | None = None,
            extra_env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run one whitelisted git sub-command in `cwd`; raw bytes in and out."""
    sub = args[0] if args else ""
    if sub not in ALLOWED_SUBCOMMANDS:
        raise BrainError("git_failed", f"git sub-command not allowed: {sub!r}")
    if sub == "config" and (len(args) < 2 or args[1] != "--get"):
        raise BrainError("git_failed", "only 'git config --get' is allowed")
    if sub == "symbolic-ref" and (len(args) != 3 or args[1] != "--quiet"):
        raise BrainError("git_failed", "only 'git symbolic-ref --quiet <ref>' is allowed")
    cmd = ["git", "-C", str(cwd), "--no-optional-locks", *args]
    try:
        proc = subprocess.run(cmd, input=data, capture_output=True, env=_env(extra_env), check=False)
    except OSError as e:
        raise BrainError("git_failed", f"cannot run git: {e}") from e
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise BrainError("git_failed", f"git {sub} failed: {err}")
    return proc


def _out(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout.decode("utf-8", errors="replace").strip()


# --- opening a brain ---

@dataclass(frozen=True)
class Brain:
    """A brain = a folder inside a git work tree (the repository root or a sub-folder)."""
    root: str                     # absolute path of the brain folder
    top: str                      # git top-level directory
    prefix: str                   # brain folder relative to `top`, "" or ending with "/"
    repo_names: frozenset[str]    # names used by `../<name>/` self-references


def _url_name(url: str) -> str | None:
    url = url.strip().rstrip("/")
    if not url:
        return None
    name = url.replace(":", "/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or None


def open_brain(path: str | Path) -> Brain:
    p = Path(path).expanduser()
    if not p.is_dir():
        raise BrainError("brain_not_found", f"brain folder not found: {p}")
    proc = run_git(p, ["rev-parse", "--show-toplevel"], check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise BrainNotGit(f"not inside a git work tree: {p}")
    top = _out(proc)
    prefix = _out(run_git(p, ["rev-parse", "--show-prefix"]))
    names = {p.absolute().name, p.resolve().name, Path(top).name}
    url = config_get(top, "remote.origin.url")
    if url and _url_name(url):
        names.add(_url_name(url))
    names.discard("")
    return Brain(root=str(p.absolute()), top=top, prefix=prefix, repo_names=frozenset(names))


# --- reads ---

def config_get(top: str, key: str) -> str | None:
    proc = run_git(top, ["config", "--get", key], check=False)
    return _out(proc) if proc.returncode == 0 else None


def verify_commit(top: str, expr: str) -> str | None:
    """Sha of `expr` (already suffixed with `^{commit}` by the caller) or None."""
    proc = run_git(top, ["rev-parse", "--verify", "--quiet", expr], check=False)
    sha = _out(proc)
    return sha if proc.returncode == 0 and sha else None


def symbolic_ref(top: str, name: str) -> str | None:
    proc = run_git(top, ["symbolic-ref", "--quiet", name], check=False)
    return _out(proc) if proc.returncode == 0 else None


def check_branch_name(top: str, name: str) -> bool:
    proc = run_git(top, ["check-ref-format", "--branch", name], check=False)
    return proc.returncode == 0


def ls_tree(top: str, commit: str, prefix: str) -> list[tuple[str, str, str]]:
    """Regular files (modes 100644/100755) of `commit` under `prefix`: [(mode, blob, full_path)]."""
    args = ["ls-tree", "-r", "-z", "--full-tree", commit]
    if prefix:
        args.append(prefix)
    out = run_git(top, args).stdout
    entries: list[tuple[str, str, str]] = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, name = rec.partition(b"\t")
        mode, kind, sha = meta.decode().split(" ")
        if kind != "blob" or mode not in ("100644", "100755"):
            continue
        entries.append((mode, sha, name.decode("utf-8", errors="surrogateescape")))
    return entries


def cat_file(top: str, names: Iterable[str]) -> list[bytes | None]:
    """Raw content of each object name (sha or `<commit>:<path>`) through ONE `cat-file --batch`.

    No filter and no textconv: the bytes are exactly those stored in git. Missing or non-blob
    objects come back as None.
    """
    names = list(names)
    if not names:
        return []
    for n in names:
        if "\n" in n:
            raise BrainError("git_failed", f"object name contains a newline: {n!r}")
    stdin = "".join(n + "\n" for n in names).encode("utf-8", errors="surrogateescape")
    out = run_git(top, ["cat-file", "--batch"], data=stdin).stdout
    res: list[bytes | None] = []
    pos = 0
    for _ in names:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split(b" ")
        if len(header) != 3:              # "<name> missing" / "<name> ambiguous"
            res.append(None)
            pos = nl + 1
            continue
        _sha, kind, size = header
        start = nl + 1
        end = start + int(size)
        res.append(out[start:end] if kind == b"blob" else None)
        pos = end + 1                     # content is followed by a newline
    return res


def last_change(top: str, commit: str, full_path: str) -> tuple[str, str] | None:
    """(sha, committer ISO date) of the last commit <= `commit` that touched `full_path`."""
    out = _out(run_git(top, ["log", "-1", "--format=%H%x1f%cI", commit, "--", full_path]))
    if not out:
        return None
    sha, _, date = out.partition("\x1f")
    return sha, date


def commit_date(top: str, commit: str) -> str:
    return _out(run_git(top, ["log", "-1", "--format=%cI", commit]))


def log_follow(top: str, commit: str, full_path: str) -> bytes:
    return run_git(top, ["log", "--follow", "--format=%H%x1f%cI%x1f%an%x1f%s", "--name-only", "-z",
                         commit, "--", full_path]).stdout


# --- writes (normalize only) ---

def hash_object(top: str, data: bytes) -> str:
    """Store `data` as a blob exactly as given (no clean filter, no eol conversion)."""
    return _out(run_git(top, ["hash-object", "-w", "--no-filters", "--stdin"], data=data))


def commit_tree(top: str, tree: str, parent: str, message: str) -> str:
    return _out(run_git(top, ["commit-tree", tree, "-p", parent, "-m", message]))


def commit_entries(top: str, base: str, entries: list[tuple[str, str, str]], message: str) -> str:
    """Commit `base` + replaced entries [(mode, blob, full_path)] without touching the real index.

    The tree is built in a temporary index file, removed in all cases.
    """
    tmp = tempfile.mkdtemp(prefix="sdlc-brain-index-")
    try:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index")}
        run_git(top, ["read-tree", base], extra_env=env)
        info = b"".join(f"{mode} blob {sha}\t".encode() + path.encode("utf-8", errors="surrogateescape")
                        + b"\0" for mode, sha, path in entries)
        run_git(top, ["update-index", "-z", "--index-info"], data=info, extra_env=env)
        tree = _out(run_git(top, ["write-tree"], extra_env=env))
        return commit_tree(top, tree, base, message)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def create_branch_ref(top: str, branch: str, sha: str) -> None:
    """Create `refs/heads/<branch>` atomically; fails if it already exists (old value = "")."""
    run_git(top, ["update-ref", f"refs/heads/{branch}", sha, ""])
