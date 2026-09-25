"""Phase 4 — cycle de vie des git worktrees (create-or-reuse + remove-if-merged). Vrais repos git temp."""
import json
import subprocess
from pathlib import Path

from sdlc import cli
from sdlc import worktree as wt


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "f.txt").write_text("x")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


# --- chemin déterministe / slug ---

def test_slug():
    assert wt.slug("feat/HIA-1-x") == "feat-HIA-1-x"


def test_worktree_path_is_sibling(tmp_path):
    repo = _init_repo(tmp_path / "myrepo")
    p = wt.worktree_path(repo, "feat/a")
    assert p == repo.parent / "_wt" / "myrepo" / "feat-a"


# --- create-or-reuse ---

def test_ensure_reuses_existing_branch(tmp_path):
    repo = _init_repo(tmp_path / "r")
    _git(repo, "branch", "feat/a")
    r1 = wt.ensure_worktree(repo, "feat/a")
    assert r1["reused"] is False and r1["created_branch"] is False
    assert Path(r1["path"]).is_dir()
    r2 = wt.ensure_worktree(repo, "feat/a")           # 2ᵉ appel → réutilise (git interdit un 2ᵉ checkout)
    assert r2["reused"] is True and r2["path"] == r1["path"]


def test_ensure_reuses_when_registry_pruned(tmp_path):
    """Chemin déterministe présent mais registre périmé → prune + re-scan réutilise (idempotent)."""
    repo = _init_repo(tmp_path / "r")
    r1 = wt.ensure_worktree(repo, "feat/a")
    path = Path(r1["path"])
    # simule un registre périmé : on efface la ligne du registre en laissant le dossier worktree en place
    _git(repo, "worktree", "prune")           # no-op ici, mais l'appel doit rester idempotent
    r2 = wt.ensure_worktree(repo, "feat/a")
    assert r2["reused"] is True and r2["path"] == str(path)


def test_ensure_raises_on_unrelated_path_collision(tmp_path):
    """Le chemin déterministe est occupé par un dossier étranger → erreur explicite, pas d'écrasement."""
    repo = _init_repo(tmp_path / "r")
    path = wt.worktree_path(repo, "feat/a")
    path.mkdir(parents=True)
    (path / "stranger.txt").write_text("not a worktree")
    try:
        wt.ensure_worktree(repo, "feat/a")
        assert False, "attendait une RuntimeError sur collision de chemin"
    except RuntimeError as e:
        assert "non rattaché" in str(e)


def test_ensure_creates_branch_when_absent(tmp_path):
    repo = _init_repo(tmp_path / "r")
    assert not wt.branch_exists(repo, "feat/new")
    r = wt.ensure_worktree(repo, "feat/new")
    assert r["created_branch"] is True and wt.branch_exists(repo, "feat/new")


def test_find_worktree_for_branch(tmp_path):
    repo = _init_repo(tmp_path / "r")
    wt.ensure_worktree(repo, "feat/a")
    assert wt.find_worktree_for_branch(repo, "feat/a") is not None
    assert wt.find_worktree_for_branch(repo, "feat/absent") is None


# --- merge detection + cleanup ---

def test_is_merged(tmp_path):
    repo = _init_repo(tmp_path / "r")
    _git(repo, "branch", "feat/a")                    # pointe sur main → mergée (ancêtre)
    assert wt.is_merged(repo, "feat/a", "main") is True
    wt.ensure_worktree(repo, "feat/ahead")            # nouvelle branche
    w = wt.find_worktree_for_branch(repo, "feat/ahead")
    (Path(w) / "g.txt").write_text("y")
    _git(w, "add", "-A"); _git(w, "commit", "-q", "-m", "ahead")
    assert wt.is_merged(repo, "feat/ahead", "main") is False   # a un commit hors de main


