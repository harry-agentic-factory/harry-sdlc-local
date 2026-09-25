"""`sdlc brain` (library + CLI) on the fixture (F): a throwaway git brain built by the test.

(F) `fx-brain`, branch `main`:
- C1 (annotated tag `v1`): README.md, per-repo/a.md, per-repo/b.md, per-repo/c.md (CRLF, no final
  newline), technical/architecture.md (front matter without category), misc/notes.md,
  .claude/cmd.md, hooks/h.md, .gitignore (= secret.md).
- C2 (`main`): per-repo/b.md renamed to per-repo/b2.md + per-repo/a.md modified.
- Dirty working copy: per-repo/a.md modified (uncommitted), new.md untracked, secret.md ignored.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from sdlc import cli
from sdlc.brain import gitio
from sdlc.brain.frontmatter import parse_frontmatter
from sdlc.brain.links import note_links
from sdlc.brain.mapping import DEFAULT_RULES, deduce

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]
BOM = b"\xef\xbb\xbf"

README_C1 = (b"# Fx brain\n\nSee [arch](technical/architecture.md).\n"
             b"Also `../fx-brain/per-repo/a.md` for details.\n"
             b"Site: https://example.org\n")
A_C1 = b"# A\n\n[x](missing.md)\n"
A_C2 = b"# A\n\nSecond version.\n\n[x](missing.md)\n"
C_CRLF = b"# C\r\n\r\nbody line\r\nlast line without newline"
ARCH = b"---\nowner: x\ntags: [a]\n---\n# Architecture\n\nText.\n"


# --- helpers ---

def git(repo, *args, check=True, env=None) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, env=env).stdout.strip()


def git_bytes(repo, *args) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def refs(repo) -> str:
    return git(repo, "for-each-ref", "--format=%(refname) %(objectname)")


def write(root: Path, rel: str, data: bytes) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def fx_add_commit(repo, parent: str, changes: dict[str, bytes | None], *, ref: str | None = None,
                  message: str = "change", extra_parents: tuple[str, ...] = ()) -> str:
    """Commit `changes` (path -> bytes, None = delete) on top of `parent` with plumbing only,
    so the dirty working copy of the fixture is never staged. Optionally move `ref` there."""
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(d, "index")}
        git(repo, "read-tree", parent, env=env)
        for path, data in changes.items():
            if data is None:
                git(repo, "update-index", "--force-remove", path, env=env)
                continue
            sha = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=data,
                                 capture_output=True, check=True).stdout.decode().strip()
            git(repo, "update-index", "--add", "--cacheinfo", f"100644,{sha},{path}", env=env)
        tree = git(repo, "write-tree", env=env)
    parents = []
    for p in (parent, *extra_parents):
        parents += ["-p", p]
    sha = git(repo, *GIT_ID, "commit-tree", tree, *parents, "-m", message)
    if ref:
        git(repo, "update-ref", ref, sha)
    return sha


def fx_branch(repo, name: str, parent: str, changes: dict[str, bytes | None]) -> str:
    return fx_add_commit(repo, parent, changes, ref=f"refs/heads/{name}")


def fx_clone(src: Path, dst: Path) -> Path:
    subprocess.run(["git", "clone", "-q", str(src), str(dst)], check=True, capture_output=True)
    return dst


@dataclass
class FxBrain:
    path: Path
    c1: str
    c2: str
    tag: str = "v1"


def make_fx_brain(tmp_path: Path) -> FxBrain:
    root = tmp_path / "fx-brain"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "t")          # identity for normalize's commit-tree
    git(root, "config", "user.email", "t@t")
    for rel, data in {
        "README.md": README_C1, "per-repo/a.md": A_C1, "per-repo/b.md": b"# B\n",
        "per-repo/c.md": C_CRLF, "technical/architecture.md": ARCH, "misc/notes.md": b"# Notes\n",
        ".claude/cmd.md": b"# tool\n", "hooks/h.md": b"# hook\n", ".gitignore": b"secret.md\n",
    }.items():
        write(root, rel, data)
    git(root, "add", "-A")
    git(root, *GIT_ID, "commit", "-q", "-m", "C1")
    c1 = git(root, "rev-parse", "HEAD")
    git(root, *GIT_ID, "tag", "-a", "v1", "-m", "v1")
    git(root, "mv", "per-repo/b.md", "per-repo/b2.md")
    write(root, "per-repo/a.md", A_C2)
    git(root, "add", "-A")
    git(root, *GIT_ID, "commit", "-q", "-m", "C2")
    c2 = git(root, "rev-parse", "HEAD")
    write(root, "per-repo/a.md", A_C2 + b"uncommitted change\n")
    write(root, "new.md", b"# untracked\n")
    write(root, "secret.md", b"# ignored\n")
    return FxBrain(root, c1, c2)


def make_fx_host(tmp_path: Path) -> Path:
    host = tmp_path / "fx-host"
    host.mkdir()
    git(host, "init", "-q", "-b", "main")
    for rel, data in {"README.md": b"# Host\n", "src/x.md": b"# X\n", "docs/README.md": b"# Docs\n",
                      "docs/per-repo/a.md": b"# A\n\n[r](../README.md)\n"}.items():
        write(host, rel, data)
    git(host, "add", "-A")
    git(host, *GIT_ID, "commit", "-q", "-m", "host")
    return host


def make_fx_master(tmp_path: Path) -> Path:
    repo = tmp_path / "fx-master"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    write(repo, "README.md", b"# M\n")
    git(repo, "add", "-A")
    git(repo, *GIT_ID, "commit", "-q", "-m", "m")
    return repo


def run(capsys, *argv):
    """(exit, parsed stdout or raw text, stderr) of `sdlc <argv>`."""
    rc = cli.main([str(a) for a in argv])
    cap = capsys.readouterr()
    try:
        out = json.loads(cap.out) if cap.out.strip() else None
    except ValueError:
        out = cap.out
    return rc, out, cap.err


def body(data: bytes) -> bytes:
    return data[parse_frontmatter(data).body_start:]


@pytest.fixture
def fx(tmp_path) -> FxBrain:
    return make_fx_brain(tmp_path)


def normalize_cat(capsys, fx, branch="brain/cat", *extra):
    rc, rep, err = run(capsys, "brain", "normalize", "--repo", fx.path, "--branch", branch, *extra)
    assert rc == 0, err
    return rep


# --- AC1: normalize deduces, merges and reports the undecidable ---

def test_ac1_normalize_dry_run_counts_and_undecidable(capsys, fx):
    rc, rep, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run")
    assert rc == 0
    assert rep["counts"] == {"usage": 1, "repo": 3, "archi": 1}
    assert rep["undecidable"] == ["misc/notes.md"]
    assert len(rep["deduced"]) == 5
    by_path = {d["path"]: d["category"] for d in rep["deduced"]}
    assert by_path == {"README.md": "usage", "per-repo/a.md": "repo", "per-repo/b2.md": "repo",
                       "per-repo/c.md": "repo", "technical/architecture.md": "archi"}
    assert rep["branch"] is None and rep["commit"] is None and rep["commit_base"] == fx.c2
    assert set(rep) == {"commit_base", "branch", "commit", "counts", "deduced", "already", "invalid",
                        "undecidable", "broken_links"}
    assert all(set(d) == {"path", "category", "rule"} for d in rep["deduced"])


def test_ac1_tooling_ignored_untracked_absent(capsys, fx):
    rc = cli.main(["brain", "normalize", "--repo", str(fx.path), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    for needle in (".claude/", "hooks/", "new.md", "secret.md"):
        assert needle not in out


def test_ac1_dry_run_creates_no_branch(capsys, fx):
    before = refs(fx.path)
    rc, _, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run")
    assert rc == 0 and refs(fx.path) == before


# --- AC2: new branch, never main, working copy untouched ---

def test_ac2_normalize_new_branch_one_commit(capsys, fx):
    rep = normalize_cat(capsys, fx)
    assert rep["branch"] == "brain/cat"
    assert git(fx.path, "rev-list", "--count", "main..brain/cat") == "1"
    assert git(fx.path, "rev-parse", "main") == fx.c2
    assert git(fx.path, "rev-parse", "brain/cat") == rep["commit"]
    assert git(fx.path, "log", "-1", "--format=%s", "brain/cat") == "docs(brain): add category headers"
    assert git(fx.path, "rev-parse", "brain/cat^") == fx.c2


def test_normalize_refuses_protected_and_existing(capsys, fx, tmp_path):
    normalize_cat(capsys, fx)
    for branch, code in (("main", "branch_protected"), ("master", "branch_protected"),
                         ("brain/cat", "branch_exists"), ("bad..name", "branch_invalid")):
        before = refs(fx.path)
        rc, _, err = run(capsys, "brain", "normalize", "--repo", fx.path, "--branch", branch)
        assert rc == 2, branch
        assert json.loads(err)["code"] == code
        assert refs(fx.path) == before
    # default branch of origin (origin/HEAD) is protected too, whatever its name
    up = tmp_path / "up"
    up.mkdir()
    git(up, "init", "-q", "-b", "trunk")
    write(up, "README.md", b"# up\n")
    git(up, "add", "-A")
    git(up, *GIT_ID, "commit", "-q", "-m", "up")
    clone = fx_clone(up, tmp_path / "up-clone")
    before = refs(clone)
    rc, _, err = run(capsys, "brain", "normalize", "--repo", clone, "--base", "trunk", "--branch", "trunk")
    assert rc == 2 and json.loads(err)["code"] == "branch_protected"
    assert refs(clone) == before


def _fingerprint(repo: Path) -> tuple:
    return (git(repo, "status", "--porcelain"),
            hashlib.sha256((repo / "per-repo/a.md").read_bytes()).hexdigest(),
            git(repo, "branch", "--show-current"),
            len(git(repo, "worktree", "list").splitlines()),
            hashlib.sha256((repo / ".git" / "index").read_bytes()).hexdigest(),
            git(repo, "rev-parse", "HEAD"))


def test_ac2_worktree_index_and_head_untouched(capsys, fx):
    s0 = _fingerprint(fx.path)
    normalize_cat(capsys, fx)
    run(capsys, "brain", "normalize", "--repo", fx.path, "--branch", "main")
    run(capsys, "brain", "normalize", "--repo", fx.path, "--branch", "brain/cat")
    assert _fingerprint(fx.path) == s0
    assert s0[3] == 1


def test_normalize_failed_commit_creates_no_ref(capsys, fx, monkeypatch):
    created: list[str] = []
    real_mkdtemp = gitio.tempfile.mkdtemp

    def spy_mkdtemp(*a, **k):
        d = real_mkdtemp(*a, **k)
        created.append(d)
        return d

    def failing_commit_tree(*a, **k):
        raise gitio.BrainError("git_failed", "git commit-tree failed: simulated")

    monkeypatch.setattr(gitio.tempfile, "mkdtemp", spy_mkdtemp)
    monkeypatch.setattr(gitio, "commit_tree", failing_commit_tree)
    before = refs(fx.path)
    s0 = _fingerprint(fx.path)
    rc, _, err = run(capsys, "brain", "normalize", "--repo", fx.path, "--branch", "brain/fail")
    assert rc == 2 and json.loads(err)["code"] == "git_failed"
    assert refs(fx.path) == before
    assert _fingerprint(fx.path) == s0
    assert created and not any(os.path.exists(d) for d in created)


# --- AC3: body byte for byte, existing front matter merged ---

@pytest.mark.parametrize("case,data", [
    ("lf", b"# X\n\nbody\n"),
    ("crlf_no_final_newline", b"# X\r\n\r\nbody\r\nend"),
    ("bom", BOM + b"# X\n\nbody\n"),
    ("existing_frontmatter", b"---\nowner: y\n---\n# X\nbody"),
])
def test_ac3_body_byte_identical(capsys, tmp_path, case, data):
    repo = tmp_path / "b"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "user.email", "t@t")
    write(repo, "per-repo/x.md", data)
    git(repo, "add", "-A")
    git(repo, *GIT_ID, "commit", "-q", "-m", "x")
    rc, rep, err = run(capsys, "brain", "normalize", "--repo", repo, "--branch", "brain/x")
    assert rc == 0, err
    after = git_bytes(repo, "show", "brain/x:per-repo/x.md")
    assert body(after) == body(data)
    assert parse_frontmatter(after).category == "repo"
    added, deleted, _ = git(repo, "diff", "--numstat", "main", "brain/x").split("\t")
    assert int(deleted) == (1 if case == "bom" else 0)


def test_ac3_existing_keys_order_kept(capsys, fx):
    normalize_cat(capsys, fx)
    after = git_bytes(fx.path, "show", "brain/cat:technical/architecture.md")
    assert after.startswith(b"---\nowner: x\ntags: [a]\ncategory: archi\n---\n")
    assert body(after) == body(ARCH)
    assert parse_frontmatter(after).keys == ("owner", "tags", "category")


def test_ac3_rerun_all_already(capsys, fx):
    normalize_cat(capsys, fx)
    for p in ("README.md", "per-repo/a.md", "per-repo/b2.md", "per-repo/c.md", "technical/architecture.md"):
        assert body(git_bytes(fx.path, "show", f"brain/cat:{p}")) == body(git_bytes(fx.path, "show", f"main:{p}"))
    assert git(fx.path, "diff", "main", "brain/cat", "--", "misc/notes.md") == ""
    numstat = git(fx.path, "diff", "--numstat", "main", "brain/cat").splitlines()
    assert len(numstat) == 5 and all(line.split("\t")[1] == "0" for line in numstat)
    rc, rep, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--base", "brain/cat", "--dry-run")
    assert rc == 0 and len(rep["already"]) == 5 and rep["deduced"] == []


def test_ac3_crlf_block_no_bare_lf(capsys, fx):
    normalize_cat(capsys, fx)
    data = git_bytes(fx.path, "show", "brain/cat:per-repo/c.md")
    assert data.count(b"\n") == data.count(b"\r\n")
    assert data.startswith(b"---\r\ncategory: repo\r\n---\r\n")
    assert data[-2:] == C_CRLF[-2:]


def test_ac3_bom_kept_at_offset_0_and_lint_reads_it(capsys, fx):
    fx_branch(fx.path, "fx-bom", "main", {"per-repo/d.md": BOM + b"# D\n"})
    rc, _, err = run(capsys, "brain", "normalize", "--repo", fx.path, "--base", "fx-bom", "--branch", "brain/bom")
    assert rc == 0, err
    data = git_bytes(fx.path, "show", "brain/bom:per-repo/d.md")
    assert data[:7].hex() == "efbbbf2d2d2d0a"
    rc, res, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "brain/bom")
    assert "per-repo/d.md" not in [e["path"] for e in res["errors"]]


# --- AC4: configurable mapping ---

def test_ac4_repo_map_extends_defaults(capsys, fx):
    fx_branch(fx.path, "withmap", "main", {"brain-map.yaml": b'rules:\n  - "misc/**": produit\n'})
    rc, rep, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--base", "withmap", "--dry-run")
    assert rc == 0
    assert rep["counts"]["produit"] == 1 and rep["undecidable"] == []
    assert rep["counts"]["repo"] == 3 and rep["counts"]["usage"] == 1


def test_ac4_invalid_category_names_rule(capsys, fx, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text('rules:\n  - "misc/**": foo\n')
    rc, _, err = run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run", "--map", bad)
    assert rc == 2 and "foo" in err and "misc/**" in err
    assert json.loads(err)["code"] == "mapping_invalid_category"


def test_ac4_unsupported_yaml_exit_2(capsys, fx, tmp_path):
    nested = tmp_path / "nested.yaml"
    nested.write_text('rules:\n  - "misc/**":\n      category: produit\n')
    rc, _, err = run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run", "--map", nested)
    assert rc == 2 and json.loads(err)["code"] == "mapping_unsupported"
    rc, _, err = run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run", "--map", tmp_path / "none.yaml")
    assert rc == 2 and json.loads(err)["code"] == "mapping_not_found"


def test_ac4_project_rules_before_defaults(capsys, fx, tmp_path):
    m = tmp_path / "m.yaml"
    m.write_text('rules:\n  - "per-repo/c.md": usage\n')
    rc, rep, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run", "--map", m)
    by = {d["path"]: d for d in rep["deduced"]}
    assert by["per-repo/c.md"]["category"] == "usage" and by["per-repo/c.md"]["rule"] == "per-repo/c.md"
    assert by["per-repo/a.md"]["category"] == "repo" and by["per-repo/b2.md"]["category"] == "repo"


def test_ac4_matcher_single_star_stays_in_segment(capsys, fx, tmp_path):
    fx_branch(fx.path, "deep", "main", {"per-repo/x/y.md": b"# Y\n"})
    m = tmp_path / "m.yaml"
    m.write_text('rules:\n  - "per-repo/*": usage\n')
    rc, rep, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--base", "deep", "--dry-run", "--map", m)
    by = {d["path"]: d for d in rep["deduced"]}
    assert by["per-repo/a.md"]["category"] == "usage"
    assert by["per-repo/x/y.md"]["rule"] == "per-repo/**"
    assert by["technical/architecture.md"]["rule"] == "**/architecture*.md"


@pytest.mark.parametrize("pattern,path,expected", [
    ("**/ci-cd*", "ci-cd.md", True),
    ("**/ci-cd*", "deployments/ci-cd.md", True),
    ("**/ci-cd*", "a/b/ci-cd.md", True),
    ("per-repo/*", "per-repo/a.md", True),
    ("per-repo/*", "per-repo/x/y.md", False),
    ("per-repo/**", "per-repo/x/y.md", True),
    ("per-repo/**", "per-repo", True),
    ("README.md", "README.md", True),
    ("README.md", "docs/README.md", False),
    ("*.md", "a/b.md", False),
    ("a?.md", "ab.md", True),
    ("a?.md", "a/.md", False),
    ("**", "any/thing.md", True),
    ("x/**/y.md", "x/y.md", True),
    ("x/**/y.md", "x/a/b/y.md", True),
    ("[ab].md", "[ab].md", True),
    ("[ab].md", "a.md", False),
    ("{a,b}.md", "{a,b}.md", True),
    ("{a,b}.md", "a.md", False),
    ("per-repo", "per-repo/a.md", False),
])
def test_match_glob_table(pattern, path, expected):
    from sdlc.brain import match_glob
    assert match_glob(pattern, path) is expected


def test_default_rules_cicd_before_exploit():
    assert deduce("deployments/ci-cd.md", DEFAULT_RULES) == ("cicd", "**/ci-cd*")
    assert deduce("deployments/kubernetes.md", DEFAULT_RULES) == ("exploit", "**/kubernetes*")
    assert deduce("misc/notes.md", DEFAULT_RULES) is None
    rules = [p for p, _ in DEFAULT_RULES]
    assert rules.index("**/cicd*") < rules.index("**/kubernetes*")


@pytest.mark.parametrize("text,expected", [
    ('rules:\n  - "misc/**": produit\n', ((("misc/**", "produit"),), ())),
    ("# comment\nrules:\n  - per-repo/**: repo  # trailing\n  - 'a b/*.md': usage\nexclude:\n  - drafts/\n"
     "  - \"x#y/**\"\n", ((("per-repo/**", "repo"), ("a b/*.md", "usage")), ("drafts/", "x#y/**"))),
    ("﻿exclude:\n  - tmp/\n", ((), ("tmp/",))),
    ("", ((), ())),
    ('rules:\n  - "a": foo\n', "mapping_invalid_category"),
    ('rules:\n\t- "a": repo\n', "mapping_unsupported"),
    ('rules:\n  - "a": repo\nrules:\n  - "b": repo\n', "mapping_unsupported"),
    ('other:\n  - "a": repo\n', "mapping_unsupported"),
    ('rules:\n  - "a":\n      category: repo\n', "mapping_unsupported"),
    ('rules:\n  - "a": {x: repo}\n', "mapping_unsupported"),
    ('exclude:\n  - a: b\n', "mapping_unsupported"),
    ('  - "a": repo\n', "mapping_unsupported"),
    ('rules: []\n', "mapping_unsupported"),
])
def test_yaml_subset_parser_table(text, expected):
    from sdlc.brain import BrainError, parse_mapping
    data = text.encode("utf-8")
    if isinstance(expected, str):
        with pytest.raises(BrainError) as ei:
            parse_mapping(data)
        assert ei.value.code == expected
    else:
        m = parse_mapping(data)
        assert (m.rules, m.excludes) == expected


def test_mapping_exclude_is_added(capsys, fx, tmp_path):
    m = tmp_path / "m.yaml"
    m.write_text("exclude:\n  - misc/\n")
    rc, rep, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run", "--map", m,
                     "--exclude", "technical/**")
    assert rc == 0 and rep["undecidable"] == []
    assert "technical/architecture.md" not in [d["path"] for d in rep["deduced"]]


# --- AC5: lint exit codes ---

def test_ac5_lint_exit_codes(capsys, fx, tmp_path):
    rc, res, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "main")
    assert rc == 1 and len(res["errors"]) == 6 and res["notes"] == 6
    assert set(res) == {"commit", "notes", "errors", "warnings"}
    assert all(e["code"] == "missing_category" for e in res["errors"])
    normalize_cat(capsys, fx)
    rc, res, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "brain/cat")
    assert rc == 1 and res["errors"] == [{"path": "misc/notes.md", "code": "missing_category"}]
    m = tmp_path / "m.yaml"
    m.write_text('rules:\n  - "misc/**": produit\n')
    normalize_cat(capsys, fx, "brain/all", "--map", m)
    rc, res, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "brain/all")
    assert rc == 0 and res["errors"] == [] and len(res["warnings"]) == 1
    rc, res, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "brain/all", "--strict")
    assert rc == 1
    readme = git_bytes(fx.path, "show", "brain/all:README.md").replace(b"category: usage", b"category: roadmap")
    fx_branch(fx.path, "roadmap", "brain/all", {"README.md": readme})
    rc, res, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "roadmap")
    assert rc == 1 and res["errors"][0] == {"path": "README.md", "code": "invalid_category"}
    rc, _, err = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "unknown-ref")
    assert rc == 2 and json.loads(err)["code"] == "brain_ref_unresolved"


def test_ac5_lint_ignores_uncommitted_change(capsys, fx):
    rc1, r1, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "main")
    write(fx.path, "per-repo/a.md", b"---\ncategory: repo\n---\n# A\n")
    rc2, r2, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "main")
    assert (rc1, r1) == (rc2, r2)
    rc3, r3, _ = run(capsys, "brain", "lint", "--repo", fx.path)      # default HEAD = main here
    assert r3 == r1


def test_lint_frontmatter_unreadable(capsys, fx):
    fx_branch(fx.path, "broken", "main", {"per-repo/a.md": b"---\nowner: x\n# no closing line\n",
                                          "per-repo/c.md": b"---\ncategory: repo\ncategory: usage\n---\n"})
    rc, res, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "broken")
    codes = {e["path"]: e["code"] for e in res["errors"]}
    assert rc == 1
    assert codes["per-repo/a.md"] == "frontmatter_unreadable" and codes["per-repo/c.md"] == "frontmatter_unreadable"
    rc, rep, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--base", "broken", "--dry-run")
    assert "per-repo/a.md" in rep["invalid"] and "per-repo/c.md" in rep["invalid"]


def test_lint_text_format(capsys, fx):
    rc, out, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "main", "--format", "text")
    lines = out.strip().splitlines()
    assert rc == 1
    assert "error README.md: missing_category" in lines
    assert "warning per-repo/a.md:5: broken md-link -> missing.md" in lines
    assert lines[-1] == f"lint: 6 notes, 6 errors, 1 warnings ({fx.c2})"


# --- AC6: snapshot reads the commit, never the working copy ---

def test_ac6_snapshot_exact_tree_from_commit(capsys, fx, tmp_path):
    s2 = tmp_path / "s2"
    rc, res, err = run(capsys, "brain", "snapshot", "--repo", fx.path, "--ref", "main", "--out", s2)
    assert rc == 0, err
    assert len(list(s2.rglob("*.md"))) == 6
    assert not (s2 / "new.md").exists() and not (s2 / "secret.md").exists()
    assert not (s2 / ".claude").exists() and not (s2 / "hooks").exists()
    committed = git_bytes(fx.path, "show", "main:per-repo/a.md")
    assert (s2 / "per-repo/a.md").read_bytes() == committed
    assert committed != (fx.path / "per-repo/a.md").read_bytes()
    assert (s2 / "per-repo/c.md").read_bytes() == C_CRLF
    manifest = json.loads((s2 / "manifest.json").read_text())
    assert manifest["commit"] == git(fx.path, "rev-parse", "main")
    assert res == {"repo_ref": "main", "commit": fx.c2, "out": str(s2), "files": 6, "links": 4,
                   "broken_links": 1}
    assert (s2 / "links.json").read_text().endswith("]\n")


def test_ac6_snapshot_refuses_non_empty_out(capsys, fx, tmp_path):
    s2 = tmp_path / "s2"
    assert run(capsys, "brain", "snapshot", "--repo", fx.path, "--ref", "main", "--out", s2)[0] == 0
    rc, _, err = run(capsys, "brain", "snapshot", "--repo", fx.path, "--ref", "main", "--out", s2)
    assert rc == 2 and json.loads(err)["code"] == "out_not_empty"


def test_ac6_snapshot_v1_has_b_not_b2(capsys, fx, tmp_path):
    s1 = tmp_path / "s1"
    rc, res, _ = run(capsys, "brain", "snapshot", "--repo", fx.path, "--ref", "v1", "--out", s1)
    assert rc == 0 and res["commit"] == fx.c1
    assert (s1 / "per-repo/b.md").exists() and not (s1 / "per-repo/b2.md").exists()


# --- AC7: exact manifest.json ---

def test_ac7_manifest_blob_and_last_commit(capsys, fx, tmp_path):
    side = fx_add_commit(fx.path, "main", {"misc/notes.md": b"# Notes\nside\n"}, message="side")
    merge = fx_add_commit(fx.path, "main", {"misc/notes.md": b"# Notes\nside\n"}, message="merge",
                          extra_parents=(side,), ref="refs/heads/merged")
    for ref in ("main", "merged"):
        out = tmp_path / f"s-{ref}"
        rc, _, _ = run(capsys, "brain", "snapshot", "--repo", fx.path, "--ref", ref, "--out", out)
        man = json.loads((out / "manifest.json").read_text())
        assert rc == 0 and len(man["files"]) == 6
        assert set(man) == {"repo_ref", "commit", "date", "files"}
        assert man["date"] == git(fx.path, "log", "-1", "--format=%cI", ref)
        for f in man["files"]:
            assert set(f) == {"path", "category", "blob", "last_commit", "date"}
            assert f["blob"] == git(fx.path, "rev-parse", f"{ref}:{f['path']}")
            assert f["last_commit"] == git(fx.path, "log", "-1", "--format=%H", ref, "--", f["path"])
            assert f["date"] == git(fx.path, "log", "-1", "--format=%cI", ref, "--", f["path"])
        if ref == "main":
            by = {f["path"]: f for f in man["files"]}
            assert by["per-repo/a.md"]["last_commit"] == fx.c2
            assert by["per-repo/c.md"]["last_commit"] == fx.c1
    assert merge


def test_ac7_category_null_then_filled(capsys, fx, tmp_path):
    from sdlc.brain import build_manifest
    assert [f["category"] for f in build_manifest(fx.path, "main")["files"]] == [None] * 6
    normalize_cat(capsys, fx)
    cats = [f["category"] for f in build_manifest(fx.path, "brain/cat")["files"]]
    assert sum(c is not None for c in cats) == 5


# --- AC8: links.json ---

def _links(capsys, fx, tmp_path, ref="main"):
    out = tmp_path / f"links-{ref.replace('/', '-')}"
    assert run(capsys, "brain", "snapshot", "--repo", fx.path, "--ref", ref, "--out", out)[0] == 0
    return json.loads((out / "links.json").read_text())


def test_ac8_links_kinds_and_resolution(capsys, fx, tmp_path):
    links = _links(capsys, fx, tmp_path)
    assert len(links) == 4
    kinds: dict[str, int] = {}
    for link in links:
        kinds[link["kind"]] = kinds.get(link["kind"], 0) + 1
        assert set(link) == {"from", "to", "target", "kind", "line", "resolved"}
    assert kinds == {"external": 1, "md-link": 2, "path-mention": 1}
    unresolved = [link for link in links if link["resolved"] is False]
    assert len(unresolved) == 1 and unresolved[0]["to"] == "per-repo/missing.md"
    assert not any(link["to"].startswith("../") for link in links)
    ext = next(link for link in links if link["kind"] == "external")
    assert ext["to"] == "https://example.org" and ext["resolved"] is None
    assert links == sorted(links, key=lambda x: (x["from"], x["line"]))


def test_ac8_repo_name_prefix_normalized(capsys, fx, tmp_path):
    clone = fx_clone(fx.path, tmp_path / "renamed-clone")         # name only known via remote.origin.url
    from sdlc.brain import extract_links
    mention = next(link for link in extract_links(clone, "origin/main") if link["kind"] == "path-mention")
    assert mention["to"] == "per-repo/a.md" and mention["resolved"] is True
    assert mention["target"] == "../fx-brain/per-repo/a.md"


def test_ac8_target_and_line(capsys, fx, tmp_path):
    links = _links(capsys, fx, tmp_path)
    assert all(isinstance(link["line"], int) and link["line"] >= 1 and link["target"] for link in links)
    missing = next(link for link in links if link["to"] == "per-repo/missing.md")
    main_a = git(fx.path, "show", "main:per-repo/a.md").splitlines()
    assert missing["line"] == next(i for i, line in enumerate(main_a, 1) if "missing.md" in line)
    assert missing["target"] == "missing.md"
    arch = next(link for link in links if link["kind"] == "md-link" and link["resolved"])
    assert (arch["from"], arch["to"], arch["line"]) == ("README.md", "technical/architecture.md", 3)
    # line numbers count the front matter lines
    normalize_cat(capsys, fx)
    shifted = next(link for link in _links(capsys, fx, tmp_path, "brain/cat") if link["to"] == "per-repo/missing.md")
    assert shifted["line"] == missing["line"] + 3


def test_ac8_lint_warnings_equal_unresolved_links(capsys, fx, tmp_path):
    links = _links(capsys, fx, tmp_path)
    _, res, _ = run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "main")
    _, rep, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run")
    unresolved = [{k: link[k] for k in ("from", "to", "target", "kind", "line")}
                  for link in links if link["resolved"] is False]
    assert res["warnings"] == unresolved == rep["broken_links"]


def test_links_ignore_anchor_image_non_md():
    text = (b"[a](#section) ![img](pic.md) [s](run.sh) [p](page.md#part) [u](<my%20note.md>)\n"
            b"[ref]: other.md\n[w]: https://x.org/y.md\n`code/z.md` and z.mdx and https://h/q.md\n"
            b"mail mailto:someone@example.org\n")
    notes = {"page.md", "my note.md", "other.md", "code/z.md"}
    links = note_links("n.md", text, notes, frozenset({"b"}))
    got = [(link["kind"], link["to"], link["resolved"]) for link in links]
    assert got == [
        ("md-link", "page.md", True),
        ("md-link", "my note.md", True),
        ("md-link", "other.md", True),
        ("external", "https://x.org/y.md", None),
        ("path-mention", "code/z.md", True),
        ("external", "https://h/q.md", None),
        ("external", "mailto:someone@example.org", None),
    ]


def test_links_out_of_root_kept_broken():
    text = b"[c](../code-repo/docs/features/f.md)\n[s](../b/x.md)\nsee ../code-repo/y.md\n"
    links = note_links("n.md", text, {"x.md"}, frozenset({"b"}))
    assert [(link["to"], link["resolved"]) for link in links] == [
        ("../code-repo/docs/features/f.md", False), ("x.md", True), ("../code-repo/y.md", False)]


def test_path_mention_falls_back_to_root():
    links = note_links("per-repo/x.md", b"see README.md and per-repo/y.md\n",
                       {"README.md", "per-repo/y.md", "per-repo/x.md"}, frozenset())
    assert [(link["to"], link["resolved"]) for link in links] == [("README.md", True), ("per-repo/y.md", True)]


# --- AC9: diff with and without git ---

def _statuses(res) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in res["files"]:
        out[f["status"]] = out.get(f["status"], 0) + 1
    return out


def test_ac9_diff_git_rename_modify_unchanged(capsys, fx):
    rc, res, _ = run(capsys, "brain", "diff", "--repo", fx.path, "v1", "main")
    assert rc == 0 and _statuses(res) == {"modified": 1, "renamed": 1, "unchanged": 4}
    by = {f["path"]: f for f in res["files"]}
    assert by["per-repo/b2.md"] == {"path": "per-repo/b2.md", "status": "renamed", "old_path": "per-repo/b.md"}
    assert by["per-repo/a.md"]["status"] == "modified"
    assert all("old_path" not in f for f in res["files"] if f["status"] != "renamed")
    assert (res["from"], res["to"]) == (fx.c1, fx.c2)
    assert [f["path"] for f in res["files"]] == sorted(by)


def test_ac9_git_and_manifest_modes_identical(capsys, fx, tmp_path):
    for ref, name in (("v1", "s1"), ("main", "s2")):
        assert run(capsys, "brain", "snapshot", "--repo", fx.path, "--ref", ref, "--out", tmp_path / name)[0] == 0
    _, g, _ = run(capsys, "brain", "diff", "--repo", fx.path, "v1", "main")
    _, m, _ = run(capsys, "brain", "diff", "--manifests", tmp_path / "s1/manifest.json", tmp_path / "s2/manifest.json")
    assert g == m


def test_ac9_added_deleted(capsys, fx):
    c3 = fx_add_commit(fx.path, "main", {"x.md": b"# brand new\n", "misc/notes.md": None})
    rc, res, _ = run(capsys, "brain", "diff", "--repo", fx.path, "main", c3)
    assert rc == 0
    st = _statuses(res)
    assert st["added"] == 1 and st["deleted"] == 1


def test_ac9_manifest_mode_outside_git(capsys, fx, tmp_path, monkeypatch):
    for ref, name in (("v1", "s1"), ("main", "s2")):
        run(capsys, "brain", "snapshot", "--repo", fx.path, "--ref", ref, "--out", tmp_path / name)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    rc, res, _ = run(capsys, "brain", "diff", "--manifests", tmp_path / "s1/manifest.json",
                     tmp_path / "s2/manifest.json")
    assert rc == 0 and _statuses(res) == {"modified": 1, "renamed": 1, "unchanged": 4}
    (outside / "bad.json").write_text("{}")
    rc, _, err = run(capsys, "brain", "diff", "--manifests", outside / "bad.json", tmp_path / "s2/manifest.json")
    assert rc == 2 and json.loads(err)["code"] == "manifest_invalid"


def test_diff_usage_errors(capsys, fx):
    with pytest.raises(SystemExit) as ei:
        cli.main(["brain", "diff", "--repo", str(fx.path), "main"])
    assert ei.value.code == 2
    with pytest.raises(SystemExit) as ei:
        cli.main(["brain", "diff", "--repo", str(fx.path), "--manifests", "a", "b"])
    assert ei.value.code == 2


def test_diff_rename_with_modification_is_deleted_added():
    from sdlc.brain import diff_files
    files = diff_files([{"path": "a.md", "blob": "1"}], [{"path": "b.md", "blob": "2"}])
    assert files == [{"path": "a.md", "status": "deleted"}, {"path": "b.md", "status": "added"}]


# --- AC10: history follows renames ---

def test_ac10_history_follows_rename(capsys, fx):
    rc, res, _ = run(capsys, "brain", "history", "--repo", fx.path, "per-repo/b2.md")
    assert rc == 0 and len(res) == 2
    assert res[0]["path"] == "per-repo/b2.md" and res[1]["path"] == "per-repo/b.md"
    assert res[0]["commit"] == git(fx.path, "rev-parse", "main") and res[1]["commit"] == fx.c1
    assert set(res[0]) == {"author", "commit", "date", "message", "path"}
    assert res[0]["author"] == "t" and res[0]["message"] == "C2"
    rc, res, _ = run(capsys, "brain", "history", "--repo", fx.path, "per-repo/b.md", "--ref", "v1")
    assert rc == 0 and [e["commit"] for e in res] == [fx.c1]


def test_ac10_history_unknown_exit_2(capsys, fx):
    rc, _, err = run(capsys, "brain", "history", "--repo", fx.path, "nope.md")
    assert rc == 2 and json.loads(err)["code"] == "note_not_found"


# --- AC15: brain in a sub-folder of a repository ---

def test_ac15_subfolder_brain_paths_relative(capsys, tmp_path):
    host = make_fx_host(tmp_path)
    sd = tmp_path / "sd"
    rc, _, err = run(capsys, "brain", "snapshot", "--repo", host / "docs", "--ref", "main", "--out", sd)
    assert rc == 0, err
    man = json.loads((sd / "manifest.json").read_text())
    assert sorted(f["path"] for f in man["files"]) == ["README.md", "per-repo/a.md"]
    assert (sd / "per-repo/a.md").exists() and not (sd / "src").exists()
    rc, rep, _ = run(capsys, "brain", "normalize", "--repo", host / "docs", "--dry-run")
    assert rc == 0 and rep["counts"] == {"usage": 1, "repo": 1}


def test_ac15_subfolder_blob_and_config_commit(capsys, tmp_path, monkeypatch):
    host = make_fx_host(tmp_path)
    from sdlc.brain import build_manifest
    by = {f["path"]: f for f in build_manifest(host / "docs", "main")["files"]}
    assert by["per-repo/a.md"]["blob"] == git(host, "rev-parse", "main:docs/per-repo/a.md")
    assert by["per-repo/a.md"]["last_commit"] == git(host, "rev-parse", "main")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "sdlc.config.json").write_text(json.dumps({"prefix": "DEMO", "brain": str(host / "docs")}))
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    rc, cfg, _ = run(capsys, "config")
    assert rc == 0 and cfg["brainCommit"] == git(host, "rev-parse", "main")
    rc, hist, _ = run(capsys, "brain", "history", "--repo", host / "docs", "per-repo/a.md")
    assert rc == 0 and hist[0]["path"] == "per-repo/a.md"


def test_ac15_subfolder_link_to_readme(tmp_path):
    host = make_fx_host(tmp_path)
    from sdlc.brain import extract_links
    links = extract_links(host / "docs", "main")
    assert [(link["from"], link["to"], link["resolved"]) for link in links] == [("per-repo/a.md", "README.md", True)]


# --- library API, stdlib only, git whitelist ---

def test_public_api_without_cli(fx):
    import sdlc.brain as b
    rr = b.resolve_brain_ref(fx.path)
    assert (rr.ref, rr.commit, rr.source) == ("main", fx.c2, "local")
    notes = b.list_notes(fx.path, rr.commit)
    assert [n.path for n in notes] == ["README.md", "misc/notes.md", "per-repo/a.md", "per-repo/b2.md",
                                       "per-repo/c.md", "technical/architecture.md"]
    assert all(n.blob == git(fx.path, "rev-parse", f"main:{n.path}") for n in notes)
    data = b.read_notes(fx.path, rr.commit, ["per-repo/a.md", "per-repo/c.md"])
    assert data == {"per-repo/a.md": A_C2, "per-repo/c.md": C_CRLF}
    with pytest.raises(b.BrainError) as ei:
        b.read_notes(fx.path, rr.commit, ["nope.md"])
    assert ei.value.code == "note_not_found"
    assert len(b.extract_links(fx.path, rr.commit)) == 4
    res = b.lint(fx.path, "main")
    assert res["exit"] == 1 and len(res["errors"]) == 6
    m1, m2 = b.build_manifest(fx.path, "v1"), b.build_manifest(fx.path, "main")
    assert {f["status"] for f in b.diff_manifests(m1, m2)["files"]} == {"modified", "renamed", "unchanged"}
    assert b.effective_excludes(fx.path, "main", excludes=["x/"]) == (".claude/**", "hooks/**", "x/")
    assert b.is_excluded("drafts/a.md", ["drafts/"]) and not b.is_excluded("a.md", b.DEFAULT_EXCLUDES)
    assert b.READER_PROFILE == {"produit": "fonctionnel", "usage": "mixte", "archi": "technique",
                                "repo": "technique", "config": "technique", "cicd": "technique",
                                "exploit": "technique", "observ": "technique"}
    assert b.CATEGORIES == ("produit", "usage", "archi", "repo", "config", "cicd", "exploit", "observ")
    with pytest.raises(b.BrainNotGit):
        b.list_notes(fx.path.parent, "HEAD")
    with pytest.raises(b.BrainRefUnresolved):
        b.resolve_brain_ref(fx.path, "v9")
    for name in ("resolve_brain_ref", "list_notes", "read_notes", "extract_links", "lint", "build_manifest",
                 "snapshot", "diff_refs", "diff_manifests", "history", "normalize", "match_glob",
                 "is_excluded", "parse_mapping", "BrainError", "BrainNotGit", "BrainRefUnresolved",
                 "CATEGORIES", "READER_PROFILE", "DEFAULT_EXCLUDES"):
        assert name in b.__all__


PKG = Path(__file__).resolve().parents[1] / "sdlc" / "brain"


def test_brain_stdlib_only():
    for py in PKG.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots = [node.module.split(".")[0]]
            else:
                continue
            for root in roots:
                assert root in sys.stdlib_module_names or root == "__future__", f"{py.name}: {root}"


def test_no_print_or_exit_outside_cli():
    for py in PKG.glob("*.py"):
        if py.name == "cli.py":
            continue
        src = py.read_text(encoding="utf-8")
        assert "print(" not in src and "sys.exit" not in src, py.name


def test_no_git_network_or_worktree_subcommands(capsys, fx, tmp_path, monkeypatch):
    seen: list[str] = []
    real_run = subprocess.run

    def spy(cmd, *a, **k):
        if isinstance(cmd, list) and cmd and cmd[0] == "git":
            i = cmd.index("-C") + 2
            while cmd[i].startswith("-"):
                i += 1
            seen.append(cmd[i])
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(gitio.subprocess, "run", spy)
    m = tmp_path / "m.yaml"
    m.write_text('rules:\n  - "misc/**": produit\n')
    run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run", "--report", tmp_path / "r.md")
    run(capsys, "brain", "normalize", "--repo", fx.path, "--branch", "brain/wl", "--map", m)
    run(capsys, "brain", "normalize", "--repo", fx.path, "--branch", "main")
    run(capsys, "brain", "lint", "--repo", fx.path, "--ref", "brain/wl", "--format", "text")
    run(capsys, "brain", "snapshot", "--repo", fx.path, "--ref", "v1", "--out", tmp_path / "wl")
    run(capsys, "brain", "diff", "--repo", fx.path, "v1", "main")
    run(capsys, "brain", "history", "--repo", fx.path, "per-repo/b2.md")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "sdlc.config.json").write_text(json.dumps({"prefix": "DEMO", "brain": str(fx.path)}))
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    run(capsys, "config")
    assert seen
    assert set(seen) <= gitio.ALLOWED_SUBCOMMANDS, set(seen) - gitio.ALLOWED_SUBCOMMANDS
    forbidden = {"fetch", "pull", "push", "clone", "checkout", "switch", "reset", "clean", "stash", "merge",
                 "rebase", "worktree", "archive", "add", "commit", "status", "remote", "show", "diff"}
    assert not set(seen) & forbidden
    with pytest.raises(gitio.BrainError):
        gitio.run_git(fx.path, ["fetch"])
    with pytest.raises(gitio.BrainError):
        gitio.run_git(fx.path, ["config", "user.name", "x"])


def test_normalize_report_markdown(capsys, fx, tmp_path):
    report = tmp_path / "report.md"
    rc, rep, _ = run(capsys, "brain", "normalize", "--repo", fx.path, "--dry-run", "--report", report)
    text = report.read_text()
    assert rc == 0
    for section in ("## Distribution", "## Deduced (5)", "## Already classified (0)", "## Invalid (0)",
                    "## Undecidable (1)", f"## Broken links ({len(rep['broken_links'])})"):
        assert section in text
    assert "`misc/notes.md`" in text and "missing.md" in text


def test_brain_not_found_and_not_git(capsys, tmp_path):
    rc, _, err = run(capsys, "brain", "lint", "--repo", tmp_path / "absent")
    assert rc == 2 and json.loads(err)["code"] == "brain_not_found"
    plain = tmp_path / "plain"
    plain.mkdir()
    rc, _, err = run(capsys, "brain", "lint", "--repo", plain)
    assert rc == 2 and json.loads(err)["code"] == "brain_not_git"
