"""sample-proj-sdlc-local tooling — cœur déterministe du SDLC local « Harry ».

Board-agnostique : la state-machine des statuts, le DAG des stories et le
workspace .md sont la source de vérité ; un `Board` (Trello / Planner / cockpit /
Fake) n'est qu'un miroir enfichable. 100 % stdlib → testable offline.

Cadrage : docs/PRD.md
"""

from .status import Status, PIPELINE, ALLOWED, InvalidTransition, validate_transition
from .graph import topo_order, next_actionable, CycleError
from .board import Board, FakeBoard, TrelloBoard
from .workspace import Workspace
from .service import Sdlc

__all__ = [
    "Status", "PIPELINE", "ALLOWED", "InvalidTransition", "validate_transition",
    "topo_order", "next_actionable", "CycleError",
    "Board", "FakeBoard", "TrelloBoard",
    "Workspace", "Sdlc",
]
