"""`sdlc live` (read-only cross-project snapshot) and `sdlc view` (local page over it)."""
import http.client
import json
import threading

import pytest

from sdlc import cli
from sdlc.live import parse_decisions, progress, snapshot
from sdlc.project import register_project
from sdlc.view import PortNotConfigured, make_server, resolve_port


# --- fixtures ---------------------------------------------------------------------------------

def _story(root, epic, sid, status, title="t"):
    d = root / epic / "stories" / sid
    d.mkdir(parents=True)
    (d / "status.json").write_text(json.dumps(
        {"id": sid, "epic": epic, "title": title, "status": status, "deps": [], "repos": []}))


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("HOME", str(h))                  # isolates ~/.claude/sdlc/projects.json
    monkeypatch.delenv("SDLC_VIEW_PORT", raising=False)
    monkeypatch.delenv("SDLC_WORKSPACE", raising=False)
    return h


def _registry(home, projects, **extra):
    reg = home / ".claude" / "sdlc" / "projects.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({"projects": projects, **extra}))
    return reg


def _tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


# --- progress -----------------------------------------------------------------------------------

def test_progress_counts_done_and_leaves_out_abandoned_and_superseded():
    p = progress(["draft", "recette_ok", "accepted", "done", "merged", "implemented",
                  "abandoned", "superseded"])
    assert p == {"done": 4, "total": 6, "excluded": 2, "percent": 67}


def test_progress_of_nothing_has_no_percent():
    assert progress([])["percent"] is None
    assert progress(["abandoned"]) == {"done": 0, "total": 0, "excluded": 1, "percent": None}


# --- decisions ----------------------------------------------------------------------------------

POASSIST_STYLE = """\
> Légende : ✅ décidé par Anis · 🟡 hypothèse Harry — à valider · ⛔ bloqué.

| # | Date | Décision | Pourquoi | Statut |
|---|---|---|---|---|
| D1 | 27/09 | Épic ouvert | Consigne | ✅ |
| D2 | 27/09 | Hypothèse de trunk | Reco | 🟡 |
| D3 | 27/09 | Tranché, l'ancienne hypothèse 🟡 est close | Anis | ✅ |
| D4 | 27/09 | Attend un accès | — | ⛔ |
"""

RUNWS_STYLE = """\
> Légende : ✅ décidé par Anis · 🟡 hypothèse Harry / reco archi — **à valider** · ⛔ bloqué

| Story | État | Trunk local |
|---|---|---|
| -1 workspace | ✅ recette_ok, mergée | moteur |
| -8a usine | 🟡 recette bloquée | branche |

| # | Action | Où |
|---|---|---|
| A2 | ✅ (Anis 27/09 : appliquée) Reco archi 🟡 d'origine = (b) | spec |
| A3 | 🟡 Relire les arbitrages archi | `spec-review.md` |
| A4 | Accept de -10 (gate humaine) | D7 |
| **A5** | ⛔ en attente du jeton | — |
"""


def test_decisions_marker_in_last_column():
    d = parse_decisions(POASSIST_STYLE)
    assert (d["decided"], d["pending"], d["blocked"], d["unmarked"]) == (2, 1, 1, 0)
    assert [(o["id"], o["kind"]) for o in d["open"]] == [("D2", "pending"), ("D4", "blocked")]


def test_decisions_marker_in_second_column_and_non_decision_tables_ignored():
    d = parse_decisions(RUNWS_STYLE)
    # Legend and the story recap table are not counted; A2 is decided even though its text quotes 🟡.
    assert (d["decided"], d["pending"], d["blocked"], d["unmarked"]) == (1, 1, 1, 1)
    assert [o["id"] for o in d["open"]] == ["A3", "A5"]
    assert d["open"][0]["text"] == "🟡 Relire les arbitrages archi"


# --- snapshot -----------------------------------------------------------------------------------

def test_snapshot_reads_all_projects_without_writing(home, tmp_path):
    a = tmp_path / "a-data"
    _story(a, "AA-ONE", "AA-ONE-2", "recette_ok")
    _story(a, "AA-ONE", "AA-ONE-10", "implemented")
    _story(a, "AA-ONE", "AA-ONE-1", "superseded")
    (a / "AA-ONE" / "prd.md").write_text("# PRD — AA-ONE · Premier épic\n\ntexte\n")
    (a / "AA-ONE" / "decisions-autonomie.md").write_text(POASSIST_STYLE)
    (a / "AA-EMPTY").mkdir()
    (a / "AA-EMPTY" / "prd.md").write_text("# AA-EMPTY — Pas encore découpé\n")
    (a / "_agentws").mkdir()                                # engine folders are not epics
    missing = tmp_path / "never-created"
    _registry(home, {"AA": {"workspace": str(a)}, "BB": {"workspace": str(missing)}})
    before = _tree(tmp_path)

    s = snapshot()

    assert _tree(tmp_path) == before                        # strictly read-only
    assert not missing.exists()
    aa, bb = s["projects"]
    assert bb == {"prefix": "BB", "workspace": str(missing), "exists": False, "epics": []}
    epics = {e["id"]: e for e in aa["epics"]}
    assert set(epics) == {"AA-ONE", "AA-EMPTY"}
    one = epics["AA-ONE"]
    assert one["title"] == "Premier épic"
    assert [x["id"] for x in one["stories"]] == ["AA-ONE-1", "AA-ONE-2", "AA-ONE-10"]   # natural order
    assert one["progress"] == {"done": 1, "total": 2, "excluded": 1, "percent": 50}
    assert one["decisions"]["pending"] == 1 and one["updatedAt"]
    assert epics["AA-EMPTY"]["title"] == "Pas encore découpé"
    assert epics["AA-EMPTY"]["progress"]["percent"] is None and epics["AA-EMPTY"]["decisions"] is None
    assert s["pipeline"][0] == "draft" and s["pipeline"][-1] == "done"


