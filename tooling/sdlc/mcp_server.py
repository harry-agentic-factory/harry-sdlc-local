"""Serveur MCP `sdlc` — expose la façade aux agents (bus d'état partagé).

Prêt à brancher : nécessite le paquet `mcp` (`pip install mcp`). Tant qu'il n'est
pas installé, l'import échoue proprement ; le CLI (`sdlc.cli`) reste utilisable.

Lancement (une fois `mcp` installé) :
    HIA_SDLC_WORKSPACE=/…/hia-sdlc python3 -m sdlc.mcp_server
Puis déclarer le serveur dans la config MCP de Claude Code.
"""
from __future__ import annotations

import dataclasses

from .board import NullBoard
from .config import resolve_workspace
from .service import Sdlc
from .workspace import Workspace


def _sdlc() -> Sdlc:
    return Sdlc(Workspace(resolve_workspace()), NullBoard())


def build_server():  # pragma: no cover - nécessite le paquet mcp
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("sdlc")

    @mcp.tool()
    def sdlc_get_ticket(story: str) -> dict:
        """Réhydrate tout le contexte d'un ticket en un appel."""
        return _sdlc().get_ticket(story)

    @mcp.tool()
    def sdlc_list_backlog(status: str | None = None) -> dict:
        return {"tickets": [dataclasses.asdict(t) for t in _sdlc().list_backlog(status)]}

    @mcp.tool()
    def sdlc_next(epic: str) -> dict:
        return {"epic": epic, "next": _sdlc().next(epic)}

    @mcp.tool()
    def sdlc_create_ticket(epic: str, story: str, title: str,
                           deps: list[str] | None = None, repos: list[str] | None = None) -> dict:
        return dataclasses.asdict(_sdlc().create_ticket(epic, story, title, deps or [], repos or []))

    @mcp.tool()
    def sdlc_set_status(story: str, status: str) -> dict:
        return dataclasses.asdict(_sdlc().set_status(story, status))

    @mcp.tool()
    def sdlc_link_artifact(story: str, kind: str, path: str) -> dict:
        return dataclasses.asdict(_sdlc().link_artifact(story, kind, path))

    return mcp


if __name__ == "__main__":  # pragma: no cover
    build_server().run()
