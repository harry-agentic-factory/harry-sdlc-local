"""`brainRef` / `brainCommit` / `brainRefFrom` in `sdlc config` (AC11) and non-regression (AC14)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdlc import cli
from sdlc.brain import resolve_brain_ref
from sdlc.config import load_config, resolved_manifest
from test_brain import fx_add_commit, fx_clone, git, make_fx_brain, make_fx_master, run

BRAIN_KEYS = {"brainRef", "brainCommit", "brainRefFrom"}
MANIFEST_KEYS = {"prefix", "workspace", "reposRoot", "repos", "roles", "stacks", "brain", "refBranch", "deploy",
                 "recette", "guidelines", "skillsByRepo", "credentials", "permissions", "escalation", "board",
                 "schemaVersion", "infra", "tracker"}  # infra/tracker: trunk (investigate)


def project(tmp_path: Path, monkeypatch, name: str = "ws", **cfg) -> Path:
    ws = tmp_path / name
    ws.mkdir()
    (ws / "sdlc.config.json").write_text(json.dumps({"prefix": "DEMO", **cfg}))
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    return ws


def config(capsys):
    rc, out, err = run(capsys, "--project", "DEMO", "config")
    warnings = [json.loads(line) for line in err.splitlines() if line.strip()]
    return rc, out, warnings


# --- AC11: brainRef resolved ---

def test_ac11_brainref_tag(capsys, tmp_path, monkeypatch):
    fx = make_fx_brain(tmp_path)
    project(tmp_path, monkeypatch, brain=str(fx.path), brainRef="v1")
    rc, cfg, warnings = config(capsys)
    assert rc == 0 and warnings == []
    assert cfg["brainRef"] == "v1" and cfg["brainRefFrom"] == "tag"
    assert cfg["brainCommit"] == git(fx.path, "rev-parse", "v1^{commit}") == fx.c1


def test_ac11_default_main_local(capsys, tmp_path, monkeypatch):
    fx = make_fx_brain(tmp_path)
    project(tmp_path, monkeypatch, brain=str(fx.path))
    rc, cfg, _ = config(capsys)
    assert rc == 0
    assert (cfg["brainRef"], cfg["brainCommit"], cfg["brainRefFrom"]) == ("main", fx.c2, "local")


def test_ac11_unresolved_warns_exit_0(capsys, tmp_path, monkeypatch):
    fx = make_fx_brain(tmp_path)
    project(tmp_path, monkeypatch, brain=str(fx.path), brainRef="v9")
    rc, cfg, warnings = config(capsys)
    assert rc == 0
    assert (cfg["brainRef"], cfg["brainCommit"], cfg["brainRefFrom"]) == ("v9", None, None)
    assert [w["warning"] for w in warnings] == ["brain_ref_unresolved"]
    assert "warning" not in cfg


def _clone_with_c3(tmp_path):
    fx = make_fx_brain(tmp_path)
    clone = fx_clone(fx.path, tmp_path / "fx-clone")
    c3 = fx_add_commit(fx.path, "main", {"extra.md": b"# C3\n"}, ref="refs/heads/main", message="C3")
    git(clone, "fetch", "-q")
    return fx, clone, c3


def test_ac11_origin_first(capsys, tmp_path, monkeypatch):
    fx, clone, c3 = _clone_with_c3(tmp_path)
    assert git(clone, "rev-parse", "main") == fx.c2            # local main stays at C2
    project(tmp_path, monkeypatch, brain=str(clone))
    rc, cfg, _ = config(capsys)
    assert rc == 0 and cfg["brainCommit"] == c3 and cfg["brainRefFrom"] == "origin"


def test_ac11_no_implicit_fetch(capsys, tmp_path, monkeypatch):
    fx, clone, c3 = _clone_with_c3(tmp_path)
    c4 = fx_add_commit(fx.path, "main", {"extra.md": b"# C4\n"}, ref="refs/heads/main", message="C4")
    project(tmp_path, monkeypatch, brain=str(clone))
    rc, cfg, _ = config(capsys)
    assert rc == 0 and cfg["brainCommit"] == c3 != c4
    assert git(clone, "rev-parse", "origin/main") == c3


def test_ac11_default_master(capsys, tmp_path, monkeypatch):
    repo = make_fx_master(tmp_path)
    project(tmp_path, monkeypatch, brain=str(repo))
    rc, cfg, _ = config(capsys)
    assert rc == 0
    assert cfg["brainRef"] == "master" and cfg["brainCommit"] == git(repo, "rev-parse", "master")
    assert cfg["brainRefFrom"] == "local"


def test_ac11_not_git_warns_and_snapshot_exit_2(capsys, tmp_path, monkeypatch):
    plain = tmp_path / "plain-brain"
    plain.mkdir()
    (plain / "README.md").write_text("# not versioned\n")
    project(tmp_path, monkeypatch, brain=str(plain))
    rc, cfg, warnings = config(capsys)
    assert rc == 0 and cfg["brainCommit"] is None and cfg["brainRefFrom"] is None
    assert [w["warning"] for w in warnings] == ["brain_not_git"]
    rc, _, err = run(capsys, "brain", "snapshot", "--repo", plain, "--ref", "main", "--out", tmp_path / "o")
    assert rc == 2 and json.loads(err)["code"] == "brain_not_git"


def test_ac11_no_brain_three_null_keys(capsys, tmp_path, monkeypatch):
    project(tmp_path, monkeypatch)
    rc, cfg, warnings = config(capsys)
    assert rc == 0 and warnings == []
    assert {k: cfg[k] for k in BRAIN_KEYS} == dict.fromkeys(BRAIN_KEYS)


def test_resolve_head_is_local(tmp_path):
    fx, clone, c3 = _clone_with_c3(tmp_path)
    rr = resolve_brain_ref(clone, "HEAD")
    assert (rr.ref, rr.commit, rr.source) == ("HEAD", fx.c2, "local")
    rr = resolve_brain_ref(clone, fx.c1)
    assert (rr.commit, rr.source) == (fx.c1, "sha")
    rr = resolve_brain_ref(clone, "origin/main")
    assert (rr.commit, rr.source) == (c3, "sha")


def test_resolve_order_origin_local_tag(tmp_path):
    fx = make_fx_brain(tmp_path)
    git(fx.path, "branch", "v1", fx.c2)                  # a branch named like the tag wins over it
    rr = resolve_brain_ref(fx.path, "v1")
    assert (rr.commit, rr.source) == (fx.c2, "local")


# --- AC14: engine non-regression ---

def test_ac14_resolved_manifest_default_keys_unchanged(tmp_path, monkeypatch):
    fx = make_fx_brain(tmp_path)
    ws = project(tmp_path, monkeypatch, brain=str(fx.path), brainRef="v1")
    assert set(resolved_manifest(workspace=ws)) == MANIFEST_KEYS
    assert set(resolved_manifest("DEMO")) == MANIFEST_KEYS


def test_ac14_config_adds_only_three_keys(capsys, tmp_path, monkeypatch):
    fx = make_fx_brain(tmp_path)
    ws = project(tmp_path, monkeypatch, brain=str(fx.path))
    rc, cfg, _ = config(capsys)
    assert rc == 0 and set(cfg) == MANIFEST_KEYS | BRAIN_KEYS
    assert {k: v for k, v in cfg.items() if k not in BRAIN_KEYS} == resolved_manifest(workspace=ws)


def test_ac14_raw_config_unchanged(capsys, tmp_path, monkeypatch):
    fx = make_fx_brain(tmp_path)
    ws = project(tmp_path, monkeypatch, brain=str(fx.path), brainRef="v1")
    rc, raw, _ = run(capsys, "--project", "DEMO", "config", "--raw")
    assert rc == 0 and raw == load_config(ws)
    assert raw["brainRef"] == "v1" and "brainCommit" not in raw


def test_ac14_help_lists_brain(capsys):
    with pytest.raises(SystemExit) as ei:
        cli.main(["--help"])
    assert ei.value.code == 0
    assert "brain" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["brain", "--help"])
    out = capsys.readouterr().out
    for sub in ("normalize", "lint", "snapshot", "diff", "history"):
        assert sub in out


def test_ac14_existing_commands_still_json(capsys, tmp_path, monkeypatch):
    project(tmp_path, monkeypatch)
    rc, out, _ = run(capsys, "--project", "DEMO", "create-epic", "DEMO-E", "Epic")
    assert rc == 0 and out == {"epic": "DEMO-E", "created": True}
    rc, _, err = run(capsys, "--project", "DEMO", "get", "DEMO-E-404")
    assert rc == 1 and "error" in json.loads(err)
