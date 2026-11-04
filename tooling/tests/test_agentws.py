"""Phase 3 — bulle scopée de l'agent : worktrees + settings.json (additionalDirectories) + skills projet."""
import json
import subprocess
from pathlib import Path

from sdlc import cli, worktree as wt
from sdlc.agentws import build_agent_workspace, clean_workspace


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


# --- brain épinglé par workspace (worktree détaché, lecture seule, trace, nettoyage) ---

BRAIN_REF_FIELDS = ("repo", "branch", "commit")      # mêmes noms que le bloc `brain` du manifeste


def _git_out(repo, *a) -> str:
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,
                          check=True).stdout.strip()


def _setup_git_brain(tmp_path):
    """Projet dont le brain est un dépôt git à deux commits, et deux tickets."""
    repo, brain, ws = _setup(tmp_path, with_skill=False)
    _init_repo(brain)
    (brain / "index.md").write_text("# c1\n")
    _git(brain, "add", "-A"); _git(brain, "commit", "-q", "-m", "c1")
    c1 = _git_out(brain, "rev-parse", "HEAD")
    cli.main(["create-epic", "X-E", "e"])
    for us in ("X-1", "X-2"):
        cli.main(["create-ticket", "X-E", us, "t", "--repos", "app"])
    return repo, brain, ws, c1


def _setup_three_state_brain(tmp_path):
    """Brain clone at three states: a pushed commit, a local commit not pushed, and later a dirty file."""
    repo, brain, ws = _setup(tmp_path, with_skill=False)
    upstream = _init_repo(tmp_path / "brain-origin")
    (upstream / "index.md").write_text("# pushed\n")
    _git(upstream, "add", "-A"); _git(upstream, "commit", "-q", "-m", "pushed")
    pushed = _git_out(upstream, "rev-parse", "HEAD")
    subprocess.run(["git", "clone", "-q", str(upstream), str(brain)], capture_output=True,
                   text=True, check=True)
    _git(brain, "config", "user.email", "t@t"); _git(brain, "config", "user.name", "t")
    (brain / "index.md").write_text("# local only\n")
    _git(brain, "add", "-A"); _git(brain, "commit", "-q", "-m", "local only, never pushed")
    local = _git_out(brain, "rev-parse", "HEAD")
    assert _git_out(brain, "rev-parse", "refs/remotes/origin/main") == pushed != local
    cli.main(["create-epic", "X-E", "e"])
    cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app"])
    return brain, ws, pushed, local


def test_ac20_the_bubble_pins_the_local_head(tmp_path, monkeypatch):
    """A commit made minutes earlier, not yet pushed, is what the agent reads."""
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path / "data"))
    brain, ws, pushed, local = _setup_three_state_brain(tmp_path)
    res = build_agent_workspace("X", "X-1", branch="feat/X-1")
    assert res["brain"]["commit"] == local != pushed
    assert json.loads(Path(res["brainTrace"]).read_text())["commit"] == local
    assert _git_out(Path(res["brainPath"]), "rev-parse", "HEAD") == local
    assert (Path(res["brainPath"]) / "index.md").read_text() == "# local only\n"
    assert res["brainWarnings"] == []


def test_ac20bis_a_dirty_brain_warns_without_moving_the_pin(tmp_path, monkeypatch):
    """The warning changes what the human knows, never what the agent sees."""
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path / "data"))
    brain, ws, pushed, local = _setup_three_state_brain(tmp_path)
    (brain / "index.md").write_text("# modified, never committed\n")
    res = build_agent_workspace("X", "X-1", branch="feat/X-1")
    assert res["brainWarnings"] == ["brain_dirty"]
    assert res["brain"]["commit"] == local                      # identical to the clean case
    assert json.loads(Path(res["brainTrace"]).read_text())["commit"] == local
    assert (Path(res["brainPath"]) / "index.md").read_text() == "# local only\n"


