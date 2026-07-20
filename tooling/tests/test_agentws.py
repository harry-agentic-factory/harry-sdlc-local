"""Phase 3 — bulle scopée de l'agent : worktrees + settings.json (additionalDirectories) + skills projet."""
import json
import subprocess
from pathlib import Path

from sdlc import cli
from sdlc.agentws import build_agent_workspace


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t"); _git(path, "config", "user.name", "t")
    (path / "f.txt").write_text("x"); _git(path, "add", "-A"); _git(path, "commit", "-q", "-m", "init")
    return path


def _setup(tmp_path, with_skill=True):
    repo = _init_repo(tmp_path / "app")
    brain = tmp_path / "brain"; brain.mkdir()
    ws = tmp_path / "data"; ws.mkdir()
    cfg = {"prefix": "X", "reposRoot": str(tmp_path),
           "repos": {"app": str(repo)}, "brain": str(brain), "refBranch": "main"}
    (ws / "sdlc.config.json").write_text(json.dumps(cfg))
    if with_skill:
        sk = ws / "skills" / "deploy-cfea"; sk.mkdir(parents=True)
        (sk / "SKILL.md").write_text("---\nname: deploy-cfea\ndescription: projet\n---\nx\n")
    return repo, brain, ws


def test_build_agent_workspace(tmp_path, monkeypatch):
    repo, brain, ws = _setup(tmp_path)
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    cli.main(["create-epic", "X-E", "e"]); cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app"])

    res = build_agent_workspace("X", "X-1", branch="feat/X-1")
    bubble = Path(res["workspace"])
    settings = json.loads((bubble / ".claude" / "settings.json").read_text())
    dirs = settings["permissions"]["additionalDirectories"]

    # worktree isolé du repo touché, + brain + data — et RIEN d'autre
    assert res["worktrees"]["app"] in dirs and Path(res["worktrees"]["app"]).is_dir()
    assert str(brain.resolve()) in dirs
    assert str(ws.resolve()) in dirs
    # skill projet symlinké dans la bulle
    link = bubble / ".claude" / "skills" / "deploy-cfea"
    assert link.is_symlink() and res["projectSkills"] == ["deploy-cfea"]
    # identité héritée
    assert res["credentials"] == {"source": "host"}


def test_build_is_idempotent(tmp_path, monkeypatch):
    repo, brain, ws = _setup(tmp_path, with_skill=False)
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    cli.main(["create-epic", "X-E", "e"]); cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app"])
    r1 = build_agent_workspace("X", "X-1", branch="feat/X-1")
    r2 = build_agent_workspace("X", "X-1", branch="feat/X-1")   # relance → réutilise worktree, réécrit settings
    assert r1["workspace"] == r2["workspace"]
    assert r1["worktrees"] == r2["worktrees"] and r2["projectSkills"] == []


def test_cli_workspace(tmp_path, capsys, monkeypatch):
    repo, brain, ws = _setup(tmp_path, with_skill=False)
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    cli.main(["create-epic", "X-E", "e"]); cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app"])
    capsys.readouterr()
    rc = cli.main(["workspace", "X-1", "--branch", "feat/X-1"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and Path(out["workspace"], ".claude", "settings.json").exists()
