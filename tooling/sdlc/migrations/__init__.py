"""Migrations de schéma de la **data** SDLC (repos `<projet>-sdlc-local`).

Un upgrade de l'engine peut faire évoluer la data (champ `status.json`, état de la state-machine,
layout…). Chaque migration = `(from_version, to_version, fn(workspace: Path) -> None)`, **idempotente**.
`apply_migrations` lit `schemaVersion` (dans `sdlc.config.json`), applique la chaîne en attente, bumpe.

Baseline **0.1.0** = aucune migration. Ajouter une migration = ajouter un tuple à `MIGRATIONS` (et bumper
`VERSION` de l'engine). La data étant git-trackée, un mauvais upgrade se `git revert`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

# (from_version, to_version, fn) — chaînées. Ex. futur : ("0.1.0", "0.2.0", _m_add_field)
MIGRATIONS: list[tuple[str, str, Callable[[Path], None]]] = []

# Version de schéma DATA cible (découplée de la VERSION d'engine : n'avance QUE si migration data).
LATEST_SCHEMA = MIGRATIONS[-1][1] if MIGRATIONS else "0.1.0"


def engine_version() -> str:
    v = Path(__file__).resolve().parents[3] / "VERSION"   # tooling/sdlc/migrations -> racine engine
    return v.read_text().strip() if v.exists() else "0.1.0"


def _config_path(workspace: str | Path) -> Path:
    return Path(workspace) / "sdlc.config.json"


def data_schema_version(workspace: str | Path) -> str:
    p = _config_path(workspace)
    return json.loads(p.read_text()).get("schemaVersion", "0.1.0") if p.exists() else "0.1.0"


def apply_migrations(workspace: str | Path) -> dict:
    ws = Path(workspace)
    cur = data_schema_version(ws)
    applied: list[str] = []
    changed = True
    while changed:
        changed = False
        for frm, to, fn in MIGRATIONS:
            if frm == cur:
                fn(ws)
                cur = to
                applied.append(to)
                changed = True
    p = _config_path(ws)
    if p.exists():
        data = json.loads(p.read_text())
        data["schemaVersion"] = cur
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return {"engine": engine_version(), "schemaVersion": cur, "applied": applied,
            "up_to_date": cur == LATEST_SCHEMA}