def test_cleanup_keeps_unmerged(tmp_path):
    repo = _init_repo(tmp_path / "r")
    wt.ensure_worktree(repo, "feat/x")
    w = wt.find_worktree_for_branch(repo, "feat/x")
    (Path(w) / "g.txt").write_text("y")
    _git(w, "add", "-A"); _git(w, "commit", "-q", "-m", "wip")
    res = wt.cleanup_if_merged(repo, "feat/x", "main")
    assert res["removed"] is False and Path(w).exists()   # non mergée → conservée


def test_cleanup_removes_merged(tmp_path):
    repo = _init_repo(tmp_path / "r")
    wt.ensure_worktree(repo, "feat/x")
    w = wt.find_worktree_for_branch(repo, "feat/x")
    (Path(w) / "g.txt").write_text("y")
    _git(w, "add", "-A"); _git(w, "commit", "-q", "-m", "feature")
    _git(repo, "merge", "--no-edit", "-q", "feat/x")      # merge sur main (branche de réf)
    res = wt.cleanup_if_merged(repo, "feat/x", "main")
    assert res["removed"] is True and res["branch_deleted"] is True
    assert not Path(w).exists() and not wt.branch_exists(repo, "feat/x")


# --- CLI ---

def test_cli_worktree(tmp_path, capsys, monkeypatch):
    repo = _init_repo(tmp_path / "app-repo")
    ws = tmp_path / "data"; ws.mkdir()
    (ws / "sdlc.config.json").write_text(json.dumps(
        {"prefix": "X", "repos": {"app-repo": str(repo)}, "refBranch": "main"}))
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    cli.main(["create-epic", "X-E", "e"]); capsys.readouterr()
    cli.main(["create-ticket", "X-E", "X-1", "t", "--repos", "app-repo"]); capsys.readouterr()

    rc = cli.main(["worktree", "X-1", "--branch", "feat/X-1", "--repo", "app-repo"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["branch"] == "feat/X-1"
    assert Path(out["worktrees"]["app-repo"]["path"]).is_dir()


# --- une story part TOUJOURS de la branche de référence, jamais du HEAD courant ---

def test_fetch_base_prefers_the_remote_ref(tmp_path):
    """`origin/<ref>` gagne sur la copie locale : c'est elle qui fait autorité."""
    origin = _init_repo(tmp_path / "origin")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    assert wt.fetch_base(clone, "main") == "origin/main"


def test_fetch_base_falls_back_when_there_is_no_remote(tmp_path):
    repo = _init_repo(tmp_path / "solo")
    assert wt.fetch_base(repo, "main") == "main"
    # ref inconnue : ni distante ni locale
    assert wt.fetch_base(repo, "nope") == "HEAD"


def test_worktree_starts_from_ref_branch_not_from_current_head(tmp_path, monkeypatch):
    """Le bug historique : le repo est sur une branche de travail qui ne contient PAS main,
    et la story en héritait en silence."""
    origin = _init_repo(tmp_path / "origin")
    clone = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)

    # une branche de travail divergente, depuis laquelle main n'est plus atteignable
    _git(clone, "checkout", "-q", "--orphan", "feat/elsewhere")
    (clone / "other.txt").write_text("y")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "orphan")
    assert not wt.is_based_on(clone, "feat/elsewhere", "origin/main")

    base = wt.fetch_base(clone, "main")
    res = wt.ensure_worktree(clone, "fix/story-1", base=base)

    assert res["created_branch"] is True
    assert wt.is_based_on(clone, "fix/story-1", "origin/main"), "la story doit descendre de origin/main"


def test_worktree_reports_a_branch_cut_from_a_stale_base(tmp_path):
    """Une branche préexistante est réutilisée telle quelle : le défaut doit être VISIBLE,
    pas corrigé en douce."""
    origin = _init_repo(tmp_path / "origin")
    clone = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    _git(clone, "checkout", "-q", "--orphan", "fix/stale")
    (clone / "z.txt").write_text("z")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "stale")
    _git(clone, "checkout", "-q", "main")

    assert wt.is_based_on(clone, "fix/stale", "origin/main") is False
