"""State-machine des statuts d'une story SDLC.

Pipeline linéaire + arêtes de fix-loop (retour à IMPLEMENTED) + skip spec-func.
Toute transition invalide lève `InvalidTransition` — c'est le garde-fou testable
qui empêche un agent d'avancer un ticket dans le désordre.
"""
from __future__ import annotations

from enum import Enum


class Status(str, Enum):
    DRAFT = "draft"            # créé par /refine
    SPEC_FUNC = "spec_func"    # /spec-func (skippable)
    SPEC_TECH = "spec_tech"    # /spec-tech
    IMPLEMENTED = "implemented"  # /implement
    REVIEWED = "reviewed"      # agent reviewer (MR approuvée)
    DEPLOYED = "deployed"      # agent deployer
    RECETTE_OK = "recette_ok"  # recette validée
    ACCEPTED = "accepted"      # démo acceptée par l'humain
    DONE = "done"


PIPELINE: list[Status] = [
    Status.DRAFT, Status.SPEC_FUNC, Status.SPEC_TECH, Status.IMPLEMENTED,
    Status.REVIEWED, Status.DEPLOYED, Status.RECETTE_OK, Status.ACCEPTED, Status.DONE,
]


def _build_allowed() -> dict[Status, set[Status]]:
    allowed: dict[Status, set[Status]] = {}
    for i, s in enumerate(PIPELINE[:-1]):
        allowed[s] = {PIPELINE[i + 1]}
    allowed[Status.DONE] = set()
    # spec-func skippable (feature triviale) : DRAFT peut aller direct en SPEC_TECH
    allowed[Status.DRAFT].add(Status.SPEC_TECH)
    # fix-loop : une recette/review KO renvoie le ticket au dev
    for s in (Status.REVIEWED, Status.DEPLOYED, Status.RECETTE_OK):
        allowed[s].add(Status.IMPLEMENTED)
    return allowed


ALLOWED: dict[Status, set[Status]] = _build_allowed()

DONE_STATES: frozenset[Status] = frozenset({Status.ACCEPTED, Status.DONE})


class InvalidTransition(Exception):
    pass


def validate_transition(old: str | Status, new: str | Status) -> Status:
    old_s, new_s = Status(old), Status(new)
    if new_s not in ALLOWED.get(old_s, set()):
        raise InvalidTransition(f"{old_s.value} -> {new_s.value} interdit")
    return new_s
