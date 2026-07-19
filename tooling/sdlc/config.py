"""Résolution du workspace SDLC + lecture de `sdlc.config.json`.

Ordre : env `SDLC_WORKSPACE` → registre `~/.claude/sdlc/projects.json` (par préfixe)
→ remontée de l'arbo à la recherche d'un `sdlc.config.json`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_ESCALATION = {
    "review": "auto", "deploy": "human-confirm",
    "recette": "auto-then-human", "nonreg": "human-on-fail",
}


def registry_path() -> Path:
    return Path.home() / ".claude" / "sdlc" / "projects.json"


def resolve_workspace(project: str | None = None, start: str | Path | None = None) -> Path:
    env = os.environ.get("SDLC_WORKSPACE")
    if env:
        return Path(env)

    if project:
        reg = registry_path()
        if reg.exists():
            data = json.loads(reg.read_text())
            p = data.get("projects", {}).get(project, {}).get("workspace")
            if p:
                return Path(p)

    cur = Path(start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        if (d / "sdlc.config.json").exists():
            return d
        if (d / "sample-proj-sdlc-local" / "sdlc.config.json").exists():
            return d / "sample-proj-sdlc-local"
    raise FileNotFoundError(
        "workspace SDLC introuvable (env SDLC_WORKSPACE, registre projects.json, "
        "ou un sdlc.config.json en remontant l'arbo)"
    )


def load_config(workspace: str | Path) -> dict:
    p = Path(workspace) / "sdlc.config.json"
    cfg = json.loads(p.read_text()) if p.exists() else {}
    cfg.setdefault("escalation", dict(DEFAULT_ESCALATION))
    cfg.setdefault("board", {"type": "null"})
    return cfg
