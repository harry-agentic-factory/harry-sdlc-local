"""Tracker bridge: card lifecycle, pull merge, push plan, CLI — offline (fake board, fake sdlc)."""
import json

import pytest

from tracker import cli
from tracker.store import Tracker, card_ref

LISTS = {"Backlog": "L0", "TODO": "L1", "IN PROGRESS": "L2", "TOVALIDATE": "L3", "VALIDATED": "L4"}
BLOCK = {"_note": "comment", "type": "trello", "board": "B", "credentials": "/nowhere.json",
         "lists": LISTS, "intake": {"TODO": "bug", "Backlog": "evol"}}


def remote(cid, short, lst="L1", activity="2026-09-23T10:00:00.000Z", labels=("bug",), name=None):
    return {"id": cid, "shortLink": short, "shortUrl": f"https://trello.com/c/{short}", "name": name or short,
            "idList": lst, "labels": [{"name": n} for n in labels], "dateLastActivity": activity}


@pytest.fixture
def t(tmp_path):
    root = tmp_path / "_tracker"
    root.mkdir()
    (root / "config.json").write_text(json.dumps(Tracker.build_config(BLOCK)))
    return Tracker.load(root)


def test_card_ref_accepts_url_shortlink_and_id():
    assert card_ref("https://trello.com/c/hMBRBCtY/1-le-telephone") == "hMBRBCtY"
    assert card_ref(" hMBRBCtY ") == "hMBRBCtY"
    assert card_ref("6ab3aa5ad7b15058e91f70af") == "6ab3aa5ad7b15058e91f70af"


def test_build_config_drops_comments_and_adds_defaults():
    cfg = Tracker.build_config(BLOCK)
    assert "_note" not in cfg
    assert cfg["statusToList"]["recette_ok"] == "TOVALIDATE"
    assert cfg["statusToList"]["feature_validated"] == "IN PROGRESS"
    assert cfg["listOrder"][0] == "Backlog"


def test_pull_registers_new_cards_and_only_intake_ones_are_to_instruct(t):
    r = t.merge_pull([remote("c1", "AAA"), remote("c2", "BBB", lst="L2")], at="2026-09-24T08:00:00+00:00")
    assert r["new"] == ["c1", "c2"]
    assert r["toInstruct"] == ["c1"]            # IN PROGRESS is not an intake list
    assert t.cards["c1"]["list"] == "TODO" and t.cards["c1"]["state"] == "new"


def test_pull_flags_a_card_edited_after_instruction_and_never_forgets_a_card(t):
    t.merge_pull([remote("c1", "AAA")])
    t.instructed("AAA", "cards/AAA/fiche.md", at="2026-09-24T09:00:00+00:00")
    r = t.merge_pull([remote("c1", "AAA", activity="2026-09-24T10:00:00.000Z")])
    assert r["changed"] == ["c1"] and r["toReview"] == ["c1"]
    r = t.merge_pull([])
    assert r["gone"] == ["c1"] and t.cards["c1"]["gone"] is True
    assert t.merge_pull([])["gone"] == []       # reported once


def test_priority_is_the_rank_in_the_list(t):
    cards = [dict(remote("c1", "AAA"), pos=300), dict(remote("c2", "BBB"), pos=100),
             dict(remote("c3", "CCC", lst="L0"), pos=50)]
    t.merge_pull(cards)
    assert [t.cards[c]["rank"] for c in ("c1", "c2", "c3")] == [2, 1, 1]
    assert [c["shortLink"] for c in t.select(state="new") if c["list"] == "TODO"] == ["BBB", "AAA"]


def test_nature_comes_from_the_label_then_the_intake_list(t):
    t.merge_pull([remote("c1", "AAA", lst="L0", labels=("bug", "bloquant")),
                  remote("c2", "BBB", lst="L0", labels=()), remote("c3", "CCC", lst="L2", labels=())])
    assert [t.nature(t.cards[c]) for c in ("c1", "c2", "c3")] == ["bug", "evol", None]
    assert [c["shortLink"] for c in t.select(nature="bug")] == ["AAA"]


