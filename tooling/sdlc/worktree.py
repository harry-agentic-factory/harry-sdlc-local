"""Cycle de vie des **git worktrees** par ticket (isolation du code pour les agents autonomes).

Règle (cf. worktree-paths) : chemin **déterministe** `<parent>/_wt/<repo>/<branche-slug>`,
**create-or-reuse** (git interdit un 2ᵉ checkout d'une même branche → on réutilise), et
**remove au merge** sur la branche de référence (`refBranch` du manifest).

Un worktree = **1 branche = 1 ticket**, réutilisé par tous les agents du ticket ; supprimé une seule
fois, quand la branche est mergée sur `refBranch`. `remove` ne détruit **pas** les commits (ils vivent
dans le `.git` commun) → aucune perte, pas d'archivage.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def slug(branch: str) -> str:
    """`feat/HIA-1-x` → `feat-HIA-1-x` (nom de dossier sûr)."""
    return branch.replace("/", "-")


def worktree_path(repo: str | Path, branch: str) -> Path:
    """`<parent>/_wt/<repo>/<branche-slug>` — sibling du repo, hors du repo (pas de .gitignore)."""
    r = Path(repo).resolve()
    return r.parent / "_wt" / r.name / slug(branch)


def _git(repo: str | Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _git_ok(repo: str | Path, *args: str) -> bool:
    return _git(repo, *args).returncode == 0


def branch_exists(repo: str | Path, branch: str) -> bool:
    return _git_ok(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")


def list_worktrees(repo: str | Path) -> list[dict]:
    """Parse `git worktree list --porcelain` → [{path, branch}]."""
    out = _git(repo, "worktree", "list", "--porcelain").stdout
    entries: list[dict] = []
    cur: dict = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": line[len("worktree "):]}
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].removeprefix("refs/heads/")
        elif line == "" and cur:
            entries.append(cur); cur = {}
    if cur:
        entries.append(cur)
    return entries


def find_worktree_for_branch(repo: str | Path, branch: str) -> str | None:
    for e in list_worktrees(repo):
        if e.get("branch") == branch:
            return e["path"]
    return None


def ensure_worktree(repo: str | Path, branch: str, base: str | None = None) -> dict:
    """Create-or-reuse le worktree du ticket. Retourne {path, reused, created_branch}.

    - branche déjà checkoutée dans un worktree → **réutilise** ce chemin (git interdirait un 2ᵉ).
    - branche existe mais pas sortie → `worktree add <path> <branch>`.
    - branche absente → `worktree add -b <branch> <path> <base>` (base requise, défaut HEAD).
    """
    repo = Path(repo).resolve()
    existing = find_worktree_for_branch(repo, branch)
    if existing:
        return {"path": existing, "reused": True, "created_branch": False}

    path = worktree_path(repo, branch)
    path.parent.mkdir(parents=True, exist_ok=True)
    created_branch = False
    if branch_exists(repo, branch):
        cp = _git(repo, "worktree", "add", str(path), branch)
    else:
        cp = _git(repo, "worktree", "add", "-b", branch, str(path), base or "HEAD")
        created_branch = True
    if cp.returncode != 0:
        raise RuntimeError(f"git worktree add a échoué ({repo}, {branch}): {cp.stderr.strip()}")
    return {"path": str(path), "reused": False, "created_branch": created_branch}


def is_merged(repo: str | Path, branch: str, ref: str) -> bool:
    """`branch` est-elle intégrée dans `ref` ? (ses commits sont ancêtres de `ref`)."""
    return _git_ok(repo, "merge-base", "--is-ancestor", branch, ref)


def remove_worktree(repo: str | Path, branch: str, *, delete_branch: bool = False,
                    ref: str | None = None, force: bool = False) -> dict:
    """Retire le worktree de `branch`. Si `delete_branch`, supprime aussi la branche via
    `git branch -d` (refuse si non mergée = garde-fou) ; si `ref` donné, vérifie l'intégration d'abord.
    """
    repo = Path(repo).resolve()
    path = find_worktree_for_branch(repo, branch) or str(worktree_path(repo, branch))
    result = {"removed": False, "branch_deleted": False, "path": path}

    if ref is not None and delete_branch and not is_merged(repo, branch, ref):
        result["note"] = f"branche non mergée dans {ref} → rien supprimé"
        return result

    if Path(path).exists():
        args = ["worktree", "remove", path] + (["--force"] if force else [])
        cp = _git(repo, *args)
        if cp.returncode != 0:
            raise RuntimeError(f"git worktree remove a échoué: {cp.stderr.strip()}")
        result["removed"] = True
    _git(repo, "worktree", "prune")

    if delete_branch:
        cp = _git(repo, "branch", "-d", branch)   # -d minuscule = refuse si non mergée
        result["branch_deleted"] = cp.returncode == 0
        if cp.returncode != 0:
            result["note"] = cp.stderr.strip()
    return result


def cleanup_if_merged(repo: str | Path, branch: str, ref: str) -> dict:
    """Retire worktree + branche **seulement si** `branch` est mergée dans `ref` (sinon no-op)."""
    if not is_merged(repo, branch, ref):
        return {"removed": False, "branch_deleted": False,
                "note": f"non mergée dans {ref} → conservée"}
    return remove_worktree(repo, branch, delete_branch=True, ref=ref)
