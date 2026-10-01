"""`tracker` CLI — bridge between an issue tracker (Trello, ...) and the SDLC. JSON output.

The SDLC never calls this and knows nothing about the tracker: story statuses are read here through
the `sdlc` CLI, and persistence lives in `<workspace>/_tracker/` (config.json, links.json, cards/,
reviews/).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .store import DECISIONS, STATES, Tracker
from .trello import TrelloError, source_for

TRACKER_DIR = "_tracker"


def _sdlc(prefix: str | None, *args: str) -> dict:
    cmd = [os.environ.get("SDLC_BIN", "sdlc")]
    if prefix:
        cmd += ["--project", prefix]
    out = subprocess.run(cmd + list(args), capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"sdlc {' '.join(args)} failed: {out.stderr.strip()[:300]}")
    return json.loads(out.stdout)


def _root(prefix: str | None) -> Path:
    return Path(_sdlc(prefix, "config")["workspace"]) / TRACKER_DIR


def _story_status(prefix: str | None):
    def status_of(story: str):
        try:
            return _sdlc(prefix, "get", story).get("status")
        except (RuntimeError, json.JSONDecodeError):
            return None
    return status_of


def _emit(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_init(a) -> dict:
    root = _root(a.project)
    cfg_path = root / "config.json"
    if cfg_path.exists() and not a.force:
        return {"root": str(root), "config": "exists", "hint": "--force to rebuild from the manifest"}
    block = _sdlc(a.project, "config").get("tracker")
    if not block:
        raise SystemExit("the manifest has no `tracker` block: write <workspace>/_tracker/config.json by hand")
    root.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(Tracker.build_config(block), indent=2, ensure_ascii=False) + "\n")
    t = Tracker.load(root)
    t.save()
    return {"root": str(root), "config": "written", "board": t.config.get("board"),
            "gitignore": _ignore_in_workspace(root.parent)}


def _ignore_in_workspace(workspace: Path) -> str:
    """`_tracker/` is working storage, rewritten on every run: keep it out of the data repo."""
    gitignore = workspace / ".gitignore"
    text = gitignore.read_text() if gitignore.exists() else ""
    if any(line.strip() in (f"{TRACKER_DIR}/", TRACKER_DIR, f"/{TRACKER_DIR}/") for line in text.splitlines()):
        return "already ignored"
    sep = "" if not text or text.endswith("\n") else "\n"
    gitignore.write_text(f"{text}{sep}\n# Tracker bridge working storage (local, not versioned)\n{TRACKER_DIR}/\n")
    return "added"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tracker", description=__doc__.splitlines()[0])
    p.add_argument("--project", help="project prefix (e.g. HIA)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    s = sub.add_parser("init", help="create <workspace>/_tracker/config.json from the manifest tracker block")
    s.add_argument("--force", action="store_true")
    sub.add_parser("dir", help="print the tracker persistence directory")
    s = sub.add_parser("pull", help="read the board, update links.json, report new/changed/gone/toInstruct/toReview")
    s.add_argument("--nature", help="only report cards of this nature (e.g. bug); links.json still gets all")
    s = sub.add_parser("card", help="read one card in full, live (description, comments, attachments)")
    s.add_argument("ref", help="card URL, shortLink or id")
    s.add_argument("--download", action="store_true",
                   help="save uploaded attachments under <tracker dir>/cards/<shortLink>/attachments/ (path in output)")
    s = sub.add_parser("show", help="cards known to links.json")
    s.add_argument("ref", nargs="?")
    s.add_argument("--state", choices=STATES)
    s.add_argument("--story")
    s.add_argument("--nature")
    s.add_argument("--all", action="store_true", help="include cards that left the board")
    s = sub.add_parser("instructed", help="record the investigation file of a card")
    s.add_argument("ref")
    s.add_argument("--fiche", required=True)
    s = sub.add_parser("decide", help="record the human decision of /bugs-review")
    s.add_argument("ref")
    s.add_argument("decision", choices=DECISIONS)
    s.add_argument("--reason")
    s.add_argument("--review", help="path of the review/verdict the decision comes from")
    s = sub.add_parser("link", help="link a card decided fix|other to an SDLC story")
    s.add_argument("ref")
    s.add_argument("story")
    s.add_argument("--epic")
    s = sub.add_parser("push", help="moves the SDLC implies on the board (dry run unless --apply)")
    s.add_argument("--apply", action="store_true", help="perform the moves on the tracker")
    s.add_argument("--only", action="append", default=[], help="restrict to these cards (repeatable)")
    s.add_argument("--comment", action="store_true", help="also post a status comment on each moved card")
    s = sub.add_parser("forget-push", help="forget our last push of cards moved back on purpose (not reporter feedback)")
    s.add_argument("refs", nargs="+")
    a = p.parse_args(argv)

    try:
        if a.cmd == "init":
            _emit(cmd_init(a))
            return 0
        root = _root(a.project)
        if a.cmd == "dir":
            print(root)
            return 0
        t = Tracker.load(root)
        if a.cmd == "pull":
            report = t.merge_pull(source_for(t.config).board_cards())
            t.save()
            def row(cid):
                c = t.cards[cid]
                return {"card": cid, "shortLink": c["shortLink"], "nature": t.nature(c), "list": c["list"],
                        "rank": c.get("rank"), "labels": c["labels"], "name": c["name"]}
            by_priority = lambda cids: sorted(cids, key=lambda c: (t.cards[c]["list"], t.cards[c].get("rank") or 10**6))
            rows = {k: [row(c) for c in by_priority(v)] for k, v in report.items()}
            if a.nature:
                rows = {k: [r for r in v if r["nature"] == a.nature] for k, v in rows.items()}
            _emit(rows | {"lastPull": t.links["lastPull"]})
        elif a.cmd == "card":
            src = source_for(t.config)
            card = src.card(a.ref)
            if a.download:
                dest = root / "cards" / card["shortLink"] / "attachments"
                for att in card["attachments"]:
                    path = src.download(att, dest)
                    att["path"] = str(path) if path else None
                if card["id"] in t.cards:
                    t.cards[card["id"]]["attachments"] = [
                        {"name": x["name"], "mimeType": x.get("mimeType"), "path": x.get("path"), "url": x["url"]}
                        for x in card["attachments"]]
                    t.save()
            _emit(card)
        elif a.cmd == "show":
            if a.ref:
                cid, c = t.find(a.ref)
                _emit({"card": cid, **c})
            else:
                _emit(t.select(state=a.state, story=a.story, nature=a.nature, include_gone=a.all))
        elif a.cmd == "instructed":
            _emit(t.instructed(a.ref, a.fiche))
            t.save()
        elif a.cmd == "decide":
            _emit(t.decide(a.ref, a.decision, a.reason, a.review))
            t.save()
        elif a.cmd == "link":
            _emit(t.link(a.ref, a.story, a.epic))
            t.save()
        elif a.cmd == "push":
            plan = t.plan(_story_status(a.project))
            if a.only:
                keep = {t.find(r)[0] for r in a.only}
                plan["moves"] = [m for m in plan["moves"] if m["card"] in keep]
            if a.apply:
                src = source_for(t.config)
                lists = t.config["lists"]
                for m in plan["moves"]:
                    src.move(m["card"], lists[m["to"]])
                    if a.comment:
                        stories = ", ".join(f"{s} ({st})" for s, st in m["stories"].items())
                        src.comment(m["card"], f"Suivi SDLC : {stories} → {m['to']}")
                    t.mark_pushed(m["card"], m["to"])
                t.save()
            _emit({"applied": a.apply, **plan})
        elif a.cmd == "forget-push":
            _emit([t.forget_push(t.find(r)[0]) for r in a.refs])
            t.save()
    except (KeyError, ValueError, FileNotFoundError, TrelloError, RuntimeError) as e:
        print(json.dumps({"error": str(e).strip("'\"")}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
