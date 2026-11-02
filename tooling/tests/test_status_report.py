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


# --- engine 0.8.3: fixed deliverable sections --------------------------------------------------------------------

def test_epic_scaffolds_carry_the_fixed_sections_in_order(tmp_path):
    import re
    from pathlib import Path

    from sdlc.workspace import DELIVERABLE_SECTIONS, Workspace

    d = Workspace(tmp_path).create_epic("E-1", "Titre")
    for name in ("prd.md", "refine.md"):
        text = (d / name).read_text()
        assert len(re.findall(r"(?m)^# ", text)) == 1, name
        assert re.findall(r"(?m)^## (.+)$", text) == list(DELIVERABLE_SECTIONS[name]), name
    # the same names as the command templates (one source of truth for the scaffold and the prompts)
    commands = Path(__file__).resolve().parents[2] / "claude" / "commands"
    for name, command in (("prd.md", "scope"), ("refine.md", "refine"), ("spec-func.md", "spec-func"),
                          ("spec-tech.md", "spec-tech")):
        template = (commands / f"{command}.md").read_text().split("```markdown", 1)[1].split("```", 1)[0]
        assert re.findall(r"(?m)^## (.+)$", template) == expected_sections(name), command


def expected_sections(name: str) -> list[str]:
    """The required sections, plus the conditional ones inserted at their declared index. Stronger than the
    former equality: it pins the POSITION of a conditional section, not only its presence."""
    from sdlc.workspace import CONDITIONAL_SECTIONS, DELIVERABLE_SECTIONS

    out = list(DELIVERABLE_SECTIONS[name])
    for section, index in CONDITIONAL_SECTIONS.get(name, ()):
        out.insert(index, section)
    return out


def test_the_one_pass_command_enumerates_the_same_sections():
    """`full-spec.md` has no ```markdown block: it duplicates the two fixed formats IN PROSE, and nothing used to
    check it. A section added to a format would silently miss that prompt, and the gate would then refuse specs
    written by following it."""
    import re as _re
    from pathlib import Path as _Path

    text = (_Path(__file__).resolve().parents[2] / "claude" / "commands" / "full-spec.md").read_text()
    for name, marker in (("spec-func.md", "spec-func.md` au **format FIXE**"),
                         ("spec-tech.md", "spec-tech.md` au **format FIXE**")):
        prose = text.split(marker, 1)[1].split("set-status", 1)[0]
        cited = set(_re.findall(r"`## ([^`]+)`", prose))
        assert set(expected_sections(name)) - {"Sources"} <= cited | {"Sources"}, name
        for section, _index in __import__("sdlc.workspace", fromlist=["x"]).CONDITIONAL_SECTIONS.get(name, ()):
            assert section in prose, f"{name}: the conditional section is missing from the prose enumeration"


def test_story_stubs_stay_unproduced(tmp_path):
    from sdlc.status_report import _artifacts
    from sdlc.workspace import Ticket, Workspace

    ws = Workspace(tmp_path)
    ws.create_epic("E-1", "Titre")
    d = ws.create_story(Ticket(id="E-1-1", epic="E-1", title="t"))
    assert not any(a["produced"] for a in _artifacts(d))
