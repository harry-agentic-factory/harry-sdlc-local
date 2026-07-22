"""CLI `sdlc` — surface en ligne de commande de la façade (utilisée par les
commandes Harry et testable directement). Sortie JSON.

    python3 -m sdlc.cli create-epic SAMPLE-PROV "Provisioning depuis le produit"
    python3 -m sdlc.cli create-ticket SAMPLE-PROV SAMPLE-PROV-1 "API" --deps SAMPLE-PROV-2,SAMPLE-PROV-3 --repos app-repo
    python3 -m sdlc.cli get SAMPLE-PROV-1
    python3 -m sdlc.cli next SAMPLE-PROV
    python3 -m sdlc.cli set-status SAMPLE-PROV-1 spec_tech
    python3 -m sdlc.cli link SAMPLE-PROV-1 spec_tech SAMPLE-PROV/stories/SAMPLE-PROV-1/spec-tech.md
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from .config import resolve_workspace
from .board import NullBoard
from .service import Sdlc
from .workspace import Workspace


def _csv(v: str | None) -> list[str]:
    return [x for x in (v or "").split(",") if x]


def _sdlc(project: str | None) -> Sdlc:
    ws = resolve_workspace(project)
    return Sdlc(Workspace(ws), NullBoard())


def run(argv: list[str] | None = None) -> dict:
    p = argparse.ArgumentParser(
        prog="sdlc",
        description="Façade SDLC Harry — état des tickets/épics, DAG, artefacts, worktrees. Sortie JSON.",
        epilog="Astuce : `sdlc <commande> -h` pour le détail d'une commande. "
               "Pipeline : create-epic → create-ticket → set-status (spec_func→spec_tech→implemented→"
               "reviewed→deployed→recette_ok→accepted→done).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--project", default=None, help="préfixe projet (ex. SAMPLE) ; sinon workspace résolu par défaut")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<commande>",
                           title="commandes", help="(voir `sdlc <commande> -h`)")

    # --- backlog / stories ---
    a = sub.add_parser("create-epic", help="crée un épic")
    a.add_argument("epic", help="ID épic (ex. SAMPLE-PROV)"); a.add_argument("title", help="titre de l'épic")
    a = sub.add_parser("create-ticket", help="crée une story dans un épic (avec deps + repos)")
    a.add_argument("epic", help="ID épic parent"); a.add_argument("story", help="ID story (ex. SAMPLE-PROV-1)")
    a.add_argument("title", help="titre de la story")
    a.add_argument("--deps", help="stories dont elle dépend, séparées par des virgules")
    a.add_argument("--repos", help="repos touchés, séparés par des virgules")
    a = sub.add_parser("get", help="réhydrate un ticket (statut, repos, branche, artefacts)")
    a.add_argument("story", help="ID story")
    a = sub.add_parser("list", help="liste le backlog (option : filtrer par statut)")
    a.add_argument("--status", help="filtre statut (spec_func|spec_tech|implemented|reviewed|deployed|…)")
    a = sub.add_parser("next", help="prochain actionnable d'un épic (résolution du DAG)")
    a.add_argument("epic", help="ID épic")
    a = sub.add_parser("set-status", help="change le statut d'une story (transition d'orchestration)")
    a.add_argument("story", help="ID story")
    a.add_argument("status", help="spec_func|spec_tech|implemented|reviewed|deployed|recette_ok|accepted|done")
    a = sub.add_parser("link", help="attache un artefact (doc) à une story")
    a.add_argument("story", help="ID story")
    a.add_argument("kind", help="type : prd|spec_func|spec_tech|implement|review|deploy|acceptance|demo")
    a.add_argument("path", help="chemin du .md relatif au repo data du projet")

    # --- projets / config / maintenance ---
    a = sub.add_parser("migrate", help="applique les migrations de schéma du workspace")
    a.add_argument("--workspace", help="chemin workspace (sinon résolu depuis --project)")
    a = sub.add_parser("init-project", help="initialise un nouveau projet SDLC (repo data + config)")
    a.add_argument("prefix", help="préfixe projet (ex. SAMPLE)")
    a.add_argument("--path", required=True, help="chemin du repo data du projet")
    a.add_argument("--repos", help="repos de code, séparés par des virgules")
    a = sub.add_parser("register", help="enregistre un projet existant dans le registre")
    a.add_argument("prefix", help="préfixe projet"); a.add_argument("path", help="chemin du repo data")
    sub.add_parser("projects", help="liste les projets enregistrés")
    a = sub.add_parser("config", help="manifest résolu du projet (deploy/recette/credentials…)")
    a.add_argument("--raw", action="store_true", help="config brute non résolue")
    a = sub.add_parser("status", help="statut exact d'un ticket/épic (état + artefacts + recaps agents)")
    a.add_argument("target", nargs="?", help="ID ticket ou épic (sinon : projet entier)")

    # --- worktrees / workspace agent ---
    a = sub.add_parser("worktree", help="crée/assure un git worktree par repo pour une story")
    a.add_argument("story", help="ID story"); a.add_argument("--repo", help="limiter à un repo (sinon tous ceux du ticket)")
    a.add_argument("--branch", help="branche (sinon ticket.branch)"); a.add_argument("--base", help="branche de base")
    a = sub.add_parser("worktree-clean", help="nettoie le(s) worktree(s) d'une story")
    a.add_argument("story", help="ID story"); a.add_argument("--branch", help="branche"); a.add_argument("--ref", help="ref à conserver")
    a = sub.add_parser("workspace", help="construit le workspace isolé d'un agent pour une story")
    a.add_argument("story", help="ID story"); a.add_argument("--branch", help="branche")

    args = p.parse_args(argv)

    if args.cmd == "migrate":
        from .migrations import apply_migrations
        ws = args.workspace or resolve_workspace(args.project)
        return apply_migrations(ws)
    if args.cmd == "init-project":
        from .project import init_project
        return init_project(args.prefix, args.path, _csv(args.repos))
    if args.cmd == "register":
        from .project import register_project
        return {"prefix": args.prefix, "registered": register_project(args.prefix, args.path)}
    if args.cmd == "projects":
        from .project import list_projects
        return {"projects": list_projects()}
    if args.cmd == "config":
        from .config import load_config, resolved_manifest
        if args.raw:
            return load_config(resolve_workspace(args.project))
        return resolved_manifest(args.project)
    if args.cmd == "status":
        from .status_report import build_status
        return build_status(resolve_workspace(args.project), args.target)

    s = _sdlc(args.project)

    if args.cmd == "create-epic":
        s.create_epic(args.epic, args.title); return {"epic": args.epic, "created": True}
    if args.cmd == "create-ticket":
        t = s.create_ticket(args.epic, args.story, args.title, _csv(args.deps), _csv(args.repos))
        return dataclasses.asdict(t)
    if args.cmd == "get":
        return s.get_ticket(args.story)
    if args.cmd == "list":
        return {"tickets": [dataclasses.asdict(t) for t in s.list_backlog(args.status)]}
    if args.cmd == "next":
        return {"epic": args.epic, "next": s.next(args.epic)}
    if args.cmd == "set-status":
        return dataclasses.asdict(s.set_status(args.story, args.status))
    if args.cmd == "link":
        return dataclasses.asdict(s.link_artifact(args.story, args.kind, args.path))
    if args.cmd == "workspace":
        from .agentws import build_agent_workspace
        return build_agent_workspace(args.project, args.story, branch=args.branch)
    if args.cmd == "worktree-clean":
        from .agentws import clean_workspace
        return clean_workspace(args.project, args.story, branch=args.branch, ref=args.ref)
    if args.cmd == "worktree":
        from .config import resolved_manifest
        from . import worktree as wt
        t = s.get_ticket(args.story)
        branch = args.branch or t.get("branch")
        if not branch:
            raise ValueError(f"aucune branche pour {args.story} (ticket.branch vide, passe --branch)")
        man = resolved_manifest(args.project)
        names = ([args.repo] if args.repo else t.get("repos")) or []
        out: dict[str, dict] = {}
        for name in names:
            p = man["repos"].get(name)
            out[name] = ({"error": "repo non résolu dans le manifest (reposRoot/repos ?)"}
                         if not p else wt.ensure_worktree(p, branch, base=args.base))
        return {"story": args.story, "branch": branch, "worktrees": out}
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    try:
        print(json.dumps(run(argv), indent=2, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001 — CLI: message propre
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
