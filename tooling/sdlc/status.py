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
    SPEC_FUNC_VALIDATED = "spec_func_validated"  # gate FONCTIONNELLE : PRD + spec-func validés (épic ou story)
    SPEC_TECH = "spec_tech"    # /spec-tech
    SPEC_VALIDATED = "spec_validated"  # gate: specs validées par harry-archi (+ escalade humaine) AVANT implem
    # Feature gate: the whole epic reviewed and signed by the PO and the tech lead, before the factory handoff.
    FEATURE_VALIDATED = "feature_validated"
    IMPLEMENTED = "implemented"  # /implement
    REVIEWED = "reviewed"      # agent reviewer (MR approuvée)
    DEPLOYED = "deployed"      # agent deployer
    RECETTE_OK = "recette_ok"  # recette validée
    ACCEPTED = "accepted"      # démo acceptée par l'humain
    DONE = "done"


PIPELINE: list[Status] = [
    Status.DRAFT, Status.SPEC_FUNC, Status.SPEC_FUNC_VALIDATED, Status.SPEC_TECH,
    Status.SPEC_VALIDATED, Status.FEATURE_VALIDATED, Status.IMPLEMENTED,
    Status.REVIEWED, Status.DEPLOYED, Status.RECETTE_OK, Status.ACCEPTED, Status.DONE,
]


def _build_allowed() -> dict[Status, set[Status]]:
    allowed: dict[Status, set[Status]] = {}
    for i, s in enumerate(PIPELINE[:-1]):
        allowed[s] = {PIPELINE[i + 1]}
    allowed[Status.DONE] = set()
    # spec-func skippable (feature triviale) : DRAFT peut aller direct en SPEC_TECH
    allowed[Status.DRAFT].add(Status.SPEC_TECH)
    # gate FONCTIONNELLE skippable : SPEC_FUNC -> SPEC_TECH direct. Elle vaut surtout au niveau ÉPIC
    # (valider le PRD + tous les spec-func d'un coup, AVANT d'écrire le technique par-dessus) ; sur une
    # story isolée elle est souvent du cérémonial. Comme la gate technique, la version « dure » est portée
    # par l'ORCHESTRATION (`validate-func`), la state-machine tolère le saut.
    allowed[Status.SPEC_FUNC].add(Status.SPEC_TECH)
    # gate spec_validated SKIPPABLE (backward-compat + features triviales) : SPEC_TECH -> IMPLEMENTED direct.
    # La gate "dure" (review harry-archi + escalade) est portée par l'ORCHESTRATION (`validate-spec` passe par
    # SPEC_VALIDATED) ; la state-machine tolère le skip pour ne pas casser les flux existants.
    allowed[Status.SPEC_TECH].add(Status.IMPLEMENTED)
    # Feature gate skippable as well (backward compatibility): SPEC_VALIDATED -> IMPLEMENTED stays allowed.
    # The hard version is `validate-feature` (two human-signed verdicts, PO and tech lead).
    allowed[Status.SPEC_VALIDATED].add(Status.IMPLEMENTED)
    # Routed return after a gate: a validated spec or feature can go back to the design or the functional spec
    # (`sdlc reject --to spec_tech|spec_func`), e.g. after a `returned` verdict of the feature gate.
    for s in (Status.SPEC_VALIDATED, Status.FEATURE_VALIDATED):
        allowed[s].update({Status.SPEC_TECH, Status.SPEC_FUNC})
    # rejet routé : une review/recette KO peut repartir vers le dev (implemented), la conception
    # (spec_tech, ré-analyse) ou le fonctionnel (spec_func) — c'est la gate humaine qui choisit.
    for s in (Status.REVIEWED, Status.DEPLOYED, Status.RECETTE_OK):
        allowed[s].update({Status.IMPLEMENTED, Status.SPEC_TECH, Status.SPEC_FUNC})
    return allowed


ALLOWED: dict[Status, set[Status]] = _build_allowed()

DONE_STATES: frozenset[Status] = frozenset({Status.ACCEPTED, Status.DONE})

