"""Façade `Sdlc` : ce que le MCP `sdlc_*` exposera plus tard aux agents.

Orchestre workspace (.md, vérité) + state-machine (garde-fou) + board (miroir).
Toute la logique ici est déterministe → 100 % testable sans LLM.
"""
from __future__ import annotations

from .board import Board, NullBoard
from .graph import next_actionable
from .status import DONE_STATES, validate_transition
from .workspace import Ticket, Workspace


class Sdlc:
    def __init__(self, workspace: Workspace, board: Board | None = None) -> None:
        self.ws = workspace
        self.board = board or NullBoard()

    # --- création (/scope, /refine) ---
    def create_epic(self, epic: str, title: str) -> None:
        self.ws.create_epic(epic, title)
        self.board.upsert_epic(epic, title)

    def create_ticket(self, epic: str, story: str, title: str,
                      deps: list[str] | None = None, repos: list[str] | None = None) -> Ticket:
        t = Ticket(id=story, epic=epic, title=title, deps=deps or [], repos=repos or [])
        self.ws.create_story(t)
        self.board.upsert_story(story, epic, title)
        self.board.set_status(story, t.status)
        return t

    # --- lecture (sdlc_get_ticket / list_backlog / next) ---
    def get_ticket(self, story: str) -> dict:
        t = self.ws.load(story)
        return {
            "id": t.id, "epic": t.epic, "title": t.title, "status": t.status,
            "next": t.next_step, "deps": t.deps, "repos": t.repos,
            "branch": t.branch, "mr": t.mr, "artifacts": t.artifacts,
        }

    def list_backlog(self, status: str | None = None) -> list[Ticket]:
        tickets = self.ws.all_tickets()
        return [t for t in tickets if status is None or t.status == status]

    def next(self, epic: str) -> list[str]:
        tickets = [t for t in self.ws.all_tickets() if t.epic == epic]
        deps = {t.id: t.deps for t in tickets}
        statuses = {t.id: t.status for t in tickets}
        return next_actionable(deps, statuses, {s.value for s in DONE_STATES})

    # --- écriture d'état (sdlc_set_status / link_artifact) ---
    def set_status(self, story: str, new: str) -> Ticket:
        t = self.ws.load(story)
        validate_transition(t.status, new)   # garde-fou state-machine
        t.status = new
        self.ws.save(t)
        self.board.set_status(story, new)     # miroir
        return t

    def link_artifact(self, story: str, kind: str, path: str) -> Ticket:
        t = self.ws.load(story)
        t.artifacts[kind] = path
        self.ws.save(t)
        return t

    # --- rejet routé (gate humaine : review/recette KO → spec_func|spec_tech|implemented) ---
    def reject(self, story: str, to: str, note: str, actor: str = "humain",
               now: str | None = None) -> dict:
        """Consigne une décision de rejet dans le journal (append-only) PUIS route le ticket.
        `to` doit être une transition autorisée depuis le statut courant (garde-fou state-machine).
        N'écrase JAMAIS `acceptance.md` (preuve de recette) — la décision vit dans `journal.md`.
        """
        t = self.ws.load(story)
        validate_transition(t.status, to)              # garde-fou : rejet routé autorisé ?
        ts = now or _now_iso()
        frm = t.status
        self.ws.journal_add(
            story, f"## {ts} — REJECT  {frm} → {to}  (par: {actor})\n{note.strip()}")
        t.status = to
        self.ws.save(t)
        self.board.set_status(story, to)               # miroir
        return {"story": story, "from": frm, "to": to, "actor": actor, "note": note,
                "journal": str(self.ws.journal_path(story))}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
