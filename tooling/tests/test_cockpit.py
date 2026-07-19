from sdlc import Sdlc, Workspace
from sdlc.board import NullBoard
from cockpit.data import build_board


def test_board_groups_by_status_and_inbox(tmp_path):
    s = Sdlc(Workspace(tmp_path), NullBoard())
    s.create_epic("HIA-T", "demo")
    s.create_ticket("HIA-T", "HIA-T-1", "a")
    s.create_ticket("HIA-T", "HIA-T-2", "b")
    for st in ("spec_func", "spec_tech", "implemented", "reviewed", "deployed", "recette_ok"):
        s.set_status("HIA-T-1", st)

    board = build_board(s)
    assert board["counts"]["draft"] == 1          # HIA-T-2
    assert board["counts"]["recette_ok"] == 1     # HIA-T-1
    assert [c["id"] for c in board["inbox"]] == ["HIA-T-1"]  # attend l'accept humain
