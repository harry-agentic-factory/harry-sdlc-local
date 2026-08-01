"""Items de post-mortem : store append-only (last-wins), filtres, statuer, convertir (dette/Brain)."""
import json

import pytest

from sdlc import cli
from sdlc.post_mortem import PostMortemStore
from sdlc.service import Sdlc
from sdlc.workspace import Workspace


def _run(capsys, argv, workspace, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(workspace))
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out) if out.strip() else {}


# --- store : add → list → show ---

def test_add_list_show(tmp_path):
    store = PostMortemStore(tmp_path)
    a = store.add(agent="reviewer", kind="debt", text="fuite potentielle de secret dans le log")
    b = store.add(agent="deployer", kind="incident", text="CD a timeout", epic="E", story="E-1")
    assert a.id == "PM-001" and b.id == "PM-002"          # auto-incrément par projet
    assert a.status == "open" and a.severity == "medium"  # défauts
    assert (tmp_path / "post-mortem.jsonl").exists()       # stockage jsonl
    assert {i.id for i in store.list()} == {"PM-001", "PM-002"}
    assert store.get("PM-002").story == "E-1"


def test_filters(tmp_path):
    store = PostMortemStore(tmp_path)
    store.add(agent="reviewer", kind="debt", text="t1", epic="E1", story="E1-1")
    store.add(agent="deployer", kind="incident", text="t2", epic="E2", story="E2-1")
    store.add(agent="reviewer", kind="security", text="t3", epic="E1")
    assert [i.id for i in store.list(agent="reviewer")] == ["PM-001", "PM-003"]
    assert [i.id for i in store.list(epic="E1")] == ["PM-001", "PM-003"]
    assert [i.id for i in store.list(story="E2-1")] == ["PM-002"]
    assert [i.id for i in store.list(kind="security")] == ["PM-003"]
    assert [i.id for i in store.list(status="open")] == ["PM-001", "PM-002", "PM-003"]


def test_add_validates_kind_and_severity(tmp_path):
    store = PostMortemStore(tmp_path)
    with pytest.raises(ValueError):
        store.add(agent="dev", kind="bogus", text="x")
    with pytest.raises(ValueError):
        store.add(agent="dev", kind="debt", text="x", severity="critical")


# --- reconstruction last-wins après plusieurs status ---

def test_last_wins_reconstruction(tmp_path):
    store = PostMortemStore(tmp_path)
    store.add(agent="dev", kind="learning", text="apprentissage", now="2026-07-24T10:00:00Z")
    store.set_status("PM-001", "triaged", now="2026-07-24T11:00:00Z")
    store.set_status("PM-001", "wontfix", now="2026-07-24T12:00:00Z")
    # append-only : 3 snapshots, mais l'état courant = le dernier
    assert len(store._snapshots()) == 3
    cur = store.get("PM-001")
    assert cur.status == "wontfix"
    assert cur.created_at == "2026-07-24T10:00:00Z"   # created_at préservé
    assert cur.updated_at == "2026-07-24T12:00:00Z"   # updated_at bumpé
    assert len(store.list()) == 1                      # toujours 1 item logique


# --- to-ticket : crée une story de dette + status=ticketed + target ---

def test_to_ticket(tmp_path):
    ws = Workspace(tmp_path)
    ws.create_epic("DEBT", "dette")
    store = PostMortemStore(tmp_path)
    store.add(agent="reviewer", kind="debt", text="RBAC à refondre côté back-tenant\nligne 2 ignorée")
    res = store.to_ticket("PM-001", Sdlc(ws), debt_epic="DEBT", repos=["back-tenant"])
    assert res == {"id": "PM-001", "ticket": "DEBT-1"}
    story = ws.load("DEBT-1")
    assert story.epic == "DEBT" and story.repos == ["back-tenant"]
    assert story.title == "RBAC à refondre côté back-tenant"   # 1re ligne du text
    item = store.get("PM-001")
    assert item.status == "ticketed" and item.target == "DEBT-1"


def test_to_ticket_creates_epic_if_absent(tmp_path):
    ws = Workspace(tmp_path)
    store = PostMortemStore(tmp_path)
    store.add(agent="dev", kind="debt", text="dette isolée")
    res = store.to_ticket("PM-001", Sdlc(ws), debt_epic="DEBT")
    assert res["ticket"] == "DEBT-1"
    assert (tmp_path / "DEBT").exists()


# --- to-brain : status=brain + suggestion ---

def test_to_brain(tmp_path):
    store = PostMortemStore(tmp_path)
    store.add(agent="human", kind="brain", text="documenter le flow QR", epic="E")
    res = store.to_brain("PM-001")
    assert res["status"] == "brain"
    assert "brain-update-propale.md" in res["suggestion"] and "PM-001" in res["suggestion"]
    item = store.get("PM-001")
    assert item.status == "brain" and item.target == "brain-propale"


# --- surface CLI (bout en bout, sortie JSON) ---

def test_cli_add_list_show_status(tmp_path, capsys, monkeypatch):
    rc, out = _run(capsys, ["pm", "add", "--agent", "reviewer", "--kind", "security",
                            "--text", "creds en clair", "--epic", "E"], tmp_path, monkeypatch)
    assert rc == 0 and out["id"] == "PM-001"
    rc, out = _run(capsys, ["pm", "list", "--kind", "security"], tmp_path, monkeypatch)
    assert rc == 0 and [i["id"] for i in out["items"]] == ["PM-001"]
    rc, out = _run(capsys, ["pm", "show", "PM-001"], tmp_path, monkeypatch)
    assert out["agent"] == "reviewer" and out["epic"] == "E"
    rc, out = _run(capsys, ["pm", "status", "PM-001", "triaged"], tmp_path, monkeypatch)
    assert rc == 0 and out["status"] == "triaged"


def test_cli_to_ticket(tmp_path, capsys, monkeypatch):
    Workspace(tmp_path).create_epic("DEBT", "dette")
    _run(capsys, ["pm", "add", "--agent", "fixer", "--kind", "debt",
                  "--text", "nettoyer KeycloakAdminService"], tmp_path, monkeypatch)
    rc, out = _run(capsys, ["pm", "to-ticket", "PM-001", "--epic", "DEBT",
                            "--repos", "back-tenant"], tmp_path, monkeypatch)
    assert rc == 0 and out == {"id": "PM-001", "ticket": "DEBT-1"}
    rc, out = _run(capsys, ["pm", "show", "PM-001"], tmp_path, monkeypatch)
    assert out["status"] == "ticketed" and out["target"] == "DEBT-1"


def test_cli_to_brain(tmp_path, capsys, monkeypatch):
    _run(capsys, ["pm", "add", "--agent", "human", "--kind", "brain",
                  "--text", "capitaliser le learning"], tmp_path, monkeypatch)
    rc, out = _run(capsys, ["pm", "to-brain", "PM-001"], tmp_path, monkeypatch)
    assert rc == 0 and out["status"] == "brain" and "suggestion" in out
