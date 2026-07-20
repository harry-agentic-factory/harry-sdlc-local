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
    p = argparse.ArgumentParser(prog="sdlc")
    p.add_argument("--project", default=None, help="préfixe projet (ex. SAMPLE)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("create-epic"); a.add_argument("epic"); a.add_argument("title")
    a = sub.add_parser("create-ticket")
    a.add_argument("epic"); a.add_argument("story"); a.add_argument("title")
    a.add_argument("--deps"); a.add_argument("--repos")
    a = sub.add_parser("get"); a.add_argument("story")
    a = sub.add_parser("list"); a.add_argument("--status")
    a = sub.add_parser("next"); a.add_argument("epic")
    a = sub.add_parser("set-status"); a.add_argument("story"); a.add_argument("status")
    a = sub.add_parser("link"); a.add_argument("story"); a.add_argument("kind"); a.add_argument("path")
    a = sub.add_parser("migrate"); a.add_argument("--workspace")
    a = sub.add_parser("init-project"); a.add_argument("prefix"); a.add_argument("--path", required=True); a.add_argument("--repos")
    a = sub.add_parser("register"); a.add_argument("prefix"); a.add_argument("path")
    sub.add_parser("projects")
    a = sub.add_parser("config"); a.add_argument("--raw", action="store_true")
    a = sub.add_parser("worktree")
    a.add_argument("story"); a.add_argument("--repo"); a.add_argument("--branch"); a.add_argument("--base")
    a = sub.add_parser("worktree-clean")
    a.add_argument("story"); a.add_argument("--branch"); a.add_argument("--ref")

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
    if args.cmd in ("worktree", "worktree-clean"):
        from .config import resolved_manifest
        from . import worktree as wt
        t = s.get_ticket(args.story)
        branch = args.branch or t.get("branch")
        if not branch:
            raise ValueError(f"aucune branche pour {args.story} (ticket.branch vide, passe --branch)")
        man = resolved_manifest(args.project)
        repos_map = man["repos"]
        names = ([args.repo] if getattr(args, "repo", None) else t.get("repos")) or []
        out: dict[str, dict] = {}
        if args.cmd == "worktree":
            for name in names:
                p = repos_map.get(name)
                out[name] = ({"error": "repo non résolu dans le manifest (reposRoot/repos ?)"}
                             if not p else wt.ensure_worktree(p, branch, base=args.base))
            return {"story": args.story, "branch": branch, "worktrees": out}
        ref = args.ref or man.get("refBranch") or "main"
        for name in names:
            p = repos_map.get(name)
            out[name] = ({"error": "repo non résolu dans le manifest"}
                         if not p else wt.cleanup_if_merged(p, branch, ref))
        return {"story": args.story, "branch": branch, "ref": ref, "cleaned": out}
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
