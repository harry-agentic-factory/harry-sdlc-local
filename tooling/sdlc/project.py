"""Cycle de vie des projets SDLC : scaffolding d'un repo **data** `<projet>-sdlc-local`
+ enregistrement dans le registre `~/.claude/sdlc/projects.json`.

C'est la « commande plateforme » pour ajouter/initialiser un projet (SAMPLE, OtherProject…) sans étapes manuelles.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import registry_path
from .migrations import LATEST_SCHEMA

DEFAULT_ESCALATION = {
    "review": "auto", "deploy": "human-confirm",
    "recette": "auto-then-human", "nonreg": "human-on-fail",
}


def list_projects() -> dict:
    reg = registry_path()
    return json.loads(reg.read_text()).get("projects", {}) if reg.exists() else {}


def register_project(prefix: str, workspace: str | Path) -> dict:
    reg = registry_path()
    reg.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(reg.read_text()) if reg.exists() else {"projects": {}}
    data.setdefault("projects", {})[prefix] = {"workspace": str(Path(workspace).expanduser().resolve())}
    reg.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return data["projects"][prefix]


def init_project(prefix: str, path: str | Path, repos: list[str] | None = None,
                 git: bool = True) -> dict:
    """Crée le repo data (dossier + sdlc.config.json + README + git init) et l'enregistre. Idempotent-safe :
    refuse si un sdlc.config.json existe déjà (pour ne pas écraser une data)."""
    ws = Path(path).expanduser().resolve()
    cfg = ws / "sdlc.config.json"
    if cfg.exists():
        raise FileExistsError(f"data déjà initialisée : {cfg}")
    ws.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({
        "prefix": prefix,
        "workspace": ".",
        "reposRoot": None,
        "_note_reposRoot": "base dir des repos ; si posé, les repos ci-dessous se résolvent par <reposRoot>/<nom>",
        "repos": {name: None for name in (repos or [])},
        "roles": {},
        "_note_roles": "name -> role (code | gitops | knowledge | ...) ; optionnel",
        "brain": None,
        "refBranch": "main",
        "_note_refBranch": "branche de référence (cible de merge -> cleanup worktree)",
        "deploy": {},
        "_note_deploy": "{ skill, ci, gitops } ; lu par l'agent deployer via `sdlc config`",
        "credentials": {"source": "host"},
        "_note_credentials": "host = creds ambiantes opérateur (curl -s -n/.netrc, ~/.kube/config, gh/glab) ; jamais lues. Futur: 'service' = creds scopées.",
        "board": {"type": "null", "_note": "null | fake | trello | planner"},
        "escalation": dict(DEFAULT_ESCALATION),
        "schemaVersion": LATEST_SCHEMA,
    }, indent=2, ensure_ascii=False) + "\n")
    _write_if_absent(ws / "README.md",
                     f"# {ws.name} — data SDLC ({prefix})\n\n"
                     f"Repo **DATA** opéré par l'engine `harry-sdlc-local`. Tickets `{prefix}-*/`.\n")
    _write_if_absent(ws / ".gitignore", "*.db\n__pycache__/\n.pytest_cache/\n")
    if git and not (ws / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(ws), check=False)
    register_project(prefix, ws)
    return {"prefix": prefix, "workspace": str(ws), "repos": repos or [],
            "schemaVersion": LATEST_SCHEMA, "registered": True}


def _write_if_absent(p: Path, content: str) -> None:
    if not p.exists():
        p.write_text(content)
