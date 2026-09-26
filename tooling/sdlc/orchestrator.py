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


def run_ticket_upstream(sdlc, story, agents, escalation=None, max_fix=2, bubble=None,
                        run_workspace=None) -> Outcome:
    if run_workspace is not None:
        return _upstream_rw(sdlc, story, agents, run_workspace, escalation, max_fix)
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


def run_ticket_downstream(sdlc, story, agents, escalation=None, bubble=None, run_workspace=None) -> Outcome:
    if run_workspace is not None:
        return _downstream_rw(sdlc, story, agents, run_workspace)
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


# --- run workspace mode (code runs): one run per agent call, transitions carried by `finish` ---
#
# `run_workspace` exposes `init(story, role, **opts) -> dict` (JSON of `sdlc run init`) and
# `finish(run_uid, status=None) -> dict` (JSON of `sdlc run finish`). Each agent sees the ticket without
# its data paths (`artifacts`) plus `run`; the status that followed an agent becomes the `status` of its
# finish. The only direct transition left is `deployed` after a fix (no redeploy agent here).

class _Rejected(Exception):
    pass


def _published(fin: dict) -> bool:
    return bool(fin) and (fin.get("state") == "published" or "already" in fin)


_STEP = {"reviewer": "review", "deployer": "deploy", "recetteur": "recette", "fixer": "recette",
         "e2e-author": "e2e_author", "nonreg-runner": "nonreg", "demo": "demo"}


def _rw_step(sdlc, story, rw, role, agent, verdict_status, init_opts=None):
    """init -> agent -> finish (with the status the verdict earns). Returns (verdict, run)."""
    run = rw.init(story, role, **(init_opts or {}))
    t = {k: v for k, v in sdlc.get_ticket(story).items() if k != "artifacts"}
    verdict = agent({**t, "run": run})
    fin = rw.finish(run["run_uid"], status=verdict_status(verdict))
    if not _published(fin):
        raise _Rejected(_STEP[role])
    return verdict, run


def _upstream_rw(sdlc, story, agents, rw, escalation, max_fix) -> Outcome:
    esc = _esc(escalation)
    log: list = []
    try:
        if esc["review"] == "human-confirm":
            return Outcome(story, "review", "needs_human", "confirm review", log)
        rev, _ = _rw_step(sdlc, story, rw, "reviewer", agents["reviewer"],
                          lambda v: "reviewed" if v.get("conform") else None)
        log.append(("review", rev))
        if not rev.get("conform"):
            return Outcome(story, "review", "needs_human", rev.get("note", "non conforme"), log)

        if esc["deploy"] == "human-confirm":
            return Outcome(story, "deploy", "needs_human", "confirm deploy", log)
        dep, _ = _rw_step(sdlc, story, rw, "deployer", agents["deployer"],
                          lambda v: "deployed" if v.get("ok") else None)
        log.append(("deploy", dep))
        if not dep.get("ok"):
            return Outcome(story, "deploy", "needs_human", "deploy failed", log)

        tries = 0
        while True:
            rec, rec_run = _rw_step(sdlc, story, rw, "recetteur", agents["recetteur"],
                                    lambda v: "recette_ok" if v.get("pass") else None)
            log.append(("recette", rec))
            if rec.get("pass"):
                return Outcome(story, "recette", "await_validation", "recette OK — validation humaine", log)
            if rec.get("flaky") or tries >= max_fix:
                return Outcome(story, "recette", "needs_human", "recette KO (flaky/retries épuisés)", log)
            tries += 1
            fx, _ = _rw_step(sdlc, story, rw, "fixer", agents["fixer"],
                             lambda v: "reviewed" if v.get("fixed") else None,
                             {"status": "implemented", "repro": rec_run["run_uid"]})
            log.append(("fix", fx))
            if not fx.get("fixed"):
                return Outcome(story, "recette", "needs_human", "fix failed", log)
            sdlc.set_status(story, "deployed")                    # re-deploy (no agent in this reference)
    except _Rejected as e:
        return Outcome(story, str(e), "needs_human", "finish_rejected", log)


def _downstream_rw(sdlc, story, agents, rw) -> Outcome:
    log: list = []
    try:
        ea, _ = _rw_step(sdlc, story, rw, "e2e-author", agents["e2e_author"], lambda v: None)
        log.append(("e2e_author", ea))
        nr, _ = _rw_step(sdlc, story, rw, "nonreg-runner", agents["nonreg"], lambda v: None)
        log.append(("nonreg", nr))
        if not nr.get("pass"):
            return Outcome(story, "nonreg", "needs_human", "régression non-reg", log)
        demo, _ = _rw_step(sdlc, story, rw, "demo", agents["demo"], lambda v: None)
        log.append(("demo", demo))
    except _Rejected as e:
        return Outcome(story, str(e), "needs_human", "finish_rejected", log)
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
