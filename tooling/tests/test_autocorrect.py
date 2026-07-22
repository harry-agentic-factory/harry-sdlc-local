"""CLI tolérant : devine la sous-commande (préfixe / fuzzy) si la frappe n'est pas exacte."""
import pytest

from sdlc import cli
from sdlc.cli import _resolve_cmd

CMDS = ["create-epic", "create-ticket", "get", "list", "next", "set-status",
        "config", "status", "workspace", "worktree", "worktree-clean"]


def test_prefix_unique():
    assert _resolve_cmd("stat", CMDS)[0] == "status"       # préfixe unique
    assert _resolve_cmd("wo", CMDS)[0] is None             # wo* ambigu (workspace/worktree*)


def test_fuzzy_typo():
    assert _resolve_cmd("statu", CMDS)[0] == "status"
    assert _resolve_cmd("wokspace", CMDS)[0] == "workspace"
    assert _resolve_cmd("config", CMDS)[0] == "config"


def test_ambiguous_suggests():
    resolved, note = _resolve_cmd("s", CMDS)
    assert resolved is None and "voulais-tu" in note       # propose sans exécuter

def test_unknown_no_candidate():
    assert _resolve_cmd("zzzzz", CMDS) == (None, None)


def test_cli_runs_corrected(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path))
    rc = cli.main(["statu"])                                # devine → status, projet vide
    out = capsys.readouterr()
    assert rc == 0 and "« statu » → « status »" in out.err
    import json
    assert json.loads(out.out)["scope"] == "project"


def test_cli_ambiguous_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path))
    assert cli.main(["s"]) == 1                             # ambigu → erreur propre (pas d'exécution)