def test_i16_detached_worktree_per_story(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path / "data"))
    repo, brain, ws, c1 = _setup_git_brain(tmp_path)
    r1 = build_agent_workspace("X", "X-1", branch="feat/X-1")
    r2 = build_agent_workspace("X", "X-2", branch="feat/X-2")
    w1, w2 = Path(r1["brainPath"]), Path(r2["brainPath"])
    assert w1 == tmp_path / "_wt" / "brain" / "X-1" and w2 == tmp_path / "_wt" / "brain" / "X-2"
    assert _git_out(w1, "rev-parse", "HEAD") == _git_out(w2, "rev-parse", "HEAD") == c1
    assert w1 in [Path(d) for d in r1["additionalDirectories"]]
    assert str(brain.resolve()) not in r1["additionalDirectories"]   # plus le clone partagé

    # le clone partagé bouge : les worktrees épinglés ne bougent pas
    _git(brain, "checkout", "-q", "-b", "other")
    (brain / "index.md").write_text("# c2\n")
    _git(brain, "add", "-A"); _git(brain, "commit", "-q", "-m", "c2")
    assert _git_out(w1, "rev-parse", "HEAD") == _git_out(w2, "rev-parse", "HEAD") == c1

    # relance : réutilisé, jamais un second worktree pour la même story
    again = build_agent_workspace("X", "X-1", branch="feat/X-1")
    assert again["brainPath"] == r1["brainPath"]
    assert len([e for e in wt.list_worktrees(brain) if "X-1" in e["path"]]) == 1


def test_i16_worktree_repositioned_when_the_pin_moves(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path / "data"))
    repo, brain, ws, c1 = _setup_git_brain(tmp_path)
    r1 = build_agent_workspace("X", "X-1", branch="feat/X-1")
    (brain / "index.md").write_text("# c2\n")
    _git(brain, "add", "-A"); _git(brain, "commit", "-q", "-m", "c2")
    c2 = _git_out(brain, "rev-parse", "HEAD")
    r2 = build_agent_workspace("X", "X-1", branch="feat/X-1")
    assert r2["brainPath"] == r1["brainPath"] and r2["brain"]["commit"] == c2
    assert _git_out(Path(r2["brainPath"]), "rev-parse", "HEAD") == c2
    assert len([e for e in wt.list_worktrees(brain) if "X-1" in e["path"]]) == 1


def test_i17_brain_denied_to_write_with_and_without_role(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path / "data"))
    repo, brain, ws, c1 = _setup_git_brain(tmp_path)
    for agent in (None, "deployer"):
        res = build_agent_workspace("X", "X-1", branch="feat/X-1", agent=agent)
        perms = json.loads((Path(res["workspace"]) / ".claude" / "settings.json").read_text())["permissions"]
        path = res["brainPath"]
        assert f"Edit(/{path}/**)" in perms["deny"] and f"Write(/{path}/**)" in perms["deny"]
        for rule in perms["deny"][-2:]:
            assert rule.split("(", 1)[1].startswith("//")        # forme absolue
        assert not [d for d in perms["deny"] if d.startswith(("Read(", "Glob(", "Grep("))]
        assert path in perms["additionalDirectories"]
        assert (Path(path) / "index.md").read_text() == "# c1\n"


def test_i18_trace_in_the_output_and_in_a_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path / "data"))
    repo, brain, ws, c1 = _setup_git_brain(tmp_path)
    res = build_agent_workspace("X", "X-1", branch="feat/X-1")
    expected = {"repo": str(brain.resolve()), "branch": "main", "commit": c1}
    assert tuple(res["brain"]) == BRAIN_REF_FIELDS and res["brain"] == expected
    trace = json.loads(Path(res["brainTrace"]).read_text())
    assert trace == expected and Path(res["brainTrace"]).parent == Path(res["workspace"])
    assert len(trace["commit"]) == 40


