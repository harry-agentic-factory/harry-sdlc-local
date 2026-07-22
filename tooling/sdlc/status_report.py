"""`sdlc status [<EPIC>|<STORY>]` — statut **exact** d'un ticket/épic en croisant trois sources :

1. **l'état** (`status.json` via la state-machine) — statut, position pipeline, deps, blocage ;
2. **le feedback des agents** — présence des artefacts `.md` (review/deploy/acceptance/…) ;
3. **le recap d'activité** — le bloc `## Recap` que chaque agent écrit en tête de son artefact
   (outcome + faits clés + agent + horodatage). Pas de parsing de logs bruts (contexte maîtrisé).

Déterministe, sans LLM → testable. Le recap est **tronqué** (discipline de contexte).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .graph import next_actionable
from .status import DONE_STATES
from .workspace import STORY_MD, Workspace

_RECAP_MAX = 500
# indice de gate humaine attendue selon le statut courant
_AWAITING = {
    "recette_ok": "attend l'accept humain (→ accepted)",
    "reviewed": "attend le déploiement",
    "deployed": "attend la recette",
}


def _recap(md_path: Path) -> str | None:
    """Extrait le bloc `## Recap` d'un artefact (jusqu'au heading suivant), tronqué."""
    if not md_path.exists():
        return None
    grab, out = False, []
    for line in md_path.read_text(errors="ignore").splitlines():
        if line.strip().lower().startswith("## recap"):
            grab = True
            continue
        if grab and line.startswith("## "):
            break
        if grab:
            out.append(line)
    txt = "\n".join(out).strip()
    if not txt:
        return None
    return txt[:_RECAP_MAX] + ("…" if len(txt) > _RECAP_MAX else "")


def _artifacts(story_dir: Path) -> list[dict]:
    """Un artefact est **produit** (feedback d'agent réel) s'il dépasse le stub scaffoldé
    (`# <id> — <kind>`, une seule ligne). Un stub vide ≠ feedback."""
    arts = []
    for name in STORY_MD:
        p = story_dir / name
        produced, recap = False, None
        if p.exists():
            body = [ln for ln in p.read_text(errors="ignore").splitlines() if ln.strip()]
            produced = len(body) > 1                    # > le simple header scaffoldé
            recap = _recap(p)
        arts.append({"kind": name.removesuffix(".md"), "produced": produced, "recap": recap})
    return arts


def build_status(workspace: str | Path, target: str | None = None) -> dict:
    ws = Workspace(workspace)
    tickets = ws.all_tickets()
    done = {s.value for s in DONE_STATES}
    status_by = {t.id: t.status for t in tickets}

    # périmètre : ticket, épic, ou projet entier
    if target:
        sel = [t for t in tickets if t.id == target]
        scope = "ticket"
        if not sel:
            sel = [t for t in tickets if t.epic == target]
            scope = "epic"
        if not sel:
            raise KeyError(f"ni ticket ni épic connu : {target}")
    else:
        sel, scope = tickets, "project"

    out_tickets = []
    for t in sel:
        blocked = [d for d in t.deps if status_by.get(d) not in done]
        out_tickets.append({
            "id": t.id, "epic": t.epic, "title": t.title, "status": t.status,
            "next": t.next_step, "deps": t.deps, "blockedBy": blocked,
            "awaiting": _AWAITING.get(t.status),
            "artifacts": _artifacts(ws.story_dir(t.epic, t.id)),
        })

    total = len(out_tickets)
    ndone = sum(1 for t in out_tickets if t["status"] in done)
    res = {
        "scope": scope, "target": target,
        "progress": {"total": total, "done": ndone,
                     "by_status": dict(Counter(t["status"] for t in out_tickets))},
        "tickets": out_tickets,
    }
    # prochain actionnable de l'épic concerné (hors scope projet multi-épics)
    if scope in ("epic", "ticket") and out_tickets:
        epic = out_tickets[0]["epic"]
        deps = {t.id: t.deps for t in tickets if t.epic == epic}
        st = {t.id: t.status for t in tickets if t.epic == epic}
        res["next"] = next_actionable(deps, st, done)
    return res