def test_decisions_need_a_reason_except_fix(t):
    t.merge_pull([remote("c1", "AAA")])
    with pytest.raises(ValueError):
        t.decide("AAA", "rejected")
    with pytest.raises(ValueError):
        t.decide("AAA", "maybe", "x")
    assert t.decide("AAA", "fix")["state"] == "reviewed"


def test_only_a_card_to_fix_becomes_a_story(t):
    t.merge_pull([remote("c1", "AAA"), remote("c2", "BBB")])
    t.decide("BBB", "deferred", "after the release")
    with pytest.raises(ValueError):
        t.link("BBB", "HIA-BUG-1")
    t.decide("AAA", "other", "fix the read model instead")
    c = t.link("AAA", "HIA-BUG-1", epic="HIA-BUG")
    t.link("AAA", "HIA-BUG-2")
    assert c["state"] == "planned" and t.cards["c1"]["stories"] == ["HIA-BUG-1", "HIA-BUG-2"]
    assert [c["card"] for c in t.select(story="HIA-BUG-2")] == ["c1"]


def planned(t, cid="c1", short="AAA", lst="L1", stories=("S1",)):
    t.merge_pull([remote(cid, short, lst=lst)])
    t.decide(short, "fix")
    for s in stories:
        t.link(short, s)


def test_plan_moves_forward_following_the_least_advanced_story(t):
    planned(t, stories=("S1", "S2"))
    plan = t.plan({"S1": "recette_ok", "S2": "implemented"}.get)
    assert [(m["from"], m["to"], m["status"]) for m in plan["moves"]] == [("TODO", "IN PROGRESS", "implemented")]


def test_plan_never_moves_back_and_reports_why(t):
    planned(t, lst="L4")                                   # reporter put it in VALIDATED
    assert t.plan({"S1": "recette_ok"}.get)["signals"][0]["kind"] == "reporter-accepted"
    assert t.plan({"S1": "deployed"}.get)["signals"][0]["kind"] == "card-ahead-of-story"
    assert t.plan({"S1": "deployed"}.get)["moves"] == []


def test_plan_does_not_fight_a_human_who_sent_the_card_back(t):
    planned(t)
    t.mark_pushed("c1", "TOVALIDATE")
    t.merge_pull([remote("c1", "AAA", lst="L1")])          # reporter moved it back to TODO
    plan = t.plan({"S1": "recette_ok"}.get)
    assert plan["moves"] == [] and plan["signals"][0]["kind"] == "sent-back-by-human"


def test_plan_reports_an_unknown_story(t):
    planned(t)
    assert t.plan(lambda s: None)["signals"][0]["kind"] == "unknown-story"


def test_links_survive_a_save_load_round_trip(t):
    planned(t)
    t.save()
    again = Tracker.load(t.root)
    assert again.cards["c1"]["stories"] == ["S1"] and again.links["lastPull"]


# ---- CLI --------------------------------------------------------------------------------------------------
class FakeBoard:
    def __init__(self, cards):
        self.cards, self.moved, self.comments = cards, [], []

    def board_cards(self):
        return self.cards

    def move(self, cid, lid):
        self.moved.append((cid, lid))

    def comment(self, cid, text):
        self.comments.append((cid, text))


@pytest.fixture
def env(tmp_path, monkeypatch):
    statuses = {"S1": "deployed"}

    def fake_sdlc(prefix, *args):
        if args[0] == "config":
            return {"workspace": str(tmp_path), "tracker": BLOCK}
        if args[0] == "get":
            if args[1] not in statuses:
                raise RuntimeError("unknown")
            return {"status": statuses[args[1]]}
        raise AssertionError(args)

    board = FakeBoard([remote("c1", "AAA"), remote("c2", "BBB", lst="L0", labels=())])
    monkeypatch.setattr(cli, "_sdlc", fake_sdlc)
    monkeypatch.setattr(cli, "source_for", lambda cfg: board)
    return tmp_path, board, statuses


