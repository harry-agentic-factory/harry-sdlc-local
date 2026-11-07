"""The brain of a run comes from git: pinned clone, exclusions, subtree, integrity, warnings.

One test per invariant of the story: the clone is standalone and detached (I6, I6bis), the brain
exclusions survive the clone (I6ter), `in/brain/` is a subtree with no manifest entry (I7), its
integrity is checked at finish (I7bis), a brain key reads by its path (I8), and an unreadable brain
never fails a run (I9).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from sdlc.runws import gitcode
from test_run_workspace import (BRAIN_INDEX_C1, RECAP_DOC, add, call, commit_all, git, init,
                                make_demo, ok, write)


@pytest.fixture
def demo(tmp_path, monkeypatch):
    return make_demo(tmp_path, monkeypatch)


@pytest.fixture
def cap(capsysbinary):
    return capsysbinary


def in_brain(res) -> Path:
    return Path(res["in"]) / "brain"


def brain_files(res) -> list[str]:
    root = in_brain(res)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and ".git" not in p.relative_to(root).parts)


# --- I6 / I6bis: one sequence, a standalone detached clone ---

def test_i6bis_clone_detached_standalone_without_remote(demo, cap):
    res = init(cap)
    brain = in_brain(res)
    assert git(demo.brain, "rev-parse", "HEAD") == demo.c1
    assert git(brain, "rev-parse", "HEAD") == demo.c1 == res["brain"]["commit"]
    assert git(brain, "remote") == ""
    config = (brain / ".git" / "config").read_text()
    assert str(demo.brain) not in config and "url" not in config and "remote" not in config
    assert subprocess.run(["git", "-C", str(brain), "symbolic-ref", "-q", "HEAD"],
                          capture_output=True).returncode != 0
    assert not (brain / ".git" / "objects" / "info" / "alternates").exists()
    assert gitcode.scan_repo(brain) is None            # neither commondir nor borrowed objects
    assert gitcode.neighbour_clean(brain)


def test_i6_sparse_is_posted_before_the_checkout(demo, cap, monkeypatch):
    """Order matters: a checkout before the patterns writes the excluded content, then takes it back.

    The end state is the same, so only the sequence can tell: what is excluded (the `.claude/` of
    the brain, which carries instructions) must NEVER touch the disk of the agent.
    """
    seen: list[str] = []
    real = gitcode._git_trusted

    def spy(*args, cwd=None):
        seen.append(args[0])
        return real(*args, cwd=cwd)

    monkeypatch.setattr(gitcode, "_git_trusted", spy)
    init(cap)
    assert seen[:4] == ["clone", "sparse-checkout", "checkout", "remote"]


def test_i6_extraction_never_uses_archive_or_snapshot():
    """The brain path of the engine clones; `git archive` and `snapshot()` would leave no `.git`."""
    pkg = Path(gitcode.__file__).parent
    for name in ("gitcode.py", "datarepo.py", "lifecycle.py"):
        text = (pkg / name).read_text(encoding="utf-8")
        assert "git archive" not in text and '"archive"' not in text
        assert "snapshot(" not in text


# --- I6ter: the exclusions of the brain are reapplied, as inclusion patterns ---

def test_i6ter_sparse_patterns_are_inclusions():
    """An inverted form would post ONLY the excluded paths: the patterns are negations of `/*`."""
    assert gitcode.sparse_patterns((".claude/**", "hooks/**", "adr/", "**/scratch-*.md")) == [
        "/*", "!/.claude/**", "!/hooks/**", "!/adr/**", "!**/scratch-*.md"]


def test_i6ter_excluded_paths_never_written(demo, cap):
    write(demo.brain, ".claude/settings.json", b"{}\n")
    write(demo.brain, ".claude/instructions.md", b"# do this\n")
    write(demo.brain, "hooks/pre-commit", b"#!/bin/sh\n")
    write(demo.brain, "brain-map.yaml", b"exclude:\n  - adr/\n")
    write(demo.brain, "keep/note.md", b"# keep\n")
    commit = commit_all(demo.brain, "excluded content")
    res = init(cap)
    brain = in_brain(res)
    assert res["brain"]["commit"] == commit
    assert brain_files(res) == ["brain-map.yaml", "index.md", "keep/note.md", "logo.png"]
    assert not (brain / ".claude").exists() and not (brain / "hooks").exists()
    assert not (brain / "adr").exists()
    tracked = git(demo.brain, "ls-tree", "-r", "--name-only", commit).splitlines()
    assert sorted(tracked) == sorted(brain_files(res) + [".claude/instructions.md",
                                                         ".claude/settings.json", "adr/0001.md",
                                                         "hooks/pre-commit"])
    assert git(brain, "status", "--porcelain", "--ignored") == ""      # skip-worktree, still clean


# --- I7: a subtree, not files of the manifest ---

def test_i7_no_brain_entry_and_subtree_tolerated(demo, cap, monkeypatch):
    res = init(cap)
    man = json.loads(Path(res["manifest"]).read_text())
    assert not [e for e in man["files"] if e["key"].startswith("brain")]
    assert man["brain"] == {"repo": str(demo.brain), "branch": "main", "commit": demo.c1}
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    write(in_brain(res), "untracked.md", b"# written by nobody\n")
    rc, out, _ = call(cap, "run", "finish", res["run_uid"])
    assert rc == 1 and json.loads(out)["reasons"] == ["in_modified:brain"]   # git sees it, not the walk


def test_i7_file_added_elsewhere_under_in_is_refused(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    write(Path(res["in"]), "feature/sneaky.md", b"# added\n")
    rc, out, _ = call(cap, "run", "finish", res["run_uid"])
    assert rc == 1 and json.loads(out)["reasons"] == ["in_modified:feature/sneaky.md"]


def test_i7_in_path_has_no_brain_branch():
    from sdlc.runws import layout
    scope = layout.Scope("DEMO-E", "DEMO-E-1", None)
    assert layout.in_path("project/brain/@" + "c" * 40 + "/index.md", scope) is None
    assert layout.in_path("features/DEMO-E/atelier/prd.md", scope) == "feature/atelier/prd.md"
    assert layout.BRAIN_DIR == "brain" and "in/brain" not in layout.in_dirs(scope)


# --- I7bis: integrity of the subtree, by the neighbour check ---

def test_i7bis_brain_moved_to_another_commit_is_rejected(demo, cap, monkeypatch):
    write(demo.brain, "index.md", b"# Index C2\n")
    c2 = commit_all(demo.brain, "C2")
    res = init(cap)
    assert res["brain"]["commit"] == c2
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    git(in_brain(res), "checkout", "--quiet", "--detach", demo.c1)
    rc, out, _ = call(cap, "run", "finish", res["run_uid"])
    assert rc == 1 and json.loads(out)["reasons"] == ["in_modified:brain"]
    git(in_brain(res), "checkout", "--quiet", "--detach", c2)
    rc, fin = call(cap, "run", "finish", res["run_uid"])[:2]
    assert rc == 0 and json.loads(fin)["state"] == "published"


def test_i7bis_modified_file_of_the_brain_is_rejected(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    (in_brain(res) / "index.md").write_bytes(b"# forged\n")
    rc, out, _ = call(cap, "run", "finish", res["run_uid"])
    assert rc == 1 and json.loads(out)["reasons"] == ["in_modified:brain"]


def test_i7bis_no_commit_no_check(demo, cap, monkeypatch):
    """A brain outside git has no commit: nothing to compare, the run goes through."""
    plain = demo.tmp / "plain-brain"
    write(plain, "index.md", b"# plain\n")
    demo.set_config(brain=str(plain))
    res = init(cap)
    assert res["warnings"] == ["brain_not_git"] and not (in_brain(res) / ".git").exists()
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    rc, fin = call(cap, "run", "finish", res["run_uid"])[:2]
    assert rc == 0 and json.loads(fin)["state"] == "published"


# --- I8: `doc read` of the brain by its path ---

def test_i8_brain_read_by_path(demo, cap, monkeypatch):
    res = init(cap)
    monkeypatch.setenv("SDLC_RUN", res["root"])
    assert call(cap, "doc", "read", "brain/index")[:2] == (0, BRAIN_INDEX_C1)
    assert call(cap, "doc", "read", "brain/index.md")[:2] == (0, BRAIN_INDEX_C1)
    assert call(cap, "doc", "read", "brain/adr/0001")[0] == 0
    assert [d["key"] for d in ok(cap, "doc", "list")] == sorted(
        ["prd", "DEMO-E-1/spec-func", "DEMO-E-1/spec-tech", "DEMO-E-2/spec-tech"])


@pytest.mark.parametrize("key", ["brain/logo.png", "brain/logo", "brain/../index", "brain/nope",
                                 "brain/adr", "brain//index"])
def test_i8_brain_read_refusals(demo, cap, monkeypatch, key):
    res = init(cap)
    monkeypatch.setenv("SDLC_RUN", res["root"])
    rc, out, err = call(cap, "doc", "read", key)
    assert rc != 0 and out == b"" and "unknown_key" in json.loads(err)["error"]


def test_i8_brain_symlink_refused(demo, cap, monkeypatch):
    res = init(cap)
    os.symlink(Path(res["in"]) / "feature" / "atelier" / "prd.md", in_brain(res) / "link.md")
    monkeypatch.setenv("SDLC_RUN", res["root"])
    rc, out, _ = call(cap, "doc", "read", "brain/link")
    assert rc != 0 and out == b""


# --- I9: an unreadable brain never fails a run ---

def test_i9_extract_failure_is_a_warning(demo, cap, monkeypatch):
    def boom(*a, **kw):
        raise gitcode.RunError("clone_failed", "brain")

    monkeypatch.setattr(gitcode, "clone_brain", boom)
    res = init(cap)
    assert res["warnings"] == ["brain_extract_failed"]
    assert not in_brain(res).exists() and res["brain"] == {
        "ref": "main", "commit": None, "from": "local", "files": 0, "bytes": 0}
    man = json.loads(Path(res["manifest"]).read_text())
    # I6: no commit resolved ⇒ `null`, never a branch alone. The cause is in `warnings`.
    assert man["brain"] is None
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    rc, fin = call(cap, "run", "finish", res["run_uid"])[:2]
    assert rc == 0 and json.loads(fin)["state"] == "published"


@pytest.mark.parametrize("code,prepare", [
    ("brain_not_declared", lambda d: d.set_config(brain=None)),
    ("brain_missing", lambda d: d.set_config(brain=str(d.tmp / "nowhere"))),
    ("brain_ref_unresolved", lambda d: d.set_config(brainRef="v9")),
])
def test_i9_every_warning_code_keeps_the_run(demo, cap, code, prepare):
    prepare(demo)
    res = init(cap)
    assert res["warnings"] == [code] and not in_brain(res).exists()
    assert res["brain"]["commit"] is None