def test_snapshot_single_project_and_unknown_project(home, tmp_path):
    _registry(home, {"AA": {"workspace": str(tmp_path)}, "BB": {"workspace": str(tmp_path)}})
    assert [p["prefix"] for p in snapshot("BB")["projects"]] == ["BB"]
    with pytest.raises(KeyError, match="ZZ"):
        snapshot("ZZ")


def test_snapshot_reports_a_broken_project_without_hiding_others(home, tmp_path):
    bad = tmp_path / "bad"
    (bad / "E" / "stories" / "E-1").mkdir(parents=True)
    (bad / "E" / "stories" / "E-1" / "status.json").write_text("{not json")
    good = tmp_path / "good"
    _story(good, "G", "G-1", "done")
    _registry(home, {"BAD": {"workspace": str(bad)}, "GOOD": {"workspace": str(good)}})
    bad_p, good_p = snapshot()["projects"]
    assert "error" in bad_p and good_p["progress"]["done"] == 1


def test_cli_live(home, tmp_path, capsys):
    _story(tmp_path / "d", "E", "E-1", "accepted")
    _registry(home, {"P": {"workspace": str(tmp_path / "d")}})
    assert cli.main(["live"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["projects"][0]["progress"]["percent"] == 100


# --- port resolution ----------------------------------------------------------------------------

def test_port_order_cli_then_env_then_registry(home, monkeypatch):
    _registry(home, {}, view={"port": 4102})
    assert resolve_port() == (4102, "registry")
    monkeypatch.setenv("SDLC_VIEW_PORT", "4101")
    assert resolve_port() == (4101, "env")
    assert resolve_port(4100) == (4100, "cli")


def test_port_not_configured_points_to_4002(home):
    _registry(home, {})
    with pytest.raises(PortNotConfigured) as e:
        resolve_port()
    msg = str(e.value)
    assert "4002" in msg and "SDLC_VIEW_PORT" in msg and "--port" in msg


@pytest.mark.parametrize("value", ["abc", "0", "70000"])
def test_invalid_env_port_is_rejected(home, monkeypatch, value):
    monkeypatch.setenv("SDLC_VIEW_PORT", value)
    with pytest.raises(ValueError, match="SDLC_VIEW_PORT"):
        resolve_port()


def test_registering_a_project_keeps_the_view_port(home, tmp_path):
    _registry(home, {}, view={"port": 4102})
    register_project("NEW", tmp_path)
    assert resolve_port() == (4102, "registry")


def test_cli_view_without_port_fails_cleanly(home, capsys):
    _registry(home, {})
    assert cli.main(["view"]) == 1
    assert "4002" in json.loads(capsys.readouterr().err)["error"]


# --- server -------------------------------------------------------------------------------------

@pytest.fixture
def server(home, tmp_path):
    _story(tmp_path / "d", "E", "E-1", "done")
    _registry(home, {"P": {"workspace": str(tmp_path / "d")}})
    httpd = make_server(0)                                  # ephemeral port, tests only
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _req(port, method, path, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Host": host} if host else {}
    c.request(method, path, headers=headers)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, r.getheader("Content-Type"), body


def test_server_routes(server):
    status, ctype, body = _req(server, "GET", "/")
    assert status == 200 and ctype.startswith("text/html") and b"/api/live" in body
    status, _, body = _req(server, "GET", "/api/live")
    assert status == 200 and json.loads(body)["projects"][0]["prefix"] == "P"
    status, _, body = _req(server, "GET", "/api/live?project=NOPE")
    assert status == 404 and "NOPE" in json.loads(body)["error"]
    assert _req(server, "GET", "/healthz")[0] == 200
    assert _req(server, "GET", "/etc/passwd")[0] == 404


def test_server_is_read_only_and_loopback_only(server):
    assert _req(server, "POST", "/api/live")[0] == 405
    assert _req(server, "DELETE", "/")[0] == 405
    assert _req(server, "GET", "/api/live", host="evil.example:80")[0] == 403
    assert _req(server, "GET", "/api/live", host=f"localhost:{server}")[0] == 200