def run(capsys, *argv):
    code = cli.main(["--project", "HIA", *argv])
    out, err = capsys.readouterr()
    return code, (json.loads(out) if out.strip().startswith(("{", "[")) else out), err


def test_cli_full_cycle(env, capsys):
    root, board, statuses = env
    (root / ".gitignore").write_text("*.db")
    code, out, _ = run(capsys, "init")
    assert code == 0 and out["config"] == "written" and out["gitignore"] == "added"
    assert (root / ".gitignore").read_text().splitlines()[0] == "*.db"
    assert "_tracker/" in (root / ".gitignore").read_text().splitlines()
    assert run(capsys, "init", "--force")[1]["gitignore"] == "already ignored"
    assert "_note" not in json.loads((root / "_tracker" / "config.json").read_text())
    assert run(capsys, "init")[1]["config"] == "exists"

    _, out, _ = run(capsys, "pull")
    assert sorted((c["shortLink"], c["nature"]) for c in out["toInstruct"]) == [("AAA", "bug"), ("BBB", "evol")]
    _, out, _ = run(capsys, "pull", "--nature", "bug")
    assert [c["shortLink"] for c in out["toInstruct"]] == ["AAA"]

    run(capsys, "instructed", "AAA", "--fiche", "cards/AAA/fiche.md")
    code, _, err = run(capsys, "decide", "AAA", "deferred")
    assert code == 2 and "reason" in json.loads(err)["error"]
    run(capsys, "decide", "AAA", "fix", "--review", "reviews/2026-09-29/review-bugs.md")
    run(capsys, "link", "https://trello.com/c/AAA/1-x", "S1", "--epic", "E")

    _, out, _ = run(capsys, "push")
    assert out["applied"] is False and out["moves"][0]["to"] == "IN PROGRESS" and board.moved == []
    _, out, _ = run(capsys, "push", "--apply", "--comment")
    assert board.moved == [("c1", "L2")] and "S1 (deployed)" in board.comments[0][1]
    assert run(capsys, "push")[1]["moves"] == []            # idempotent

    _, out, _ = run(capsys, "show", "--state", "planned")
    assert [c["shortLink"] for c in out] == ["AAA"] and out[0]["lastPushedList"] == "IN PROGRESS"


def test_cli_card_download_saves_uploads_and_records_their_path(env, capsys, tmp_path):
    root, board, _ = env
    atts = [{"id": "a1", "name": "écran 1.png", "url": "u1", "isUpload": True, "bytes": 3, "mimeType": "image/png"},
            {"id": "a2", "name": "link", "url": "https://x", "isUpload": False}]
    board.card = lambda ref: {"id": "c1", "shortLink": "AAA", "attachments": [dict(a) for a in atts]}

    def download(att, dest):
        if not att["isUpload"]:
            return None
        dest.mkdir(parents=True, exist_ok=True)
        p = dest / f"{att['id']}-x.png"
        p.write_bytes(b"png")
        return p
    board.download = download
    run(capsys, "init")
    run(capsys, "pull")
    _, out, _ = run(capsys, "card", "AAA", "--download")
    saved = out["attachments"][0]["path"]
    assert saved.startswith(str(root / "_tracker" / "cards" / "AAA" / "attachments")) and out["attachments"][1]["path"] is None
    assert run(capsys, "show", "AAA")[1]["attachments"][0]["path"] == saved


def test_cli_unknown_card_is_a_clean_error(env, capsys):
    run(capsys, "init")
    code, _, err = run(capsys, "show", "ZZZ")
    assert code == 2 and "unknown" in json.loads(err)["error"]
