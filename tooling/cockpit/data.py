"""Mise en forme du read-model pour le cockpit (pur, sans I/O réseau → testable)."""
from __future__ import annotations

from sdlc.status import PIPELINE
from sdlc.service import Sdlc


def build_board(sdlc: Sdlc) -> dict:
    """Colonnes par statut + Inbox HITL (tickets en attente d'action humaine)."""
    columns: dict[str, list[dict]] = {s.value: [] for s in PIPELINE}
    for t in sdlc.list_backlog():
        card = {"id": t.id, "title": t.title, "epic": t.epic,
                "repos": t.repos, "status": t.status}
        columns.setdefault(t.status, []).append(card)

    # Inbox = ce qui attend l'humain : recette validée (accept démo) à venir.
    inbox = list(columns.get("recette_ok", []))
    counts = {k: len(v) for k, v in columns.items()}
    return {"columns": columns, "inbox": inbox, "counts": counts}