# --- rattrapage d'un fait deja survenu (voir validate_transition(force_reason=...)) ---
#
# Le board doit pouvoir DECRIRE LA REALITE, meme quand la realite a saute une etape. Cas vecu
# (2026-10-24, HIA-STATPERF) : deux stories tournaient EN PRODUCTION en affichant encore
# `implemented`, parce que le deploiement avait eu lieu pour une raison d'infra et que rien
# n'avait notifie la state-machine. Le board inventait alors du retard qui n'existait pas, et
# ce retard fictif a ete rapporte a l'humain comme un fait. Un tableau qui ne peut pas decrire
# le monde est plus nuisible qu'un tableau qui a saute une etape.
#
# D'ou la distinction qui porte tout ce mecanisme :
#
# FACTUAL = statuts qui constatent un FAIT OBSERVABLE (le code existe, il est relu, il est
#   deploye, il est recette). Un fait peut etre rattrape : il s'est produit, qu'on l'ait
#   enregistre ou non. On exige seulement un MOTIF, pour que le saut reste lisible.
#
# SIGNED = statuts qui portent une SIGNATURE HUMAINE (verdicts de gate, accept, done). Ils ne
#   sont JAMAIS forcables. Forger une signature est la seule chose que le harnais doit refuser
#   en toute circonstance : un agent qui pourrait s'auto-accorder un `accepted` viderait de sens
#   la seule gate que l'humain possede.
FACTUAL: frozenset[Status] = frozenset({
    Status.SPEC_FUNC, Status.SPEC_TECH, Status.IMPLEMENTED,
    Status.REVIEWED, Status.DEPLOYED, Status.RECETTE_OK,
})

SIGNED: frozenset[Status] = frozenset({
    Status.SPEC_FUNC_VALIDATED, Status.SPEC_VALIDATED, Status.FEATURE_VALIDATED,
    Status.ACCEPTED, Status.DONE,
})


class InvalidTransition(Exception):
    pass


class ForcedTransitionRefused(InvalidTransition):
    """Un rattrapage a ete demande sur une transition qui n'en admet pas."""


def validate_transition(old: str | Status, new: str | Status,
                        force_reason: str | None = None) -> Status:
    """Valide une transition, ou RATTRAPE un fait deja survenu si `force_reason` est fourni.

    Sans `force_reason` : comportement d'origine, seules les aretes de `ALLOWED` passent.

    Avec `force_reason` : on autorise en plus un saut VERS L'AVANT dans le pipeline et vers un
    statut `FACTUAL`. Trois refus subsistent, et ce sont eux qui font que ce n'est pas un
    contournement de la state-machine :
      - vers un statut `SIGNED` : on n'enregistre pas une signature humaine qu'on n'a pas ;
      - vers l'arriere : un retour en arriere est un REJET, il a sa commande (`sdlc reject --to`)
        qui exige une note et un acteur ;
      - un motif vide : sans motif, le saut est indistinguable d'un bug d'orchestration.
    """
    old_s, new_s = Status(old), Status(new)
    if new_s in ALLOWED.get(old_s, set()):
        return new_s
    if force_reason is None:
        raise InvalidTransition(
            f"{old_s.value} -> {new_s.value} interdit"
            f" (si le fait est DEJA survenu : --force-reason \"<pourquoi>\")")

    if not force_reason.strip():
        raise ForcedTransitionRefused(
            f"{old_s.value} -> {new_s.value} : motif de rattrapage vide")
    if new_s in SIGNED:
        raise ForcedTransitionRefused(
            f"{old_s.value} -> {new_s.value} : `{new_s.value}` porte une signature humaine,"
            " il n'est jamais rattrapable")
    if new_s not in FACTUAL:
        raise ForcedTransitionRefused(
            f"{old_s.value} -> {new_s.value} : `{new_s.value}` n'est pas un statut de fait")
    if PIPELINE.index(new_s) <= PIPELINE.index(old_s):
        raise ForcedTransitionRefused(
            f"{old_s.value} -> {new_s.value} : un retour en arriere est un rejet,"
            " utiliser `sdlc reject --to {new}`".format(new=new_s.value))
    return new_s
