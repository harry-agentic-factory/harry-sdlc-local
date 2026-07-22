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
        description="CLI de l'engine SDLC (Harry) — pilote épics, stories, statuts, "
                    "artefacts et worktrees d'un projet. Sortie JSON.",
        epilog=(
            "exemples :\n"
            "  sdlc --project SAMPLE list --status implemented\n"
            "  sdlc --project SAMPLE get SAMPLE-GATES-1\n"
            "  sdlc --project SAMPLE next SAMPLE-GATES\n"
            "  sdlc --project SAMPLE set-status SAMPLE-GATES-1 reviewed\n"
            "  sdlc --project SAMPLE workspace SAMPLE-GATES-1 --branch feat/SAMPLE-GATES-1"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--project", default=None, help="préfixe projet (ex. SAMPLE)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<commande>", title="commandes")

    a = sub.add_parser("create-epic", help="crée un épic"); a.add_argument("epic"); a.add_argument("title")
    a = sub.add_parser("create-ticket", help="crée une story dans un épic")
    a.add_argument("epic"); a.add_argument("story"); a.add_argument("title")
    a.add_argument("--deps"); a.add_argument("--repos")
    a = sub.add_parser("get", help="affiche une story (JSON)"); a.add_argument("story")
    a = sub.add_parser("list", help="liste les stories (option --status)"); a.add_argument("--status")
    a = sub.add_parser("next", help="prochaine story prête d'un épic"); a.add_argument("epic")
    a = sub.add_parser("set-status", help="change le statut d'une story"); a.add_argument("story"); a.add_argument("status")
    a = sub.add_parser("link", help="rattache un artefact à une story"); a.add_argument("story"); a.add_argument("kind"); a.add_argument("path")
    a = sub.add_parser("migrate", help="applique les migrations du workspace"); a.add_argument("--workspace")
    a = sub.add_parser("init-project", help="initialise un nouveau projet SDLC"); a.add_argument("prefix"); a.add_argument("--path", required=True); a.add_argument("--repos")
    a = sub.add_parser("register", help="enregistre un projet existant"); a.add_argument("prefix"); a.add_argument("path")
    sub.add_parser("projects", help="liste les projets enregistrés")
    a = sub.add_parser("config", help="affiche le manifest résolu (--raw = brut)"); a.add_argument("--raw", action="store_true")
    a = sub.add_parser("worktree", help="crée un worktree git isolé pour une story")
    a.add_argument("story"); a.add_argument("--repo"); a.add_argument("--branch"); a.add_argument("--base")
    a = sub.add_parser("worktree-clean", help="retire le worktree/branche d'une story mergée")
    a.add_argument("story"); a.add_argument("--branch"); a.add_argument("--ref")
    a = sub.add_parser("workspace", help="matérialise la bulle scopée (worktree+settings+skills)"); a.add_argument("story"); a.add_argument("--branch")

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
