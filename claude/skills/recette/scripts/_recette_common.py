"""Helpers scripts recette. Stdlib only. Le **token n'est JAMAIS affiché** ni passé en argv (header via
fichier `@` en `chmod 600`). Sorties = JSON compact filtré (contexte maigre)."""
from __future__ import annotations

import json
import sys


def build_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def filter_obj(obj, fields: str | None):
    """Réduit un dict (ou chaque dict d'une liste) aux `fields` (CSV) → sortie < ~2 Ko."""
    if not fields:
        return obj
    keys = [f.strip() for f in fields.split(",") if f.strip()]
    pick = lambda d: {k: d.get(k) for k in keys} if isinstance(d, dict) else d
    return [pick(x) for x in obj] if isinstance(obj, list) else pick(obj)


def emit(o: dict) -> None:
    print(json.dumps(o, ensure_ascii=False))


def die(msg: str) -> None:
    emit({"ok": False, "error": msg})
    sys.exit(1)
