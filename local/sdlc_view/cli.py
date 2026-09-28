"""`sdlc-view` CLI — JSON output, like `sdlc`.

    python3 -m sdlc_view board [--project P]
    python3 -m sdlc_view view [--port N]
    python3 -m sdlc_view activity start --epic E [--story S] --what "recette live MR-A" [--agent recetteur]
    python3 -m sdlc_view activity beat <id>
    python3 -m sdlc_view activity stop <id> [--result ok|ko|cancelled] [--note ...]
    python3 -m sdlc_view activity list
"""
from __future__ import annotations

import argparse
import json
import sys

from .activity import RESULTS


def _store(project: str | None, clock=None):
    from sdlc.config import resolve_workspace

    from .activity import ActivityStore
    return ActivityStore(resolve_workspace(project), clock=clock)


def run(argv: list[str] | None = None, clock=None) -> dict:
    p = argparse.ArgumentParser(
        prog="sdlc-view",
        description="Tableau de bord LOCAL du SDLC : instantané lecture seule, page web, et déclaration "
                    "de ce qui tourne en ce moment. Sortie JSON.")
    p.add_argument("--project", default=None,
                   help="préfixe projet (ex. AISDLC) ; sinon workspace résolu par défaut comme `sdlc`")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<commande>")

    sub.add_parser("board", help="instantané LECTURE SEULE de tous les projets du registre : épics, stories, "
                                 "avancement, décisions ouvertes, ce qui tourne (--project pour n'en garder qu'un)")
    a = sub.add_parser("view", help="page web locale (127.0.0.1) sur `sdlc-view board`, rafraîchie en continu. "
                                    "Port : --port, sinon SDLC_VIEW_PORT, sinon \"view\": {\"port\": N} "
                                    "dans ~/.claude/sdlc/projects.json")
    a.add_argument("--port", type=int, help="port d'écoute (prioritaire sur SDLC_VIEW_PORT et le registre)")

    act = sub.add_parser("activity", help="déclare ce qui tourne maintenant (écrit <workspace>/_live.json)")
    asub = act.add_subparsers(dest="actcmd", required=True, metavar="<start|beat|stop|list>")
    a = asub.add_parser("start", help="déclare une activité qui démarre → renvoie son id")
    a.add_argument("--epic", required=True, help="ID épic concerné")
    a.add_argument("--story", help="ID story concernée")
    a.add_argument("--what", required=True, help="libellé court (ex. « recette live MR-A »)")
    a.add_argument("--agent", help="type d'agent (ex. recetteur, deployer, fixer)")
    a = asub.add_parser("beat", help="signe de vie d'une activité en cours")
    a.add_argument("id", help="id renvoyé par `activity start`")
    a = asub.add_parser("stop", help="termine une activité")
    a.add_argument("id", help="id renvoyé par `activity start`")
    a.add_argument("--result", default="ok", choices=RESULTS, help="ok | ko | cancelled (défaut ok)")
    a.add_argument("--note", help="note courte (jamais de secret)")
    asub.add_parser("list", help="activités en cours (avec « stale ») et dernières terminées du projet")

    args = p.parse_args(argv)

    if args.cmd == "board":
        from .board import snapshot
        return snapshot(args.project)
    if args.cmd == "view":
        from .server import serve
        return serve(args.port)
    store = _store(args.project, clock)
    if args.actcmd == "start":
        return store.start(args.epic, args.what, story=args.story, agent=args.agent)
    if args.actcmd == "beat":
        return store.beat(args.id)
    if args.actcmd == "stop":
        return store.stop(args.id, result=args.result, note=args.note)
    return store.list()


def main(argv: list[str] | None = None) -> int:
    try:
        print(json.dumps(run(argv), indent=2, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001 - CLI: clean message
        msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
        print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
