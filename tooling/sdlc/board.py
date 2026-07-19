"""Port `Board` : miroir enfichable du backlog + statuts.

La vérité reste le workspace .md + la state-machine. Un board (Trello / Planner /
cockpit) n'est qu'une projection une-voie. `FakeBoard` sert aux tests offline ;
`TrelloBoard` est l'adaptateur à brancher quand un MCP Trello sera connecté.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Board(Protocol):
    def upsert_epic(self, epic_id: str, title: str) -> None: ...
    def upsert_story(self, story_id: str, epic_id: str, title: str) -> None: ...
    def set_status(self, story_id: str, status: str) -> None: ...


class FakeBoard:
    """Board en mémoire pour les tests : enregistre chaque appel."""

    def __init__(self) -> None:
        self.epics: dict[str, str] = {}
        self.stories: dict[str, tuple[str, str]] = {}
        self.status: dict[str, str] = {}
        self.calls: list[tuple] = []

    def upsert_epic(self, epic_id: str, title: str) -> None:
        self.epics[epic_id] = title
        self.calls.append(("epic", epic_id, title))

    def upsert_story(self, story_id: str, epic_id: str, title: str) -> None:
        self.stories[story_id] = (epic_id, title)
        self.calls.append(("story", story_id, epic_id, title))

    def set_status(self, story_id: str, status: str) -> None:
        self.status[story_id] = status
        self.calls.append(("status", story_id, status))


class NullBoard:
    """Aucun miroir (mode 100 % local, seulement les .md)."""

    def upsert_epic(self, epic_id: str, title: str) -> None: ...
    def upsert_story(self, story_id: str, epic_id: str, title: str) -> None: ...
    def set_status(self, story_id: str, status: str) -> None: ...


class TrelloBoard:
    """Adaptateur Trello — board=projet, list=statut, card=story.

    TODO: implémenter via un MCP Trello (non connecté dans la session actuelle).
    Mapping prévu : chaque `Status` = une liste Trello ; `set_status` déplace la
    carte ; la description de la carte pointe vers les .md de `hia-sdlc/`.
    """

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError(
            "Trello MCP non connecté — l'ajouter via `claude mcp` (clé/token Trello), "
            "puis implémenter cet adaptateur. Cf. README."
        )
