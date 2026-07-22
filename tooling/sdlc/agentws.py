"""Génère la **bulle scopée** d'un agent pour un ticket (Phase 3 — droits + isolation + skills).

Assemble ce que les autres phases ont posé :
- **worktrees** (Phase 4) : un code isolé par repo touché, sur la branche du ticket ;
- **settings.json** (`additionalDirectories`) : n'autorise QUE les worktrees + le brain + la data —
  plus de dépendance au workspace VS Code ni au home-grant global ;
- **skills projet** (2-tiers) : symlink de `<data>/skills/*` dans le `.claude/skills` de la bulle ;
- **identité** : `credentials.source` du manifest (héritée, cf. Phase 5).

Résultat : un dossier prêt pour un **lancement headless**, préfigurant le sandbox factory.
Le dossier est **déterministe et régénérable** (sibling des worktrees, hors de tout repo).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import worktree as wt
from .config import resolved_manifest
from .service import Sdlc
from .workspace import Workspace


def _base_dir(manifest: dict) -> Path:
    root = manifest.get("reposRoot") or str(Path(manifest["workspace"]).parent)
    return Path(root)


def agentws_path(manifest: dict, story: str) -> Path:
    return _base_dir(manifest) / "_agentws" / (manifest.get("prefix") or "PROJ") / story


def _link_project_skills(data_workspace: str | Path, skills_dir: Path) -> list[str]:
    """Symlinke `<data>/skills/<name>` → `<bulle>/.claude/skills/<name>` (skills spécifiques projet)."""
    src = Path(data_workspace) / "skills"
    linked: list[str] = []
    if not src.is_dir():
        return linked
    skills_dir.mkdir(parents=True, exist_ok=True)
    for d in sorted(src.iterdir()):
        if not d.is_dir():
            continue
        dst = skills_dir / d.name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(d.resolve())
        linked.append(d.name)
    return linked


def build_agent_workspace(project: str | None = None, story: str | None = None,
                          branch: str | None = None, agent: str | None = None,
                          workspace: str | Path | None = None) -> dict:
    """Crée/rafraîchit la bulle scopée du ticket. Idempotent (worktrees réutilisés, settings réécrit).
    `agent` : rôle (deployer/reviewer/…) → injecte `permissions.allow/deny` du manifest dans la bulle."""
    man = resolved_manifest(project, workspace)
    ws_root = man["workspace"]
    sdlc = Sdlc(Workspace(ws_root))
    ticket = sdlc.get_ticket(story)
    br = branch or ticket.get("branch")
    if not br:
        raise ValueError(f"aucune branche pour {story} (ticket.branch vide, passe branch=...)")

    # 1. worktrees (create-or-reuse) pour chaque repo touché résolu
    worktrees: dict[str, str] = {}
    for name in ticket.get("repos") or []:
        repo_path = man["repos"].get(name)
        if repo_path:
            worktrees[name] = wt.ensure_worktree(repo_path, br)["path"]

    # 2. additionalDirectories = worktrees + brain + data (scope minimal)
    add_dirs = list(worktrees.values())
    if man.get("brain"):
        add_dirs.append(man["brain"])
    add_dirs.append(str(Path(ws_root).resolve()))

    # 3. écrit la bulle : .claude/settings.json + skills projet
    bubble = agentws_path(man, story)
    claude = bubble / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    scratch = bubble / "scratch"                 # scripts/fichiers temp de l'agent (jamais /tmp)
    scratch.mkdir(parents=True, exist_ok=True)
    perms: dict = {"additionalDirectories": add_dirs}   # droits scopés
    mperm = man.get("permissions", {})
    if agent:                                    # allow/deny par agent-rôle (from manifest)
        allow = ((mperm.get("agents", {}) or {}).get(agent, {}) or {}).get("allow", [])
        if allow:
            perms["allow"] = allow
        if mperm.get("deny"):
            perms["deny"] = mperm["deny"]
    (claude / "settings.json").write_text(
        json.dumps({"permissions": perms}, indent=2, ensure_ascii=False) + "\n")
    skills = _link_project_skills(ws_root, claude / "skills")
    (bubble / "README.md").write_text(
        f"# Bulle agent — {story} ({man.get('prefix')})\n\n"
        f"Workspace scopé **régénérable** (`sdlc workspace {story}`). Branche `{br}`.\n"
        f"`additionalDirectories` = worktrees + brain + data. Skills projet : "
        f"{', '.join(skills) or '(aucun)'}.\n\n"
        f"`scratch/` : scripts/fichiers temp de l'agent (JAMAIS /tmp).\n")

    return {
        "story": story, "branch": br, "agent": agent, "workspace": str(bubble), "scratch": str(scratch),
        "worktrees": worktrees, "additionalDirectories": add_dirs, "permissions": perms,
        "projectSkills": skills, "credentials": man.get("credentials", {"source": "host"}),
    }


def clean_workspace(project: str | None = None, story: str | None = None,
                    branch: str | None = None, ref: str | None = None,
                    workspace: str | Path | None = None) -> dict:
    """Fin de vie du ticket : retire worktrees + branche **si mergée** sur `ref` (défaut `refBranch`),
    puis supprime la bulle régénérable. Partagé par la CLI (`worktree-clean`) et l'orchestrateur.
    """
    man = resolved_manifest(project, workspace)
    sdlc = Sdlc(Workspace(man["workspace"]))
    ticket = sdlc.get_ticket(story)
    br = branch or ticket.get("branch")
    if not br:
        raise ValueError(f"aucune branche pour {story} (ticket.branch vide, passe branch=...)")
    r = ref or man.get("refBranch") or "main"

    cleaned: dict[str, dict] = {}
    for name in ticket.get("repos") or []:
        repo_path = man["repos"].get(name)
        if repo_path:
            cleaned[name] = wt.cleanup_if_merged(repo_path, br, r)

    all_removed = all(c.get("removed") for c in cleaned.values()) if cleaned else True
    bubble = agentws_path(man, story)
    bubble_removed = False
    if all_removed and bubble.exists():       # tout est mergé/parti → la bulle n'a plus lieu d'être
        shutil.rmtree(bubble)
        bubble_removed = True
    return {"story": story, "branch": br, "ref": r, "cleaned": cleaned, "bubbleRemoved": bubble_removed}
