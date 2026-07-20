"""Orchestrateur `run-ticket` (logique de référence, déterministe, testable en stub).

Les agents sont injectés (callables `ctx -> verdict`) → on teste l'enchaînement, les
gates, le fix-loop et l'escalation SANS LLM. La version « live » (Workflow Claude Code)
appelle les mêmes étapes via de vrais sous-agents.

**Propriété des transitions de statut = l'ORCHESTRATION, jamais l'agent.** Les agents renvoient un
*verdict* (`{conform}`/`{ok}`/`{pass}`…) et enregistrent leurs artefacts (`link`) ; ils **ne décident pas**
de la transition. Ici (Python) l'orchestrateur applique `sdlc.set_status(...)` en direct. Dans le tronçon
JS (`run-ticket*.js`, qui ne peut pas shell-out), le **workflow dicte** la transition cible dans le prompt
de chaque phase et l'agent l'exécute mécaniquement — la *décision* reste à l'orchestration. En interactif,
c'est Harry/la commande (`/spec-func`…) qui possède la transition. Un seul propriétaire par contexte.

Tronçon 1 (auto amont)  : reviewer → deployer → recette (+ fix-loop) → STOP validation.
Tronçon 2 (auto aval)   : e2e-author → nonreg → demo → STOP accept.

Verdicts attendus :
  reviewer(ctx)   -> {"conform": bool, "note": str}
  deployer(ctx)   -> {"ok": bool, "version": str}
  recetteur(ctx)  -> {"pass": bool, "repro": str|None, "flaky": bool}
  fixer(ctx)      -> {"fixed": bool}
  e2e_author(ctx) -> {"spec": str}
  nonreg(ctx)     -> {"pass": bool}
  demo(ctx)       -> {"demo": str}
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import DEFAULT_ESCALATION


@dataclass
class Outcome:
    story: str
    stopped_at: str            # étape où le run s'arrête
    reason: str                # 'await_validation' | 'needs_human' | 'accepted'
    detail: str = ""
    log: list = field(default_factory=list)


def _esc(escalation: dict | None) -> dict:
    return {**DEFAULT_ESCALATION, **(escalation or {})}


def run_ticket_upstream(sdlc, story, agents, escalation=None, max_fix=2, bubble=None) -> Outcome:
    esc = _esc(escalation)
    log: list = []

    def ctx() -> dict:
        t = sdlc.get_ticket(story)
        return {**t, "bubble": bubble} if bubble else t   # agents voient les worktrees scopés

    # ── REVIEW ──
    if esc["review"] == "human-confirm":
        return Outcome(story, "review", "needs_human", "confirm review", log)
    rev = agents["reviewer"](ctx()); log.append(("review", rev))
    if not rev.get("conform"):
        return Outcome(story, "review", "needs_human", rev.get("note", "non conforme"), log)
    sdlc.set_status(story, "reviewed")

    # ── DEPLOY ──
    if esc["deploy"] == "human-confirm":
        return Outcome(story, "deploy", "needs_human", "confirm deploy", log)
    dep = agents["deployer"](ctx()); log.append(("deploy", dep))
    if not dep.get("ok"):
        return Outcome(story, "deploy", "needs_human", "deploy failed", log)
    sdlc.set_status(story, "deployed")

    # ── RECETTE + FIX-LOOP ──
    tries = 0
    while True:
        rec = agents["recetteur"](ctx()); log.append(("recette", rec))
        if rec.get("pass"):
            sdlc.set_status(story, "recette_ok")
            return Outcome(story, "recette", "await_validation", "recette OK — validation humaine", log)
        if rec.get("flaky") or tries >= max_fix:
            return Outcome(story, "recette", "needs_human", "recette KO (flaky/retries épuisés)", log)
        tries += 1
        sdlc.set_status(story, "implemented")                     # retour dev
        fx = agents["fixer"]({**ctx(), "repro": rec.get("repro")}); log.append(("fix", fx))
        sdlc.set_status(story, "reviewed")                        # re-review
        sdlc.set_status(story, "deployed")                        # re-deploy


def run_ticket_downstream(sdlc, story, agents, escalation=None, bubble=None) -> Outcome:
    esc = _esc(escalation)
    log: list = []

    def ctx() -> dict:
        t = sdlc.get_ticket(story)
        return {**t, "bubble": bubble} if bubble else t

    ea = agents["e2e_author"](ctx()); log.append(("e2e_author", ea))
    nr = agents["nonreg"](ctx()); log.append(("nonreg", nr))
    if not nr.get("pass"):
        # régression : le deployer sait rollback (hors scope logique ici) → escalade
        return Outcome(story, "nonreg", "needs_human", "régression non-reg", log)
    demo = agents["demo"](ctx()); log.append(("demo", demo))
    return Outcome(story, "demo", "await_validation", "démo prête — accept humain", log)


def accept(sdlc, story, finalize=None) -> None:
    """Gate humaine finale (sprint review) : recette_ok → accepted → done.

    `finalize` (optionnel) : callable appelé une fois `done` atteint — c'est le point où
    l'orchestration nettoie la bulle du ticket (worktrees mergés + dossier), ex.
    `lambda: clean_workspace(project, story)`.
    """
    sdlc.set_status(story, "accepted")
    sdlc.set_status(story, "done")
    if finalize:
        finalize()
