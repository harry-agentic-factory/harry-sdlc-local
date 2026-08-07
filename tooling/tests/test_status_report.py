"""`sdlc status` : agrégat état + artefacts + extraction du bloc `## Recap`."""
import pytest

from sdlc.status_report import _recap, build_status
from sdlc.workspace import Ticket, Workspace


def _ws(tmp_path):
    ws = Workspace(tmp_path)
    ws.create_epic("E", "epic")
    ws.create_story(Ticket(id="E-1", epic="E", title="socle", status="recette_ok"))
    ws.create_story(Ticket(id="E-2", epic="E", title="api", deps=["E-1"], status="spec_tech"))
    # recap écrit par l'agent recetteur dans l'artefact
    (tmp_path / "E" / "stories" / "E-1" / "acceptance.md").write_text(
        "## Recap\n- pass 8/8\n- agent: recetteur\n\n## Détail\ncritère 1 …\n")
    return ws


def test_epic_scope_progress_next_blocked_recap(tmp_path):
    _ws(tmp_path)
    res = build_status(tmp_path, "E")
    assert res["scope"] == "epic"
    assert res["progress"] == {"total": 2, "done": 0,
                               "by_status": {"recette_ok": 1, "spec_tech": 1}}
    assert res["next"] == ["E-1"]                       # E-1 pas done → encore actionable
    t1 = next(t for t in res["tickets"] if t["id"] == "E-1")
    t2 = next(t for t in res["tickets"] if t["id"] == "E-2")
    assert t2["blockedBy"] == ["E-1"]                   # bloqué par sa dep non-done
    assert t1["awaiting"]                               # recette_ok → attend accept
    acc = next(a for a in t1["artifacts"] if a["kind"] == "acceptance")
    assert acc["produced"] and "8/8" in acc["recap"]    # artefact réel + recap agent extrait
    stub = next(a for a in t1["artifacts"] if a["kind"] == "demo")
    assert stub["produced"] is False                    # stub scaffoldé ≠ feedback


def test_ticket_and_project_scope(tmp_path):
    _ws(tmp_path)
    assert build_status(tmp_path, "E-1")["scope"] == "ticket"
    assert len(build_status(tmp_path, "E-1")["tickets"]) == 1
    proj = build_status(tmp_path)
    assert proj["scope"] == "project" and proj["progress"]["total"] == 2


def test_unknown_target_raises(tmp_path):
    _ws(tmp_path)
    with pytest.raises(KeyError):
        build_status(tmp_path, "NOPE")


def test_recap_extraction_and_truncation(tmp_path):
    p = tmp_path / "a.md"; p.write_text("intro\n## Recap\n" + "x" * 600 + "\n## Suite\nzzz")
    r = _recap(p)
    assert r.startswith("x") and r.endswith("…") and len(r) <= 501
    q = tmp_path / "b.md"; q.write_text("# pas de recap ici\ntexte")
    assert _recap(q) is None


def test_all_tickets_tolerates_unknown_status_fields(tmp_path):
    """A status.json carrying extra keys (e.g. supersededBy/supersededReason written to record a
    supersede) must not crash the whole board load — regression for the `list`/`status` crash."""
    ws = Workspace(tmp_path)
    ws.create_epic("E", "epic")
    ws.create_story(Ticket(id="E-1", epic="E", title="socle", status="superseded",
                           supersededBy="E-2", supersededReason="absorbed"))
    # simulate a hand-written extra key the model doesn't know at all
    sp = tmp_path / "E" / "stories" / "E-1" / "status.json"
    import json as _json
    data = _json.loads(sp.read_text())
    data["someFutureField"] = {"x": 1}
    sp.write_text(_json.dumps(data))

    tickets = ws.all_tickets()                          # must not raise
    assert [t.id for t in tickets] == ["E-1"]
    assert tickets[0].supersededBy == "E-2"             # known extra fields round-trip
    assert ws.load("E-1").supersededReason == "absorbed"
