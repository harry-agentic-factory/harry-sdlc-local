"""Engine version and mode: `engine_version`, `engine_mode`, `version_line`, `sdlc --version`."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import enginefx as fx
from sdlc import migrations, version

RELEASE_RE = re.compile(r"^\d+\.\d+\.\d+ \(release\)$")
DEV_RE = re.compile(r"^\d+\.\d+\.\d+-dev\+([0-9a-f]{7,}|unknown)(\.dirty)? \(dev: /.+\)$")


@pytest.fixture(autouse=True)
def not_packaged(monkeypatch):
    monkeypatch.setattr(version, "packaged_version", lambda: None)


def make_repo(root: Path, ver: str = "1.4.2") -> str:
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(ver + "\n")
    fx.git("init", "-q", "-b", "main", cwd=root)
    fx.git("add", "-A", cwd=root)
    fx.git("commit", "-q", "-m", "init", cwd=root)
    return fx.git("rev-parse", "--short=7", "HEAD", cwd=root)


def test_release_mode_under_home(tmp_path):
    home = tmp_path / "hsh"
    root = home / "v1.4.2"
    root.mkdir(parents=True)
    (root / "VERSION").write_text("1.4.2\n")
    assert version.engine_mode(root, home) == ("release", None)
    assert version.version_line(root, home) == "1.4.2 (release)"
    # through a symlink (the `current` link): the physical root decides
    (home / "current").symlink_to("v1.4.2")
    assert version.version_line(home / "current", home) == "1.4.2 (release)"


@pytest.mark.parametrize("rel", ["v9.9.9", "nested/v1.4.2", "1.4.2"])
def test_other_locations_are_dev(tmp_path, rel):
    home = tmp_path / "hsh"
    root = home / rel
    root.mkdir(parents=True)
    (root / "VERSION").write_text("1.4.2\n")
    mode, where = version.engine_mode(root, home)
    assert mode == "dev" and where == os.path.realpath(root)


def test_release_home_from_environment(tmp_path, monkeypatch):
    root = tmp_path / "hsh" / "v1.4.2"
    root.mkdir(parents=True)
    (root / "VERSION").write_text("1.4.2\n")
    monkeypatch.setenv("HARRY_SDLC_HOME", str(tmp_path / "hsh"))
    assert version.engine_mode(root) == ("release", None)
    monkeypatch.setenv("HARRY_SDLC_HOME", str(tmp_path / "other"))
    assert version.engine_mode(root)[0] == "dev"


def test_dev_mode_clean_sha(tmp_path):
    root = tmp_path / "copy"
    short = make_repo(root)
    real = os.path.realpath(root)
    line = version.version_line(root, tmp_path / "hsh")
    assert line == f"1.4.2-dev+{short} (dev: {real})"
    assert DEV_RE.match(line)


def test_dev_mode_dirty(tmp_path):
    root = tmp_path / "copy"
    short = make_repo(root)
    (root / "new.txt").write_text("x\n")
    assert version.version_line(root, tmp_path / "hsh") == f"1.4.2-dev+{short}.dirty (dev: {os.path.realpath(root)})"
    (root / "new.txt").unlink()
    (root / "VERSION").write_text("1.4.2\n\n")
    assert ".dirty (dev:" in version.version_line(root, tmp_path / "hsh")


def test_dev_mode_no_git_unknown(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "VERSION").write_text("1.4.2\n")
    assert version.version_line(plain, tmp_path / "hsh") == f"1.4.2-dev+unknown (dev: {os.path.realpath(plain)})"
    # a folder that is only inside another repository is not described by that repository
    outer = tmp_path / "outer"
    make_repo(outer)
    inner = outer / "inner"
    inner.mkdir()
    (inner / "VERSION").write_text("1.4.2\n")
    assert "-dev+unknown (dev:" in version.version_line(inner, tmp_path / "hsh")
    # git missing from the PATH
    repo = tmp_path / "repo"
    make_repo(repo)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert "-dev+unknown (dev:" in version.version_line(repo, tmp_path / "hsh")


def test_dev_git_calls_are_read_only(tmp_path, monkeypatch):
    root = tmp_path / "copy"
    make_repo(root)
    calls = []
    real_run = subprocess.run

    def spy(argv, *args, **kwargs):
        calls.append((list(argv), kwargs))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(version.subprocess, "run", spy)
    version.version_line(root, tmp_path / "hsh")
    assert [c[0][3:5] for c in calls] == [[str(os.path.realpath(root)), "rev-parse"], [str(os.path.realpath(root)), "status"]]
    for argv, kwargs in calls:
        assert argv[:3] == ["git", "--no-optional-locks", "-C"]
        assert kwargs["timeout"] == version.GIT_TIMEOUT_S
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_packaged_mode_is_release(monkeypatch, tmp_path):
    monkeypatch.setattr(version, "packaged_version", lambda: "3.2.1")
    assert version.engine_version() == "3.2.1"
    assert version.engine_mode(tmp_path, tmp_path / "hsh") == ("release", None)
    assert version.version_line(tmp_path, tmp_path / "hsh") == "3.2.1 (release)"
    assert migrations.engine_version() == "3.2.1"


def test_engine_version_sources(monkeypatch, tmp_path):
    assert version.engine_version() == fx.repo_version()
    assert migrations.engine_version() == fx.repo_version()
    monkeypatch.setattr(version, "engine_root", lambda: tmp_path)
    monkeypatch.setattr(version, "_metadata_version", lambda: "2.0.0")
    assert version.engine_version() == "2.0.0"
    monkeypatch.setattr(version, "_metadata_version", lambda: None)
    assert version.engine_version() == version.UNKNOWN == "0.0.0+unknown"
    (tmp_path / "VERSION").write_text("not a version\n")
    assert version.engine_version() == version.UNKNOWN


def _cli_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HARRY_SDLC_", "SDLC_", "GIT_"))}
    env.update(HOME=str(home), PYTHONPATH=str(fx.TOOLING), PYTHONDONTWRITEBYTECODE="1")
    return env


def test_version_flag_without_home_or_workspace(tmp_path):
    home = tmp_path / "empty-home"
    home.mkdir()
    for argv in ([sys.executable, "-m", "sdlc.cli", "--version"],
                 ["bash", str(fx.ENGINE_ROOT / "bin" / "sdlc"), "--version"],
                 [sys.executable, "-m", "sdlc.cli", "--project", "NOPE", "--version"]):
        proc = subprocess.run(argv, cwd="/", env=_cli_env(home), capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert proc.stderr == ""
        lines = proc.stdout.splitlines()
        assert len(lines) == 1 and DEV_RE.match(lines[0]), proc.stdout
        assert lines[0].startswith(fx.repo_version() + "-dev+")
    assert os.listdir(home) == []


def test_version_flag_leaves_git_status(tmp_path):
    copy = fx.copy_engine_tree(tmp_path / "engine")
    fx.git("init", "-q", "-b", "main", cwd=copy)
    fx.git("add", "-A", cwd=copy)
    fx.git("commit", "-q", "-m", "copy", cwd=copy)
    short = fx.git("rev-parse", "--short=7", "HEAD", cwd=copy)
    before = fx.git("status", "--porcelain", "-uall", cwd=copy)
    env = _cli_env(tmp_path)
    env.pop("PYTHONPATH")
    proc = subprocess.run(["bash", str(copy / "bin" / "sdlc"), "--version"], cwd="/", env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"{fx.repo_version()}-dev+{short} (dev: {os.path.realpath(copy)})"
    assert fx.git("status", "--porcelain", "-uall", cwd=copy) == before == ""


def test_help_lists_version_option():
    proc = subprocess.run([sys.executable, "-m", "sdlc.cli", "-h"], cwd=fx.TOOLING, capture_output=True, text=True,
                          env=_cli_env(fx.TOOLING))
    assert proc.returncode == 0
    assert re.search(r"^\s+--version\s+print the engine version and mode, then exit$", proc.stdout, re.M)
