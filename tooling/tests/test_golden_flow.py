"""Golden test : déroule un ticket de bout en bout sur un workspace jetable.

Prouve, sans LLM, que le cœur SDLC tient : scaffolding .md, transitions valides,
réhydratation `get_ticket` en un appel, ordre DAG, et miroir board (FakeBoard).
"""
import json

from sdlc import Sdlc, Workspace, FakeBoard


def build(tmp_path):
    sdlc = Sdlc(Workspace(tmp_path), FakeBoard())
    sdlc.create_epic("SAMPLE-TEST", "Feature de démo")
    sdlc.create_ticket("SAMPLE-TEST", "SAMPLE-TEST-2", "socle A", deps=[])
    sdlc.create_ticket("SAMPLE-TEST", "SAMPLE-TEST-3", "socle B", deps=[])
    sdlc.create_ticket("SAMPLE-TEST", "SAMPLE-TEST-1", "API", deps=["SAMPLE-TEST-2", "SAMPLE-TEST-3"],
                       repos=["app-repo"])
    sdlc.create_ticket("SAMPLE-TEST", "SAMPLE-TEST-4", "UI", deps=["SAMPLE-TEST-1"])
    return sdlc


def test_scaffolding_writes_md(tmp_path):
    build(tmp_path)
    story = tmp_path / "SAMPLE-TEST" / "stories" / "SAMPLE-TEST-1"
    assert (tmp_path / "SAMPLE-TEST" / "prd.md").exists()
    assert (story / "spec-tech.md").exists()
    assert (story / "status.json").exists()
    assert json.loads((story / "status.json").read_text())["status"] == "draft"


def test_get_ticket_rehydrates_in_one_call(tmp_path):
    sdlc = build(tmp_path)
    b = sdlc.get_ticket("SAMPLE-TEST-1")
    assert b["id"] == "SAMPLE-TEST-1"
    assert b["repos"] == ["app-repo"]
    assert b["deps"] == ["SAMPLE-TEST-2", "SAMPLE-TEST-3"]
    assert b["status"] == "draft" and b["next"] == "spec_func"


def test_next_follows_the_dag(tmp_path):
    sdlc = build(tmp_path)
    assert sdlc.next("SAMPLE-TEST") == ["SAMPLE-TEST-2", "SAMPLE-TEST-3"]
    for s in ("spec_tech", "implemented", "reviewed", "deployed", "recette_ok", "accepted", "done"):
        sdlc.set_status("SAMPLE-TEST-2", s)
    for s in ("spec_tech", "implemented", "reviewed", "deployed", "recette_ok", "accepted", "done"):
        sdlc.set_status("SAMPLE-TEST-3", s)
    # socles done -> l'API se débloque
    assert sdlc.next("SAMPLE-TEST") == ["SAMPLE-TEST-1"]


def test_full_pipeline_and_board_mirror(tmp_path):
    sdlc = build(tmp_path)
    board: FakeBoard = sdlc.board  # type: ignore[assignment]
    steps = ["spec_func", "spec_tech", "implemented", "reviewed",
             "deployed", "recette_ok", "accepted", "done"]
    for s in steps:
        sdlc.set_status("SAMPLE-TEST-1", s)
    assert sdlc.get_ticket("SAMPLE-TEST-1")["status"] == "done"
    # le board a bien reçu chaque avancement (miroir une-voie)
    assert board.status["SAMPLE-TEST-1"] == "done"
    status_calls = [c for c in board.calls if c[0] == "status" and c[1] == "SAMPLE-TEST-1"]
    assert [c[2] for c in status_calls] == ["draft", *steps]


def test_fix_loop_transition(tmp_path):
    sdlc = build(tmp_path)
    for s in ("spec_func", "spec_tech", "implemented", "reviewed", "deployed"):
        sdlc.set_status("SAMPLE-TEST-1", s)
    # recette KO -> retour dev
    sdlc.set_status("SAMPLE-TEST-1", "implemented")
    assert sdlc.get_ticket("SAMPLE-TEST-1")["status"] == "implemented"


def test_link_artifact(tmp_path):
    sdlc = build(tmp_path)
    sdlc.link_artifact("SAMPLE-TEST-1", "spec_tech", "SAMPLE-TEST/stories/SAMPLE-TEST-1/spec-tech.md")
    assert sdlc.get_ticket("SAMPLE-TEST-1")["artifacts"]["spec_tech"].endswith("spec-tech.md")