def test_i19_shared_clone_never_written(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path / "data"))
    repo, brain, ws, c1 = _setup_git_brain(tmp_path)
    before = (_git_out(brain, "rev-parse", "HEAD"), _git_out(brain, "branch", "--show-current"),
              _git_out(brain, "status", "--porcelain"))
    build_agent_workspace("X", "X-1", branch="feat/X-1")
    clean_workspace("X", "X-1", branch="feat/X-1")
    after = (_git_out(brain, "rev-parse", "HEAD"), _git_out(brain, "branch", "--show-current"),
             _git_out(brain, "status", "--porcelain"))
    assert before == after


def test_i20_clean_removes_the_brain_worktree(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path / "data"))
    repo, brain, ws, c1 = _setup_git_brain(tmp_path)
    res = build_agent_workspace("X", "X-1", branch="feat/X-1")
    path = res["brainPath"]
    assert any(Path(e["path"]) == Path(path) for e in wt.list_worktrees(brain))
    out = clean_workspace("X", "X-1", branch="feat/X-1")
    assert out["brain"] == {"path": path, "removed": True}
    assert not Path(path).exists()
    assert not any(Path(e["path"]) == Path(path) for e in wt.list_worktrees(brain))
    assert _git_out(brain, "rev-parse", "HEAD") == c1


def test_brain_not_git_falls_back_and_says_so(tmp_path, monkeypatch):
    """Brain hors git : le dossier tel quel, l'avertissement existant, et un commit nul."""
    repo, brain, ws = _setup(tmp_path, with_skill=False)
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    cli.main(["create-epic", "X-E", "e"]); cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app"])
    res = build_agent_workspace("X", "X-1", branch="feat/X-1")
    assert res["brainPath"] == str(brain.resolve()) and res["brain"]["commit"] is None
    assert res["brainWarnings"] == ["brain_not_git"]
    assert not (tmp_path / "_wt" / "brain").exists()


def test_brain_not_declared_is_reported(tmp_path, monkeypatch):
    repo, brain, ws = _setup(tmp_path, with_skill=False)
    cfg = json.loads((ws / "sdlc.config.json").read_text())
    cfg.pop("brain")
    (ws / "sdlc.config.json").write_text(json.dumps(cfg))
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    cli.main(["create-epic", "X-E", "e"]); cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app"])
    res = build_agent_workspace("X", "X-1", branch="feat/X-1")
    assert res["brainWarnings"] == ["brain_not_declared"] and res["brainPath"] is None
    assert res["brain"] == {"repo": None, "branch": None, "commit": None}


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


def test_agent_permissions_injected(tmp_path, monkeypatch):
    """--agent injecte permissions.allow (rôle) + deny (partagé) du manifest dans la bulle."""
    import json as _json
    repo, brain, ws = _setup(tmp_path, with_skill=False)
    # ajoute un bloc permissions au manifest du projet de test
    cfgp = ws / "sdlc.config.json"
    cfg = _json.loads(cfgp.read_text())
    cfg["permissions"] = {"deny": ["Bash(rm -rf:*)"],
                          "agents": {"deployer": {"allow": ["Bash(python3:*)", "Bash(kubectl:*)"]}}}
    cfgp.write_text(_json.dumps(cfg))
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    cli.main(["create-epic", "X-E", "e"]); cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app"])

    res = build_agent_workspace("X", "X-1", branch="feat/X-1", agent="deployer")
    settings = _json.loads((Path(res["workspace"]) / ".claude" / "settings.json").read_text())
    perms = settings["permissions"]
    assert "Bash(python3:*)" in perms["allow"] and "Bash(kubectl:*)" in perms["allow"]
    brain_deny = [f"Edit(/{res['brainPath']}/**)", f"Write(/{res['brainPath']}/**)"]
    assert perms["deny"] == ["Bash(rm -rf:*)", *brain_deny]
    assert perms["additionalDirectories"]                 # toujours présent
    # sans --agent : pas d'allow, mais le brain reste interdit en écriture (I17)
    res2 = build_agent_workspace("X", "X-1", branch="feat/X-1")
    s2 = _json.loads((Path(res2["workspace"]) / ".claude" / "settings.json").read_text())
    assert "allow" not in s2["permissions"]
    assert s2["permissions"]["deny"] == brain_deny
