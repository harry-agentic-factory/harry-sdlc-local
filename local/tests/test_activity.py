"""`sdlc-view activity` — the `_live.json` file of what runs right now, and its place in the board."""
import datetime as dt
import json
import os
import threading

import pytest

from sdlc_view import activity as act
from sdlc_view import cli
from sdlc_view.activity import ActivityError, ActivityStore, read_activity
from sdlc_view.board import snapshot

T0 = dt.datetime(2026, 9, 28, 10, 0, 0, tzinfo=dt.timezone.utc)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += dt.timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ws(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("SDLC_VIEW_PORT", raising=False)
    monkeypatch.delenv("SDLC_WORKSPACE", raising=False)
    return h


def _registry(home, projects):
    reg = home / ".claude" / "sdlc" / "projects.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({"projects": projects}))


def _story(root, epic, sid, status="implemented"):
    d = root / epic / "stories" / sid
    d.mkdir(parents=True)
    (d / "status.json").write_text(json.dumps(
        {"id": sid, "epic": epic, "title": "t", "status": status, "deps": [], "repos": []}))


# --- store --------------------------------------------------------------------------------------

def test_start_beat_stop_list(ws, clock):
    s = ActivityStore(ws, clock=clock)
    a = s.start("EP", "recette live MR-A", story="EP-1", agent="recetteur")
    assert a["id"].startswith("act-20260928-100000-")
    assert a["startedAt"] == a["lastBeat"] == "2026-09-28T10:00:00+00:00"
    raw = json.loads((ws / "_live.json").read_text())
    assert raw["version"] == 1 and [e["id"] for e in raw["running"]] == [a["id"]]

    clock.advance(minutes=3)
    b = s.beat(a["id"])
    assert b["lastBeat"] == "2026-09-28T10:03:00+00:00" and b["stale"] is False and b["elapsedS"] == 180

    clock.advance(minutes=2)
    done = s.stop(a["id"], result="ko", note="  2 critères  KO ")
    assert (done["result"], done["note"], done["durationS"]) == ("ko", "2 critères KO", 300)
    assert done["endedAt"] == "2026-09-28T10:05:00+00:00"

    lst = s.list()
    assert lst["running"] == [] and [e["id"] for e in lst["recent"]] == [a["id"]]


def test_unknown_and_finished_ids_are_errors(ws, clock):
    s = ActivityStore(ws, clock=clock)
    with pytest.raises(KeyError, match="inconnue"):
        s.beat("act-nope")
    with pytest.raises(KeyError, match="inconnue"):
        s.stop("act-nope")
    a = s.start("EP", "x")
    s.stop(a["id"])
    with pytest.raises(ActivityError, match="déjà terminée"):
        s.stop(a["id"])
    with pytest.raises(ActivityError, match="résultat invalide"):
        s.stop(s.start("EP", "y")["id"], result="maybe")


def test_required_fields_and_missing_workspace(ws, tmp_path):
    s = ActivityStore(ws)
    with pytest.raises(ActivityError, match="--what"):
        s.start("EP", "   ")
    with pytest.raises(ActivityError, match="--epic"):
        s.start("", "x")
    with pytest.raises(ActivityError, match="introuvable"):
        ActivityStore(tmp_path / "missing")


def test_stale_after_15_minutes_without_heartbeat(ws, clock):
    s = ActivityStore(ws, clock=clock)
    a = s.start("EP", "long run")
    clock.advance(minutes=14, seconds=59)
    assert read_activity(ws, now=clock())["running"][0]["stale"] is False
    clock.advance(seconds=1)
    r = read_activity(ws, now=clock())["running"][0]
    assert r["stale"] is True and r["idleS"] == 900
    s.beat(a["id"])                                          # a heartbeat revives it
    assert read_activity(ws, now=clock())["running"][0]["stale"] is False


def test_recent_is_newest_first_and_capped(ws, clock):
    s = ActivityStore(ws, clock=clock)
    ids = []
    for i in range(act.RECENT_KEPT + 5):
        clock.advance(seconds=1)
        ids.append(s.stop(s.start("EP", f"run {i}")["id"])["id"])
    raw = json.loads((ws / "_live.json").read_text())
    assert [e["id"] for e in raw["recent"]] == ids[::-1][: act.RECENT_KEPT]
    assert len(read_activity(ws)["recent"]) == act.RECENT_SHOWN


def test_write_is_atomic_and_leaves_no_temp_file(ws, clock, monkeypatch):
    s = ActivityStore(ws, clock=clock)
    first = s.start("EP", "kept")
    before = (ws / "_live.json").read_text()

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(act.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        s.start("EP", "lost")
    assert (ws / "_live.json").read_text() == before         # old content intact
    assert sorted(p.name for p in ws.iterdir()) == ["_live.json"]   # no temp, no lock file
    monkeypatch.undo()
    assert [e["id"] for e in s.list()["running"]] == [first["id"]]


def test_concurrent_starts_do_not_lose_entries(ws):
    s = ActivityStore(ws)
    threads = [threading.Thread(target=s.start, args=("EP", f"t{i}")) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(s.list()["running"]) == 12


def test_unreadable_or_newer_file(ws):
    (ws / "_live.json").write_text("{broken")
    assert "illisible" in read_activity(ws)["error"]
    with pytest.raises(ActivityError, match="illisible"):
        ActivityStore(ws).start("EP", "x")                   # never clobbers a file it cannot read
    assert (ws / "_live.json").read_text() == "{broken"
    (ws / "_live.json").write_text(json.dumps({"version": 99, "running": [], "recent": []}))
    assert "version" in read_activity(ws)["error"]


def test_read_activity_is_read_only(ws):
    assert read_activity(ws) == {"running": [], "recent": []}
    assert list(ws.iterdir()) == []


# --- board snapshot -----------------------------------------------------------------------------

def test_snapshot_exposes_running_and_recent_per_project_and_epic(home, tmp_path, clock):
    a = tmp_path / "a"
    _story(a, "EP", "EP-1")
    _story(a, "OTHER", "OTHER-1")
    _registry(home, {"AA": {"workspace": str(a)}, "BB": {"workspace": str(tmp_path / "nope")}})
    s = ActivityStore(a, clock=clock)
    old = s.start("EP", "vieux run")
    clock.advance(minutes=20)
    live = s.start("EP", "recette live", story="EP-1", agent="recetteur")
    fin = s.stop(s.start("EP", "deploy")["id"], result="ok", note="v1.2")
    orphan = s.start("NEW-EPIC", "scope")                  # epic without folder yet
    before = sorted(p.name for p in a.iterdir())

    snap = snapshot(now=clock())

    assert sorted(p.name for p in a.iterdir()) == before
    assert snap["staleAfterMin"] == 15
    assert [(r["project"], r["id"]) for r in snap["running"]] == \
        [("AA", old["id"]), ("AA", live["id"]), ("AA", orphan["id"])]
    aa, bb = snap["projects"]
    assert bb["running"] == [] and bb["recent"] == []
    stale = {r["id"]: r["stale"] for r in aa["running"]}
    assert stale == {old["id"]: True, live["id"]: False, orphan["id"]: False}
    epics = {e["id"]: e for e in aa["epics"]}
    assert [r["id"] for r in epics["EP"]["running"]] == [old["id"], live["id"]]
    assert [r["id"] for r in epics["EP"]["recent"]] == [fin["id"]]
    assert epics["OTHER"]["running"] == [] and epics["OTHER"]["recent"] == []
    assert [r["id"] for r in epics["NEW-EPIC"]["running"]] == [orphan["id"]]
    assert aa["epics"][-1]["id"] == "OTHER"                 # busy epics are listed first


def test_board_survives_a_broken_activity_file(home, tmp_path):
    a = tmp_path / "a"
    _story(a, "EP", "EP-1")
    (a / "_live.json").write_text("nope")
    _registry(home, {"AA": {"workspace": str(a)}})
    p = snapshot()["projects"][0]
    assert "illisible" in p["activityError"] and p["epics"][0]["id"] == "EP"


def test_page_renders_activity_fields():
    page = (act.Path(act.__file__).with_name("view.html")).read_text(encoding="utf-8")
    for needle in ("En cours maintenant", "Rien ne tourne", "Derniers événements",
                   "sans signe de vie depuis", "prefers-reduced-motion", "@keyframes blink",
                   "data.running", "e.running", "p.running", "e.recent"):
        assert needle in page, needle


# --- CLI ----------------------------------------------------------------------------------------

def test_cli_activity_roundtrip(home, tmp_path, capsys):
    a = tmp_path / "a"
    a.mkdir()
    _registry(home, {"AA": {"workspace": str(a)}})
    assert cli.main(["--project", "AA", "activity", "start", "--epic", "EP", "--story", "EP-1",
                     "--what", "recette live MR-A", "--agent", "recetteur"]) == 0
    aid = json.loads(capsys.readouterr().out)["id"]
    assert cli.main(["--project", "AA", "activity", "beat", aid]) == 0
    assert json.loads(capsys.readouterr().out)["stale"] is False
    assert cli.main(["--project", "AA", "activity", "list"]) == 0
    assert [r["id"] for r in json.loads(capsys.readouterr().out)["running"]] == [aid]
    assert cli.main(["--project", "AA", "activity", "stop", aid, "--result", "cancelled",
                     "--note", "abandon"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == "cancelled"
    assert cli.main(["--project", "AA", "activity", "stop", aid]) == 1
    assert "déjà terminée" in json.loads(capsys.readouterr().err)["error"]
    assert cli.main(["--project", "AA", "activity", "beat", "act-x"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "activité inconnue : act-x"


def test_workspace_env_override_is_honoured(home, tmp_path, monkeypatch, capsys):
    a = tmp_path / "direct"
    a.mkdir()
    monkeypatch.setenv("SDLC_WORKSPACE", str(a))
    assert cli.main(["activity", "start", "--epic", "EP", "--what", "x"]) == 0
    assert os.path.exists(a / "_live.json")
