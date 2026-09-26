"""install.sh in a throwaway HOME against a local bare repository (AC6-AC11 of AISDLC-RUNWS-3).

Never touches the real HOME: every call runs with the environment (E) of ``enginefx.env_e`` (reduced
PATH without /usr/local/bin nor /opt/homebrew/bin, HOME/CLAUDE_HOME/HARRY_SDLC_HOME under tmp_path).
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

import enginefx as fx

KINDS = {"agents": "*.md", "commands": "*.md", "workflows": "*.js"}


@pytest.fixture(scope="module")
def remote(tmp_path_factory) -> fx.Remote:
    return fx.make_engine_remote(tmp_path_factory.mktemp("remote"))


@pytest.fixture
def env(tmp_path, remote) -> dict[str, str]:
    return fx.env_e(tmp_path, remote)


def install(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(fx.INSTALL_SH), *args], env=env, capture_output=True, text=True,
                          cwd=env["HOME"])


def ok(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    proc = install(env, *args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def paths(env: dict[str, str]) -> tuple[Path, Path, Path, Path]:
    home = Path(env["HOME"])
    return home, Path(env["CLAUDE_HOME"]), Path(env["HARRY_SDLC_HOME"]), home / ".local" / "bin"


def links_under(*roots: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            for name in dirnames + filenames:
                p = Path(dirpath) / name
                if p.is_symlink():
                    out[str(p)] = os.readlink(p)
    return out


def broken_links(root: Path) -> list[str]:
    return [p for p in links_under(root) if not os.path.exists(p)]


def listing(home: Path, exclude: tuple[str, ...] = ()) -> list[tuple]:
    """lstat listing of HOME (G4: os.lstat, never `stat -f`), .git folders pruned."""
    rows = []
    for dirpath, dirnames, filenames in os.walk(home):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in [""] + dirnames + filenames:
            p = Path(dirpath) / name if name else Path(dirpath)
            rel = str(p.relative_to(home))
            if rel in exclude:
                continue
            st = os.lstat(p)
            rows.append((rel, st.st_mode, st.st_mtime_ns, st.st_ctime_ns, st.st_ino,
                         os.readlink(p) if p.is_symlink() else None))
    return sorted(set(rows))


def sdlc_version(env: dict[str, str]) -> str:
    proc = subprocess.run(["sdlc", "--version"], env=env, capture_output=True, text=True, cwd=env["HOME"])
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def readlink(p: Path) -> str:
    return os.readlink(p)


# ---- AC6 -------------------------------------------------------------------------------------------------

def test_ac6_install_detached_clone_and_current(env, remote):
    ok(env, remote.tag)
    _, _, hsh, _ = paths(env)
    clone = hsh / remote.tag
    assert fx.git("describe", "--exact-match", "--tags", cwd=clone) == remote.tag
    assert subprocess.run(["git", "-C", str(clone), "symbolic-ref", "-q", "HEAD"],
                          env=fx.git_env(), capture_output=True).returncode != 0
    assert readlink(hsh / "current") == remote.tag
    assert not list(hsh.glob(".staging.*")) and not list(hsh.glob(".current.*"))


def test_ac6_all_links_through_current(env, remote):
    ok(env, remote.tag)
    _, cla, hsh, local_bin = paths(env)
    links = links_under(cla, local_bin)
    assert links, "no link created"
    outside = {k: v for k, v in links.items() if not v.startswith(f"{hsh}/current/")}
    assert outside == {}
    assert readlink(local_bin / "sdlc") == f"{hsh}/current/bin/sdlc"


def test_ac6_link_counts_match_version(env, remote):
    ok(env, remote.tag)
    _, cla, hsh, _ = paths(env)
    version_dir = hsh / remote.tag / "claude"
    for kind, pattern in KINDS.items():
        expected = sorted(p.name for p in (version_dir / kind).glob(pattern))
        assert expected, kind
        assert sorted(p.name for p in (cla / kind).iterdir() if p.is_symlink()) == expected, kind
    skills = sorted(p.name for p in (version_dir / "skills").iterdir() if p.is_dir())
    assert sorted(p.name for p in (cla / "skills").iterdir() if p.is_symlink()) == skills
    assert (cla / "agents" / "zz-retire.md").is_symlink()
    assert readlink(cla / "sdlc" / "harry.md") == f"{hsh}/current/claude/sdlc/harry.md"


def test_ac6_version_and_no_broken_links(env, remote):
    proc = ok(env, remote.tag)
    _, cla, _, local_bin = paths(env)
    assert proc.stdout.strip().splitlines()[-1] == f"{remote.v} (release)"
    assert sdlc_version(env) == f"{remote.v} (release)"
    assert broken_links(cla) == [] and broken_links(local_bin) == []
    assert (cla / "sdlc" / "projects.json").read_text() == '{\n  "projects": {}\n}\n'


# ---- AC7 -------------------------------------------------------------------------------------------------

def test_ac7_refuses_mismatch_branch_and_no_arg(env, remote):
    ok(env, remote.tag)
    proc = install(env, "v9.9.9")
    assert proc.returncode != 0
    assert "v9.9.9" in proc.stderr and remote.v in proc.stderr
    assert "tag_mismatch" in proc.stderr
    proc = install(env, remote.branch_like_tag)
    assert proc.returncode != 0 and "not_a_tag" in proc.stderr
    for args in (["main"], [], [remote.v], ["vbranch"], ["--dev"], ["--dev", "/nonexistent/engine"],
                 [remote.tag, "extra"]):
        proc = install(env, *args)
        assert proc.returncode == 2, (args, proc.stderr)
        assert "usage:" in proc.stderr


def test_ac7_nothing_changes_on_refusal(env, remote):
    ok(env, remote.tag)
    home, cla, hsh, _ = paths(env)
    # The staging folder lives inside HARRY_SDLC_HOME: only that folder's own times may move.
    hsh_rel = str(hsh.relative_to(home))
    before = listing(home, exclude=(hsh_rel,))
    entries = sorted(os.listdir(hsh))
    links_before = links_under(cla)
    for args in (["v9.9.9"], [remote.branch_like_tag], ["main"], [], [remote.v]):
        assert install(env, *args).returncode != 0
        assert listing(home, exclude=(hsh_rel,)) == before, args
        assert sorted(os.listdir(hsh)) == entries, args
    assert not (hsh / "v9.9.9").exists() and not (hsh / remote.branch_like_tag).exists()
    assert not list(hsh.glob(".staging.*"))
    assert readlink(hsh / "current") == remote.tag
    assert links_under(cla) == links_before


def test_invalid_arguments_write_nothing(env, remote):
    home, *_ = paths(env)
    before = listing(home)
    for args in (["main"], [], [remote.v], ["--dev", str(home / "missing")]):
        assert install(env, *args).returncode == 2
    assert listing(home) == before


# ---- AC8 -------------------------------------------------------------------------------------------------

def test_ac8_upgrade_removes_orphan(env, remote):
    ok(env, remote.tag)
    _, cla, hsh, _ = paths(env)
    assert (cla / "agents" / "zz-retire.md").is_symlink()
    proc = ok(env, remote.tag1)
    assert readlink(hsh / "current") == remote.tag1
    assert sdlc_version(env) == f"{remote.v1} (release)"
    assert not (cla / "agents" / "zz-retire.md").is_symlink()
    assert "removed orphan" in proc.stdout
    assert broken_links(cla) == []


def test_ac8_rollback_no_new_clone(env, remote):
    ok(env, remote.tag)
    ok(env, remote.tag1)
    _, cla, hsh, _ = paths(env)
    st = os.lstat(hsh / remote.tag)
    no_remote = dict(env, HARRY_SDLC_REPO=(Path(env["HOME"]) / "no-such-remote.git").as_uri())
    ok(no_remote, remote.tag)  # a clone would fail: the version already present is reused
    after = os.lstat(hsh / remote.tag)
    assert (st.st_mtime_ns, st.st_ctime_ns, st.st_ino) == (after.st_mtime_ns, after.st_ctime_ns, after.st_ino)
    assert readlink(hsh / "current") == remote.tag
    assert sdlc_version(env) == f"{remote.v} (release)"
    assert (cla / "agents" / "zz-retire.md").is_symlink()  # back in the active version
    assert broken_links(cla) == []


def test_ac8_both_versions_kept(env, remote):
    ok(env, remote.tag)
    ok(env, remote.tag1)
    ok(env, remote.tag)
    _, _, hsh, _ = paths(env)
    assert sorted(os.listdir(hsh)) == sorted(["current", remote.tag, remote.tag1])


# ---- AC9 -------------------------------------------------------------------------------------------------

@pytest.fixture
def dev_copy(tmp_path, remote) -> Path:
    dst = tmp_path / "dev-copy"
    fx.git("clone", "-q", remote.url, str(dst))
    return Path(os.path.realpath(dst))


def test_ac9_dev_mode_points_current_and_prints_dev(env, remote, dev_copy):
    ok(env, remote.tag)
    ok(env, "--dev", str(dev_copy))
    _, cla, hsh, _ = paths(env)
    assert readlink(hsh / "current") == str(dev_copy)
    version = (dev_copy / "VERSION").read_text().strip()
    short = fx.git("rev-parse", "--short=7", "HEAD", cwd=dev_copy)
    line = sdlc_version(env)
    assert re.fullmatch(rf"{re.escape(version)}-dev\+[0-9a-f]{{7,}}(\.dirty)? \(dev: {re.escape(str(dev_copy))}\)",
                        line), line
    assert line.startswith(f"{version}-dev+{short}")
    assert broken_links(cla) == []


def test_ac9_back_to_release(env, remote, dev_copy):
    ok(env, remote.tag)
    ok(env, "--dev", str(dev_copy))
    ok(env, remote.tag)
    _, _, hsh, _ = paths(env)
    assert readlink(hsh / "current") == remote.tag
    assert sdlc_version(env) == f"{remote.v} (release)"


def test_ac9_dev_tree_untouched(env, remote, dev_copy):
    before = fx.git("status", "--porcelain", "-uall", cwd=dev_copy)
    head = fx.git("rev-parse", "HEAD", cwd=dev_copy)
    ok(env, "--dev", str(dev_copy))
    sdlc_version(env)
    ok(env, "--dev", str(dev_copy))
    assert fx.git("status", "--porcelain", "-uall", cwd=dev_copy) == before == ""
    assert fx.git("rev-parse", "HEAD", cwd=dev_copy) == head


# ---- AC10 ------------------------------------------------------------------------------------------------

def test_ac10_user_state_and_third_party_preserved(env, remote, tmp_path):
    home, cla, _, _ = paths(env)
    for kind in ("agents", "commands", "sdlc"):
        (cla / kind).mkdir(parents=True, exist_ok=True)
    projects = cla / "sdlc" / "projects.json"
    projects.write_text('{"projects": {"AAA": {"path": "/x/a"}, "BBB": {"path": "/x/b"}}}\n')
    perso = cla / "commands" / "perso.md"
    perso.write_text("# my own command\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "tiers.md").write_text("# third party\n")
    (cla / "agents" / "tiers.md").symlink_to(elsewhere / "tiers.md")
    settings = cla / "settings.json"
    settings.write_text('{"permissions": {}}\n')
    private = [cla / "sdlc" / "profile", cla / "sdlc" / "agent_runs.log", cla / "sdlc" / "locks"]
    private[0].write_text("po\n")
    private[1].write_text("log\n")
    private[2].mkdir()
    shas = {p: sha(p) for p in (projects, perso, settings, private[0], private[1])}
    for p in private:
        p.chmod(0)
    try:
        ok(env, remote.tag)
    finally:
        for p in private:
            p.chmod(0o755 if p.is_dir() else 0o644)
    assert {p: sha(p) for p in shas} == shas
    assert readlink(cla / "agents" / "tiers.md") == str(elsewhere / "tiers.md")
    assert not perso.is_symlink()


def test_ac10_old_mode_links_migrated(env, remote, tmp_path):
    home, cla, hsh, local_bin = paths(env)
    old = tmp_path / "old" / "harry-sdlc-local"  # never created: every old-mode link is broken
    for kind in ("commands", "skills"):
        (cla / kind).mkdir(parents=True, exist_ok=True)
    local_bin.mkdir(parents=True)
    (cla / "commands" / "sdlc.md").symlink_to(old / "claude" / "commands" / "sdlc.md")
    (cla / "skills" / "recette").symlink_to(old / "claude" / "skills" / "recette")
    (cla / "commands" / "review.md").symlink_to(old / "claude" / "commands" / "review.md")  # not in the engine
    (local_bin / "sdlc").symlink_to(old / "bin" / "sdlc")
    proc = ok(env, remote.tag)
    assert readlink(cla / "commands" / "sdlc.md") == f"{hsh}/current/claude/commands/sdlc.md"
    assert readlink(cla / "skills" / "recette") == f"{hsh}/current/claude/skills/recette"
    assert readlink(local_bin / "sdlc") == f"{hsh}/current/bin/sdlc"
    assert f"migrated {cla}/commands/sdlc.md" in proc.stdout
    assert f"migrated {local_bin}/sdlc" in proc.stdout
    # G7: an old-mode link whose name is not in the active version is reported, not touched
    assert readlink(cla / "commands" / "review.md") == str(old / "claude" / "commands" / "review.md")
    assert f"stale (not in {remote.tag}): {cla}/commands/review.md" in proc.stderr
    assert sdlc_version(env) == f"{remote.v} (release)"


def test_real_file_with_engine_name_skipped_with_warning(env, remote):
    _, cla, _, _ = paths(env)
    (cla / "agents").mkdir(parents=True)
    real = cla / "agents" / "reviewer.md"
    real.write_text("# a local reviewer, not the engine one\n")
    digest = sha(real)
    proc = ok(env, remote.tag)
    assert not real.is_symlink() and sha(real) == digest
    assert f"skipped (not managed): {real}" in proc.stderr


# ---- AC11 ------------------------------------------------------------------------------------------------

def test_ac11_idempotent_stat_listing(env, remote):
    home, *_ = paths(env)
    ok(env, remote.tag)
    first = listing(home, exclude=(".zshrc",))
    second_proc = ok(env, remote.tag)
    second = listing(home, exclude=(".zshrc",))
    ok(env, remote.tag)
    third = listing(home, exclude=(".zshrc",))
    assert first == second == third
    assert "linked" not in second_proc.stdout and "current ->" not in second_proc.stdout


def test_ac11_single_zshrc_line(env, remote):
    home, _, _, local_bin = paths(env)
    no_bin_in_path = dict(env, PATH=env["PATH"].split(":", 1)[1])  # ~/.local/bin not in PATH
    for _ in range(3):
        ok(no_bin_in_path, remote.tag)
    rc = (home / ".zshrc").read_text()
    assert rc.count("harry-sdlc") == 1
    assert rc.count('export PATH="$HOME/.local/bin:$PATH"') == 1
    assert (local_bin / "sdlc").is_symlink()


def test_ac11_two_entries_in_home(env, remote):
    for _ in range(3):
        ok(env, remote.tag)
    _, _, hsh, _ = paths(env)
    assert sorted(os.listdir(hsh)) == sorted(["current", remote.tag])


# ---- static guards (inv. 25, 32) -------------------------------------------------------------------------

def test_install_script_guards():
    text = fx.INSTALL_SH.read_text()
    assert text.count("rm -rf") == 1 and 'rm -rf "$STAGE"' in text
    assert '"$HSH"/.staging.*) rm -rf "$STAGE"' in text
    assert not re.search(r"\bsudo\b|\bchmod\b|/tmp\b", text)
    bash32 = re.compile(r"mapfile|readarray|declare -A|\$\{[a-zA-Z_]+,,|\$\{[a-zA-Z_]+\^\^|&>>")
    for script in [fx.INSTALL_SH, *sorted(fx.SCRIPTS.glob("*.sh"))]:
        assert not bash32.search(script.read_text()), script
        assert subprocess.run(["bash", "-n", str(script)]).returncode == 0, script
