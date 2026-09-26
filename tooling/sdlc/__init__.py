"""harry-sdlc — deterministic core of the local agentic SDLC engine.

Board agnostic: the status state machine, the story DAG and the Markdown workspace
are the source of truth; a `Board` (Trello / Planner / cockpit / fake) is only a
pluggable mirror. Runtime is 100 % stdlib, so everything is testable offline.

Engine version: `sdlc.version.engine_version()` (`sdlc --version` on the command line).
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
