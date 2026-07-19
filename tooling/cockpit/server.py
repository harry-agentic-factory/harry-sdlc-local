"""Cockpit REST+static (FastAPI, optionnel — `pip install fastapi uvicorn`).

    HIA_SDLC_WORKSPACE=/…/hia-sdlc python3 -m cockpit.server   # http://localhost:8787
"""
from __future__ import annotations

from pathlib import Path

from sdlc.board import NullBoard
from sdlc.config import resolve_workspace
from sdlc.service import Sdlc
from sdlc.workspace import Workspace

from .data import build_board


def _sdlc() -> Sdlc:
    return Sdlc(Workspace(resolve_workspace()), NullBoard())


def create_app():  # pragma: no cover - nécessite fastapi
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="hia-sdlc cockpit")
    index = (Path(__file__).parent / "index.html").read_text()

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return index

    @app.get("/api/board")
    def board() -> dict:
        return build_board(_sdlc())

    @app.get("/api/ticket/{story}")
    def ticket(story: str) -> dict:
        return _sdlc().get_ticket(story)

    return app


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8787)
