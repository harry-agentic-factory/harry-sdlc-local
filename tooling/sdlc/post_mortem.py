"""Store d'**items de post-mortem** : chaque commande/agent consigne une dette, un learning,
un incident, un point sécu ou une suggestion Brain — au fil de l'eau, sans attendre la clôture d'épic.

Stockage **append-only** `<workspace>/post-mortem.jsonl` : chaque ligne = un *snapshot* d'item.
L'état courant est **reconstruit** à la lecture (dernier snapshot par `id` gagne) → robuste aux
appends concurrents de plusieurs agents. `add` = nouvel id + append ; statuer/convertir = append
d'un snapshot mis à jour (rien n'est réécrit en place).

Le `workspace` est le **repo data** du projet (résolu comme les autres commandes, via `config.resolve_workspace`).
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("debt", "learning", "incident", "security", "brain")
SEVERITIES = ("low", "medium", "high")
STATUSES = ("open", "triaged", "ticketed", "brain", "wontfix")
BRAIN_MARKER = "brain-propale"


@dataclass
class PMItem:
    id: str
    agent: str
    kind: str
    text: str
    epic: str | None = None
    story: str | None = None
    severity: str = "medium"
    status: str = "open"
    target: str | None = None
    created_at: str = ""
    updated_at: str = ""


def _now_iso(now: str | None = None) -> str:
    return now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _title_from_text(text: str, limit: int = 80) -> str:
    """Titre de story de dette = 1re ligne non vide du `text`, tronquée."""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), text.strip())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def _next_story_id(ws, epic: str) -> str:
    """Prochain id de story libre dans l'épic (`<EPIC>-<n>`), sans collision."""
    existing = {t.id for t in ws.all_tickets() if t.epic == epic}
    n = 1
    while f"{epic}-{n}" in existing:
        n += 1
    return f"{epic}-{n}"


class PostMortemStore:
    """Journal append-only + reconstruction last-wins. Toutes les écritures = `_append`."""

    FILENAME = "post-mortem.jsonl"

    def __init__(self, workspace: str | Path) -> None:
        self.root = Path(workspace)
        self.path = self.root / self.FILENAME

    # --- I/O bas niveau ---
    def _snapshots(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def _current(self) -> dict[str, PMItem]:
        """État courant : dernier snapshot par `id` gagne (ordre du fichier = ordre des appends)."""
        cur: dict[str, PMItem] = {}
        for snap in self._snapshots():
            cur[snap["id"]] = PMItem(**snap)
        return cur

    def _append(self, item: PMItem) -> PMItem:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(dataclasses.asdict(item), ensure_ascii=False) + "\n")
        return item

    def _next_id(self) -> str:
        nums = [int(i[3:]) for i in self._current() if i.startswith("PM-") and i[3:].isdigit()]
        return f"PM-{(max(nums) + 1) if nums else 1:03d}"

    # --- lecture ---
    def get(self, item_id: str) -> PMItem:
        item = self._current().get(item_id)
        if item is None:
            raise KeyError(f"item de post-mortem introuvable: {item_id}")
        return item

    def list(self, *, epic: str | None = None, story: str | None = None,
             agent: str | None = None, kind: str | None = None,
             status: str | None = None) -> list[PMItem]:
        items = sorted(self._current().values(), key=lambda i: i.id)
        filters = {"epic": epic, "story": story, "agent": agent, "kind": kind, "status": status}
        return [it for it in items
                if all(v is None or getattr(it, k) == v for k, v in filters.items())]

    # --- écriture ---
    def add(self, *, agent: str, kind: str, text: str, epic: str | None = None,
            story: str | None = None, severity: str = "medium",
            now: str | None = None) -> PMItem:
        if kind not in KINDS:
            raise ValueError(f"kind invalide « {kind} » — attendu : {', '.join(KINDS)}")
        severity = severity or "medium"
        if severity not in SEVERITIES:
            raise ValueError(f"severity invalide « {severity} » — attendu : {', '.join(SEVERITIES)}")
        if not (text and text.strip()):
            raise ValueError("text vide")
        ts = _now_iso(now)
        return self._append(PMItem(
            id=self._next_id(), agent=agent, kind=kind, text=text,
            epic=epic, story=story, severity=severity, status="open",
            target=None, created_at=ts, updated_at=ts,
        ))

    def _update(self, item: PMItem, *, status: str, target: str | None,
                now: str | None = None) -> PMItem:
        """Append d'un snapshot mis à jour (created_at préservé, updated_at bumpé)."""
        if status not in STATUSES:
            raise ValueError(f"status invalide « {status} » — attendu : {', '.join(STATUSES)}")
        updated = dataclasses.replace(
            item, status=status,
            target=target if target is not None else item.target,
            updated_at=_now_iso(now),
        )
        return self._append(updated)

    def set_status(self, item_id: str, status: str, *, target: str | None = None,
                   now: str | None = None) -> PMItem:
        """Statuer sur un item (open|triaged|wontfix côté CLI). Append d'un snapshot."""
        return self._update(self.get(item_id), status=status, target=target, now=now)

    def to_ticket(self, item_id: str, sdlc, *, debt_epic: str,
                  repos: list[str] | None = None, now: str | None = None) -> dict:
        """Convertit l'item en **story de dette** dans `debt_epic` (via `Sdlc.create_ticket`),
        puis passe l'item en `ticketed` avec `target=<story-id>`."""
        item = self.get(item_id)
        ws = sdlc.ws
        if not ws.epic_dir(debt_epic).exists():
            sdlc.create_epic(debt_epic, f"{debt_epic} — dette")
        story_id = _next_story_id(ws, debt_epic)
        sdlc.create_ticket(debt_epic, story_id, _title_from_text(item.text),
                           repos=repos or [])
        self._update(item, status="ticketed", target=story_id, now=now)
        return {"id": item.id, "ticket": story_id}

    def to_brain(self, item_id: str, *, now: str | None = None) -> dict:
        """Passe l'item en `brain` (target = marqueur) et **suggère** une entrée à ajouter dans
        `<EPIC>/brain-update-propale.md`. N'édite PAS le Brain (read-only par défaut)."""
        item = self.get(item_id)
        self._update(item, status="brain", target=BRAIN_MARKER, now=now)
        where = f"{item.epic}/brain-update-propale.md" if item.epic else "brain-update-propale.md"
        suggestion = (f"- [{item.id}] ({item.kind}/{item.severity}) {_title_from_text(item.text)} "
                      f"→ à répercuter dans {where}")
        return {"id": item.id, "status": "brain", "suggestion": suggestion}
