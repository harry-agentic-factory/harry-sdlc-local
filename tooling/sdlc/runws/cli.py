"""`sdlc run <sub>`, `sdlc doc <sub>` and `sdlc clone`: thin CLI wrappers over the run workspace library.

`run` and `clone` commands use the data repository backend of the project; `doc` commands only need
the run workspace (`--run <root>` or `SDLC_RUN`) and never resolve a project.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .docs import doc_add, doc_list, doc_read
from .lifecycle import code_clone, run_clean, run_finish, run_init, run_list
from .model import DOC_TYPES


def add_parsers(sub) -> None:
    r = sub.add_parser("run", help="run workspace of an autonomous agent: init, finish, clean, list",
                       description="Create a run workspace (in/ read only, rw/ writable), publish what the "
                                   "agent added, then remove it. See docs/run-workspace.md.")
    rs = r.add_subparsers(dest="runcmd", required=True, metavar="<run-cmd>")
    a = rs.add_parser("init", help="create a run workspace for a story (or --mission) and an agent role")
    a.add_argument("story", nargs="?", default=None, help="story ID (exclusive with --mission)")
    a.add_argument("--agent", default=None, help="agent role (reviewer, dev, ...); required")
    a.add_argument("--phase", default=None, help="phase recorded in run.json (default: the agent role)")
    a.add_argument("--mission", default=None, help="mission ID (exclusive with STORY)")
    a.add_argument("--branch", default=None,
                   help="code run: story branch of the target repositories (default: branch of the story)")
    a.add_argument("--base", default=None, help="code run: base branch (default: refBranch of the manifest)")
    a.add_argument("--repro", default=None, help="code run: run uid whose published repro goes to in/repro/")
    a.add_argument("--repro-dir", dest="repro_dir", default=None,
                   help="code run: absolute folder whose *.md go to in/repro/ (exclusive with --repro)")
    a.add_argument("--status", default=None, help="code run: story transition applied before the run is created")
    a = rs.add_parser("finish", help="check, publish into the data repository, then remove the workspace")
    a.add_argument("run", help="run uid or workspace path")
    a.add_argument("--keep", action="store_true", help="keep the workspace after publication (debug)")
    a.add_argument("--status", default=None,
                   help="code run: story transition applied once the run is published")
    a = rs.add_parser("clean", help="remove a run workspace without publishing anything")
    a.add_argument("run", help="run uid or workspace path")
    a = rs.add_parser("list", help="open/rejected workspaces and published traces")
    a.add_argument("story", nargs="?", default=None, help="filter on the story of run.json")
    a.add_argument("--mission", default=None, help="filter on the mission of run.json")

    c = sub.add_parser("clone", help="clone the code of an open run (runWorkspace projects)",
                       description="Clone the target repositories of the story into rw/code/ and the other "
                                   "repositories into in/repos/ (read only) of an existing run whose rw/code/ is "
                                   "empty. See docs/run-workspace.md.")
    c.add_argument("--run", required=True, help="run workspace root")
    c.add_argument("--branch", default=None, help="story branch (default: branch of the story)")
    c.add_argument("--base", default=None, help="base branch (default: refBranch of the manifest)")

    d = sub.add_parser("doc", help="agent side of a run: read, list, add documents",
                       description="Read the documents of the current run by logical key, add produced "
                                   "documents. The run is --run <root> or the SDLC_RUN environment variable.")
    ds = d.add_subparsers(dest="doccmd", required=True, metavar="<doc-cmd>")
    a = ds.add_parser("read", help="write the raw bytes of a document to stdout")
    a.add_argument("key", help="logical key: prd, refine, spec-tech, <US>/<doc>, brain/<path>, brief, ...")
    a.add_argument("--run", default=None, help="run workspace root (default: $SDLC_RUN)")
    a = ds.add_parser("list", help="every available key with its version (JSON)")
    a.add_argument("--run", default=None, help="run workspace root (default: $SDLC_RUN)")
    a = ds.add_parser("add", help="add a produced document once per type")
    a.add_argument("type", help="document type: " + ", ".join(DOC_TYPES))
    a.add_argument("source", help="file to add, or - for stdin")
    a.add_argument("--run", default=None, help="run workspace root (default: $SDLC_RUN)")


def _backend(project: str | None):
    from .datarepo import DataRepoBackend
    return DataRepoBackend.from_project(project)


def dispatch(args: argparse.Namespace):
    if args.cmd == "doc":
        if args.doccmd == "read":
            return doc_read(args.key, run=args.run)
        if args.doccmd == "list":
            return doc_list(run=args.run)
        if args.doccmd == "add":
            data = sys.stdin.buffer.read() if args.source == "-" else Path(args.source).read_bytes()
            return doc_add(args.type, data, run=args.run)
    if args.cmd == "run":
        if args.runcmd == "init":
            return run_init(args.project, agent=args.agent, story=args.story, mission=args.mission,
                            phase=args.phase, branch=args.branch, base=args.base, repro=args.repro,
                            repro_dir=args.repro_dir, status=args.status)
        if args.runcmd == "finish":
            from ..brain.cli import CommandResult
            res = run_finish(args.run, backend=_backend(args.project), keep=args.keep, status=args.status)
            return CommandResult(res, 1) if res.get("state") == "rejected" else res
        if args.runcmd == "clean":
            return run_clean(args.run, backend=_backend(args.project))
        if args.runcmd == "list":
            return run_list(args.project, story=args.story, mission=args.mission)
    if args.cmd == "clone":
        return code_clone(args.run, backend=_backend(args.project), branch=args.branch, base=args.base)
    raise SystemExit(2)
