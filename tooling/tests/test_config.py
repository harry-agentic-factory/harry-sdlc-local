"""Phase 1 — manifest enrichi : résolution des chemins + commande `sdlc config` + migration 0.1→0.2."""
import json

from sdlc import cli
from sdlc.config import load_config, resolve_repos, resolved_manifest
from sdlc.migrations import LATEST_SCHEMA, apply_migrations


def _write_cfg(ws, data):
    (ws / "sdlc.config.json").write_text(json.dumps(data, ensure_ascii=False))


def _run(capsys, argv, workspace, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(workspace))
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out) if out.strip() else {}


# --- résolution repos ---

def test_resolve_repos_list_via_reposroot(tmp_path):
    cfg = {"reposRoot": "/w/hia", "repos": ["back-tenant", "hia-ops"]}
    m = resolve_repos(cfg)
    assert m == {"back-tenant": "/w/hia/back-tenant", "hia-ops": "/w/hia/hia-ops"}


def test_resolve_repos_list_without_reposroot_is_none(tmp_path):
    assert resolve_repos({"repos": ["a", "b"]}) == {"a": None, "b": None}


def test_resolve_repos_map_mixed(tmp_path):
    cfg = {"reposRoot": "/w/hia", "repos": {
        "abs": "/opt/thing", "rel": "sub/dir", "null": None}}
    m = resolve_repos(cfg)
    assert m == {"abs": "/opt/thing", "rel": "/w/hia/sub/dir", "null": "/w/hia/null"}


# --- resolved_manifest defaults + brain ---

def test_resolved_manifest_defaults(tmp_path):
    _write_cfg(tmp_path, {"prefix": "X", "repos": []})
    m = resolved_manifest(workspace=tmp_path)
    assert m["prefix"] == "X"
    assert m["refBranch"] == "main"
    assert m["repos"] == {} and m["roles"] == {} and m["deploy"] == {}
    assert m["brain"] is None
    assert m["credentials"] == {"source": "host"}   # identité par défaut
    assert m["escalation"]["deploy"]  # défaut posé


def test_credentials_source_overridable(tmp_path):
    _write_cfg(tmp_path, {"prefix": "X", "credentials": {"source": "service", "ref": "vault/x"}})
    m = resolved_manifest(workspace=tmp_path)
    assert m["credentials"]["source"] == "service" and m["credentials"]["ref"] == "vault/x"


def test_resolved_manifest_brain_relative_to_reposroot(tmp_path):
    _write_cfg(tmp_path, {"prefix": "X", "reposRoot": "/w/hia", "brain": "hia-brain"})
    assert resolved_manifest(workspace=tmp_path)["brain"] == "/w/hia/hia-brain"


def test_resolved_manifest_brain_absolute(tmp_path):
    _write_cfg(tmp_path, {"prefix": "X", "brain": "/abs/brain"})
    assert resolved_manifest(workspace=tmp_path)["brain"] == "/abs/brain"


# --- CLI `sdlc config` ---

def test_cli_config_resolves(tmp_path, capsys, monkeypatch):
    _write_cfg(tmp_path, {"prefix": "X", "reposRoot": "/w", "repos": ["r1"],
                          "deploy": {"skill": "deploy-jenkins", "ci": "prod/x/ci"}})
    rc, m = _run(capsys, ["config"], tmp_path, monkeypatch)
    assert rc == 0
    assert m["repos"] == {"r1": "/w/r1"}
    assert m["deploy"]["skill"] == "deploy-jenkins"


def test_cli_config_raw(tmp_path, capsys, monkeypatch):
    _write_cfg(tmp_path, {"prefix": "X", "repos": ["r1"]})
    rc, m = _run(capsys, ["config", "--raw"], tmp_path, monkeypatch)
    assert rc == 0 and m["repos"] == ["r1"]  # brut : liste non résolue


# --- migration 0.1.0 -> 0.2.0 ---

def test_migration_list_to_map_and_defaults(tmp_path):
    _write_cfg(tmp_path, {"prefix": "X", "repos": ["a", "b"], "schemaVersion": "0.1.0"})
    res = apply_migrations(tmp_path)
    assert res["schemaVersion"] == "0.2.0" and res["up_to_date"]
    cfg = load_config(tmp_path)
    assert cfg["repos"] == {"a": None, "b": None}
    assert cfg["refBranch"] == "main" and "roles" in cfg and "deploy" in cfg


def test_migration_idempotent(tmp_path):
    _write_cfg(tmp_path, {"prefix": "X", "repos": ["a"], "schemaVersion": "0.1.0"})
    apply_migrations(tmp_path)
    first = load_config(tmp_path)
    res2 = apply_migrations(tmp_path)  # relance
    assert res2["applied"] == [] and res2["up_to_date"]
    assert load_config(tmp_path)["repos"] == first["repos"] == {"a": None}


def test_latest_schema_is_0_2_0():
    assert LATEST_SCHEMA == "0.2.0"
