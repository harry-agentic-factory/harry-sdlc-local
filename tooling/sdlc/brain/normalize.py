"""`normalize`: add a `category` header, deduced from the path, to the notes lacking one.

The change is proposed on a NEW branch, built with plumbing only (new blobs, a temporary index,
`commit-tree`, `update-ref <ref> <sha> ""`): no worktree, no checkout, so the working copy, the
repository index and the current branch are out of reach, and no filter/hook can alter bytes.
No push, no merge request.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Iterable

from . import gitio
from .frontmatter import insert_category, parse_frontmatter
from .gitio import BrainError
from .links import broken, links_for
from .mapping import CATEGORIES, deduce
from .notes import collect, read_blobs
from .ref import resolve_in

COMMIT_MESSAGE = "docs(brain): add category headers"
PROTECTED = ("main", "master")


def default_branch(now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now()
    return f"brain/normalize-{now.strftime('%Y%m%d-%H%M')}"


def _check_branch(brain, branch: str) -> None:
    if not gitio.check_branch_name(brain.top, branch):
        raise BrainError("branch_invalid", f"invalid branch name: {branch!r}")
    protected = set(PROTECTED)
    origin_head = gitio.symbolic_ref(brain.top, "refs/remotes/origin/HEAD")
    if origin_head and origin_head.startswith("refs/remotes/origin/"):
        protected.add(origin_head[len("refs/remotes/origin/"):])
    if branch in protected:
        raise BrainError("branch_protected", f"refusing to write on protected branch {branch!r}")
    if gitio.verify_commit(brain.top, f"refs/heads/{branch}"):
        raise BrainError("branch_exists", f"branch already exists: {branch!r}")


def normalize(repo: str | Path, *, base: str | None = None, branch: str | None = None,
              map_path: str | Path | None = None, excludes: Iterable[str] = (),
              dry_run: bool = False, now: _dt.datetime | None = None) -> dict:
    """Classify the notes at `base` (None = `main` then `master`) and, unless `dry_run`, commit
    the deduced headers on the new branch `branch`. Returns the report."""
    brain = gitio.open_brain(repo)
    rr = resolve_in(brain, base)
    target = branch or default_branch(now)
    if not dry_run:
        _check_branch(brain, target)           # every refusal happens before any write
    ns = collect(brain, rr.commit, excludes=excludes, map_path=map_path)
    contents = read_blobs(brain, ns.notes)
    rules = ns.mapping.effective_rules()
    deduced, already, invalid, undecidable = [], [], [], []
    new_bytes: dict[str, bytes] = {}
    for note in ns.notes:
        data = contents[note.path]
        fm = parse_frontmatter(data)
        if fm.error or (fm.category is not None and fm.category not in CATEGORIES):
            invalid.append(note.path)
        elif fm.category is not None:
            already.append(note.path)
        else:
            found = deduce(note.path, rules)
            if found is None:
                undecidable.append(note.path)
            else:
                deduced.append({"path": note.path, "category": found[0], "rule": found[1]})
                new_bytes[note.path] = insert_category(data, fm, found[0])
    counts = {c: n for c in CATEGORIES if (n := sum(1 for d in deduced if d["category"] == c))}
    report = {
        "commit_base": rr.commit, "branch": None, "commit": None, "counts": counts,
        "deduced": deduced, "already": already, "invalid": invalid, "undecidable": undecidable,
        "broken_links": broken(links_for(contents, brain.repo_names)),
    }
    if dry_run or not deduced:
        return report
    modes = {n.path: n.mode for n in ns.notes}
    entries = [(modes[p], gitio.hash_object(brain.top, b), brain.prefix + p) for p, b in new_bytes.items()]
    sha = gitio.commit_entries(brain.top, rr.commit, entries, COMMIT_MESSAGE)
    gitio.create_branch_ref(brain.top, target, sha)
    report["branch"] = target
    report["commit"] = sha
    return report


def render_markdown(report: dict) -> str:
    """The report as Markdown, ready to paste in a merge request (every section present)."""
    def items(values: list[str]) -> list[str]:
        return [f"- `{v}`" for v in values] or ["_none_"]

    out = ["# Brain normalization report", "",
           f"- Base commit: `{report['commit_base']}`",
           f"- Branch: `{report['branch']}`" if report["branch"] else "- Branch: _none (dry run or nothing to do)_",
           f"- Commit: `{report['commit']}`" if report["commit"] else "- Commit: _none_",
           "", "## Distribution", ""]
    if report["counts"]:
        out += ["| category | notes |", "|---|---|"]
        out += [f"| {c} | {n} |" for c, n in report["counts"].items()]
    else:
        out.append("_none_")
    out += ["", f"## Deduced ({len(report['deduced'])})", ""]
    out += [f"- `{d['path']}` -> {d['category']} (rule `{d['rule']}`)" for d in report["deduced"]] or ["_none_"]
    out += ["", f"## Already classified ({len(report['already'])})", ""] + items(report["already"])
    out += ["", f"## Invalid ({len(report['invalid'])})", ""] + items(report["invalid"])
    out += ["", f"## Undecidable ({len(report['undecidable'])})", ""] + items(report["undecidable"])
    out += ["", f"## Broken links ({len(report['broken_links'])})", ""]
    out += [f"- `{b['from']}:{b['line']}` {b['kind']} -> `{b['target']}` (`{b['to']}`)"
            for b in report["broken_links"]] or ["_none_"]
    return "\n".join(out) + "\n"
