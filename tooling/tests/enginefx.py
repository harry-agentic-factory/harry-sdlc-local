"""Shared fixtures of the packaging and installation tests (stdlib only).

- ``copy_engine_tree``: copy of the engine repository without ``.git`` (the ``.git`` of a worktree is only
  a pointer, not mounted in the test container), caches and build output.
- ``make_engine_remote``: a local bare repository with the tags of the acceptance criteria, built from that
  copy: ``v<V>`` (VERSION = V, with an extra agent ``zz-retire.md``), ``v<V+1>`` (VERSION = V+1, agent
  removed), ``v9.9.9`` (VERSION = V: inconsistent) and a branch named like a tag ``v<V+2>`` (no tag).
- ``env_e``: the throwaway environment (E) of the spec: HOME, ZDOTDIR, CLAUDE_HOME, HARRY_SDLC_HOME,
  HARRY_SDLC_REPO and a reduced PATH (``$HOME/.local/bin``, a shim folder with python3 and git, /usr/bin, /bin).
- ``build_dist``: ``uv build`` of ``tooling/`` into a given folder.

Versions are derived from the VERSION file of the repository: nothing here depends on a literal version.
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[2]
TOOLING = ENGINE_ROOT / "tooling"
INSTALL_SH = ENGINE_ROOT / "install.sh"
SCRIPTS = ENGINE_ROOT / "scripts"
_IGNORED = {".git", "__pycache__", "dist", ".venv", ".pytest_cache", "_toDelete", "_version.py", ".uv-cache"}


def repo_version() -> str:
    return (ENGINE_ROOT / "VERSION").read_text().splitlines()[0].strip()


def bump_patch(version: str, by: int = 1) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    return f"{major}.{minor}.{patch + by}"


def git_env(home: Path | None = None) -> dict[str, str]:
    """Environment for fixture git calls: no user or system configuration, fixed identity."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    if home is not None:
        env["HOME"] = str(home)
    return env


def git(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, env=env or git_env(), capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def copy_engine_tree(dst: Path) -> Path:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in _IGNORED or n.endswith(".pyc")}
    shutil.copytree(ENGINE_ROOT, dst, ignore=ignore, symlinks=True)
    return dst


@dataclasses.dataclass(frozen=True)
class Remote:
    url: str            # file://<bare>
    bare: Path
    work: Path          # non-bare working repository the bare was cloned from (at C2)
    v: str              # VERSION of the repository (tag v<v>)
    v1: str             # patch + 1 (tag v<v1>)
    branch_like_tag: str  # branch named v<patch + 2>, no such tag

    @property
    def tag(self) -> str:
        return "v" + self.v

    @property
    def tag1(self) -> str:
        return "v" + self.v1

    def commit_of(self, ref: str) -> str:
        return git("rev-parse", f"{ref}^{{commit}}", cwd=self.bare)


def make_engine_remote(base: Path) -> Remote:
    v = repo_version()
    v1 = bump_patch(v, 1)
    v2 = bump_patch(v, 2)
    work = copy_engine_tree(base / "engine-work")
    git("init", "-q", "-b", "main", cwd=work)
    (work / "VERSION").write_text(v + "\n")
    (work / "claude" / "agents" / "zz-retire.md").write_text("# retired agent (fixture)\n")
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "C1", cwd=work)
    git("tag", "-a", "v" + v, "-m", "v" + v, cwd=work)
    git("tag", "-a", "v9.9.9", "-m", "inconsistent", cwd=work)
    (work / "VERSION").write_text(v1 + "\n")
    (work / "claude" / "agents" / "zz-retire.md").unlink()
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "C2", cwd=work)
    git("tag", "-a", "v" + v1, "-m", "v" + v1, cwd=work)
    git("checkout", "-q", "-b", "v" + v2, cwd=work)
    (work / "VERSION").write_text(v2 + "\n")
    git("commit", "-q", "-am", "branch named like a tag", cwd=work)
    git("checkout", "-q", "main", cwd=work)
    bare = base / "engine.git"
    git("clone", "-q", "--bare", str(work), str(bare))
    return Remote(url=bare.as_uri(), bare=bare, work=work, v=v, v1=v1, branch_like_tag="v" + v2)


def _shim(folder: Path, name: str, target: str) -> None:
    path = folder / name
    path.write_text(f'#!/bin/sh\nexec "{target}" "$@"\n')
    path.chmod(0o755)


def env_e(base: Path, remote: Remote | None = None) -> dict[str, str]:
    """Environment (E): everything under <base>/home, reduced PATH, fixture remote."""
    home = base / "home"
    home.mkdir(parents=True, exist_ok=True)
    tools = base / "tools"
    tools.mkdir(exist_ok=True)
    _shim(tools, "python3", sys.executable)
    _shim(tools, "git", shutil.which("git") or "/usr/bin/git")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "HARRY_SDLC_", "CLAUDE_", "SDLC_")) and k not in ("PYTHONPATH", "ZDOTDIR")}
    env.update(
        HOME=str(home), ZDOTDIR=str(home), CLAUDE_HOME=str(home / ".claude"),
        HARRY_SDLC_HOME=str(home / ".local" / "share" / "harry-sdlc"),
        PATH=f"{home / '.local' / 'bin'}:{tools}:/usr/bin:/bin",
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
        PYTHONDONTWRITEBYTECODE="1",
    )
    if remote is not None:
        env["HARRY_SDLC_REPO"] = remote.url
    return env


def uv_path() -> str | None:
    return shutil.which("uv")


def build_dist(out: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    """``uv build --out-dir <out> [flags]`` in tooling/ (the caller skips when uv is absent)."""
    uv = uv_path()
    assert uv, "uv is required"
    return subprocess.run([uv, "build", "--quiet", "--out-dir", str(out), *flags], cwd=TOOLING,
                          capture_output=True, text=True)
