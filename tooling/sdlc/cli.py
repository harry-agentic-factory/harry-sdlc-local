"""CLI `sdlc` — surface en ligne de commande de la façade (utilisée par les
commandes Harry et testable directement). Sortie JSON.

    python3 -m sdlc.cli create-epic HIA-PROV "Provisioning depuis le produit"
    python3 -m sdlc.cli create-ticket HIA-PROV HIA-PROV-1 "API" --deps HIA-PROV-2,HIA-PROV-3 --repos back-tenant
    python3 -m sdlc.cli get HIA-PROV-1
    python3 -m sdlc.cli next HIA-PROV
    python3 -m sdlc.cli set-status HIA-PROV-1 spec_tech
    python3 -m sdlc.cli link HIA-PROV-1 spec_tech HIA-PROV/stories/HIA-PROV-1/spec-tech.md
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
    p.add_argument("--project", default=None, help="préfixe projet (ex. HIA)")
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

    args = p.parse_args(argv)

    if args.cmd == "migrate":
        from .migrations import apply_migrations
        ws = args.workspace or resolve_workspace(args.project)
        return apply_migrations(ws)

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
