"""Rejet routé (gate) : transitions de retour + journal newest-first + surface dans status."""
import json

import pytest

from sdlc import cli
from sdlc.service import Sdlc
from sdlc.status import ALLOWED, InvalidTransition, Status
from sdlc.status_report import build_status
from sdlc.workspace import Ticket, Workspace


def _sdlc(tmp_path, status="recette_ok"):
    ws = Workspace(tmp_path)
    ws.create_epic("E", "e")
    ws.create_story(Ticket(id="E-1", epic="E", title="t", status=status))
    return Sdlc(ws)


# --- state-machine : rejet routé ---

def test_reject_transitions_allowed():
    for src in (Status.REVIEWED, Status.DEPLOYED, Status.RECETTE_OK):
        assert Status.SPEC_TECH in ALLOWED[src]      # ré-analyse
        assert Status.SPEC_FUNC in ALLOWED[src]      # fonctionnel
        assert Status.IMPLEMENTED in ALLOWED[src]    # fixer/recode
    assert Status.ACCEPTED in ALLOWED[Status.RECETTE_OK]   # accept reste possible


# --- façade reject ---

def test_reject_routes_and_journals(tmp_path):
    s = _sdlc(tmp_path)
    res = s.reject("E-1", "spec_tech", "mécanisme service_name déprécié", now="2026-07-22T10:00Z")
    assert res["from"] == "recette_ok" and res["to"] == "spec_tech"
    assert s.get_ticket("E-1")["status"] == "spec_tech"           # routé
    journal = (tmp_path / "E" / "stories" / "E-1" / "journal.md").read_text()
    assert "REJECT  recette_ok → spec_tech" in journal and "déprécié" in journal
    # acceptance.md (preuve) n'est PAS touché par le rejet
    assert "REJECT" not in (tmp_path / "E" / "stories" / "E-1" / "acceptance.md").read_text()


def test_reject_invalid_target_refused(tmp_path):
    s = _sdlc(tmp_path)
    with pytest.raises(InvalidTransition):
        s.reject("E-1", "done", "saut interdit")                  # recette_ok → done interdit


def test_journal_newest_first(tmp_path):
    s = _sdlc(tmp_path)
    s.reject("E-1", "spec_tech", "premier rejet", now="2026-07-22T10:00Z")
    s.set_status("E-1", "implemented"); s.set_status("E-1", "reviewed")
    s.set_status("E-1", "deployed"); s.set_status("E-1", "recette_ok")
    s.reject("E-1", "implemented", "second rejet", now="2026-07-22T12:00Z")
    body = (tmp_path / "E" / "stories" / "E-1" / "journal.md").read_text()
    assert body.index("second rejet") < body.index("premier rejet")   # récent en premier


def test_status_surfaces_last_decision(tmp_path):
    s = _sdlc(tmp_path)
    s.reject("E-1", "spec_tech", "à réétudier via back-hia", now="2026-07-22T10:00Z")
    t = build_status(tmp_path, "E-1")["tickets"][0]
    assert "REJECT" in t["lastDecision"] and "back-hia" in t["lastDecision"]


def test_cli_reject(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path))
    Workspace(tmp_path).create_epic("E", "e")
    Workspace(tmp_path).create_story(Ticket(id="E-1", epic="E", title="t", status="recette_ok"))
    rc = cli.main(["reject", "E-1", "--to", "spec_tech", "--note", "revoir le mécanisme"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["to"] == "spec_tech"
