"""Phase 6 — orchestration : bulle threadée dans le ctx des agents, finalize d'accept, clean_workspace."""
import json
import subprocess
from pathlib import Path

from sdlc import cli
from sdlc.agentws import build_agent_workspace, clean_workspace
from sdlc.orchestrator import accept, run_ticket_upstream
from sdlc.service import Sdlc
from sdlc.workspace import Ticket, Workspace


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t"); _git(path, "config", "user.name", "t")
    (path / "f.txt").write_text("x"); _git(path, "add", "-A"); _git(path, "commit", "-q", "-m", "init")
    return path


def _data(tmp_path):
    repo = _init_repo(tmp_path / "app")
    ws = tmp_path / "data"; ws.mkdir()
    (ws / "sdlc.config.json").write_text(json.dumps(
        {"prefix": "X", "reposRoot": str(tmp_path), "repos": {"app": str(repo)}, "refBranch": "main"}))
    return repo, ws


# --- orchestrateur : la bulle arrive dans le ctx des agents ---

def test_bubble_threaded_into_ctx(tmp_path):
    ws = Workspace(tmp_path)
    sdlc = Sdlc(ws)
    ws.create_epic("X-E", "e"); ws.create_story(Ticket(id="X-1", epic="X-E", title="t"))
    seen = {}
    agents = {"reviewer": lambda ctx: (seen.update(ctx), {"conform": False, "note": "stop"})[1]}
    run_ticket_upstream(sdlc, "X-1", agents, escalation={"review": "auto"},
                        bubble={"worktree": "/wt/app", "additionalDirectories": ["/wt/app"]})
    assert seen["bubble"]["worktree"] == "/wt/app"   # l'agent voit le worktree scopé


def test_accept_calls_finalize():
    calls = []

    class FakeSdlc:
        def set_status(self, story, st): calls.append(st)

    accept(FakeSdlc(), "X-1", finalize=lambda: calls.append("finalized"))
    assert calls == ["accepted", "done", "finalized"]   # nettoyage APRÈS done


# --- clean_workspace : remove si mergé, garde sinon ---

def test_clean_removes_when_merged(tmp_path, monkeypatch):
    repo, ws = _data(tmp_path)
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    cli.main(["create-epic", "X-E", "e"]); cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app"])
    res = build_agent_workspace("X", "X-1", branch="feat/X-1")
    w = res["worktrees"]["app"]
    (Path(w) / "g.txt").write_text("y"); _git(w, "add", "-A"); _git(w, "commit", "-q", "-m", "feat")
    _git(repo, "merge", "--no-edit", "-q", "feat/X-1")               # mergée sur refBranch (main)
    out = clean_workspace("X", "X-1", branch="feat/X-1")
    assert out["cleaned"]["app"]["removed"] and out["bubbleRemoved"]
    assert not Path(w).exists() and not Path(res["workspace"]).exists()


def test_clean_keeps_when_unmerged(tmp_path, monkeypatch):
    repo, ws = _data(tmp_path)
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    cli.main(["create-epic", "X-E", "e"]); cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app"])
    res = build_agent_workspace("X", "X-1", branch="feat/X-1")
    w = res["worktrees"]["app"]
    (Path(w) / "g.txt").write_text("y"); _git(w, "add", "-A"); _git(w, "commit", "-q", "-m", "wip")
    out = clean_workspace("X", "X-1", branch="feat/X-1")             # pas mergée
    assert out["cleaned"]["app"]["removed"] is False and out["bubbleRemoved"] is False
    assert Path(w).exists() and Path(res["workspace"]).exists()
