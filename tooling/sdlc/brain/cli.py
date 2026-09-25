"""`sdlc brain <sub>`: thin CLI wrapper over the `sdlc.brain` library.

Exit codes: 0 success (including `lint` with warnings only); 1 `lint` found errors (or warnings
with `--strict`); 2 `BrainError` (usage, refusal, unknown ref, missing/non git brain, git
failure) and native argparse errors.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from .diff import diff_manifests, diff_refs, load_manifest
from .history import history
from .lint import format_text, lint
from .normalize import normalize, render_markdown
from .snapshot import snapshot


@dataclass
class CommandResult:
    payload: object
    exit_code: int = 0
    text: str | None = None


def _common(p: argparse.ArgumentParser, *, repo_help: str = "brain folder (a git work tree or a sub-folder of one)"):
    p.add_argument("--repo", required=True, help=repo_help)


def _exclude(p: argparse.ArgumentParser) -> None:
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="extra exclusion (repeatable; a trailing '/' means a folder); added to the defaults")


def _map(p: argparse.ArgumentParser) -> None:
    p.add_argument("--map", default=None, metavar="YAML",
                   help="mapping file on disk (default: brain-map.yaml read at the commit, if any)")


def add_parser(sub) -> argparse.ArgumentParser:
    b = sub.add_parser("brain", help="brain (git knowledge repo): normalize, lint, snapshot, diff, history",
                       description="Read a brain at a git commit; propose category headers on a new branch.")
    bs = b.add_subparsers(dest="braincmd", required=True, metavar="<brain-cmd>")

    a = bs.add_parser("normalize", help="add deduced `category` headers on a NEW branch (never main, no push)")
    _common(a); _map(a); _exclude(a)
    a.add_argument("--base", default=None, help="base ref (default: main, then master)")
    a.add_argument("--branch", default=None, help="new branch (default: brain/normalize-<YYYYMMDD-HHMM>)")
    a.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    a.add_argument("--report", default=None, metavar="FILE.md", help="also write the report as Markdown")

    a = bs.add_parser("lint", help="check the notes of a commit (exit 1 on errors)")
    _common(a); _map(a); _exclude(a)
    a.add_argument("--ref", default=None, help="ref to lint (default: HEAD)")
    a.add_argument("--strict", action="store_true", help="broken links become errors")
    a.add_argument("--format", choices=["json", "text"], default="json", help="output format")

    a = bs.add_parser("snapshot", help="write the exact notes of a commit + manifest.json + links.json")
    _common(a); _map(a); _exclude(a)
    a.add_argument("--ref", required=True, help="branch, tag or sha")
    a.add_argument("--out", required=True, help="output folder (created; must be empty)")

    a = bs.add_parser("diff", help="file by file diff: --repo R <refA> <refB> | --manifests <a.json> <b.json>")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--repo", help="brain folder (git mode)")
    g.add_argument("--manifests", nargs=2, metavar=("A_JSON", "B_JSON"), help="compare two manifest.json (no git)")
    a.add_argument("refs", nargs="*", metavar="REF", help="two refs in git mode")
    a.set_defaults(_diff_parser=a)

    a = bs.add_parser("history", help="git log --follow of one note, newest first")
    _common(a)
    a.add_argument("file", help="note path relative to the brain")
    a.add_argument("--ref", default=None, help="ref (default: HEAD)")
    return b


def dispatch(args: argparse.Namespace) -> CommandResult:
    cmd = args.braincmd
    if cmd == "lint":
        res = lint(args.repo, args.ref, excludes=args.exclude, map_path=args.map, strict=args.strict)
        code = res.pop("exit")
        return CommandResult(res, code, format_text(res) if args.format == "text" else None)
    if cmd == "snapshot":
        return CommandResult(snapshot(args.repo, args.ref, args.out, excludes=args.exclude, map_path=args.map))
    if cmd == "normalize":
        rep = normalize(args.repo, base=args.base, branch=args.branch, map_path=args.map,
                        excludes=args.exclude, dry_run=args.dry_run)
        if args.report:
            Path(args.report).expanduser().write_text(render_markdown(rep), encoding="utf-8")
        return CommandResult(rep)
    if cmd == "diff":
        parser = args._diff_parser
        if args.manifests:
            if args.refs:
                parser.error("--manifests takes no REF")
            a, b = (load_manifest(p) for p in args.manifests)
            return CommandResult(diff_manifests(a, b))
        if len(args.refs) != 2:
            parser.error("git mode needs exactly two refs: --repo R <refA> <refB>")
        return CommandResult(diff_refs(args.repo, args.refs[0], args.refs[1]))
    if cmd == "history":
        return CommandResult(history(args.repo, args.file, args.ref))
    raise SystemExit(2)
