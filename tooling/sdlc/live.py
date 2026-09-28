"""Read-only, cross-project snapshot of the SDLC board (`sdlc live`, and the data behind `sdlc view`).

For every project in the registry (`~/.claude/sdlc/projects.json`) it lists the epics, their stories
with status, a progress count and, when the epic has one, a summary of `decisions-autonomie.md`.

Strictly read-only: nothing is created, migrated or rewritten. In particular `Workspace()` creates its
root folder when built, so it is only instantiated once the folder is known to exist.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from .project import list_projects
from .status import PIPELINE
from .workspace import Workspace

# Statuses counted as "done" for the progress bar. `merged` is not an engine status today but is
# accepted in case a data repo ever uses it.
DONE_STATUSES: frozenset[str] = frozenset({"recette_ok", "accepted", "done", "merged"})
# Statuses written by humans/agents outside the engine's state-machine: the story no longer counts
# toward the epic's total, it is reported separately.
EXCLUDED_STATUSES: frozenset[str] = frozenset({"abandoned", "superseded"})

DECISIONS_FILE = "decisions-autonomie.md"
# Legend of the decisions files: decided by Anis / Harry's hypothesis to validate / blocked.
DECISION_MARKERS: dict[str, str] = {"✅": "decided", "🟡": "pending", "⛔": "blocked"}
# A decision/action row starts with an id such as D12, A3, A24b. Other tables of the file (story
# status recap, etc.) are ignored even if they carry markers.
_DECISION_ID = re.compile(r"^[A-Z]{1,2}\d+[a-z]?$")
_MARKER = re.compile("|".join(map(re.escape, DECISION_MARKERS)))

PIPELINE_ORDER: list[str] = [s.value for s in PIPELINE]


def _natural_key(story_id: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", story_id))


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat(timespec="seconds")


def progress(statuses: list[str]) -> dict:
    """Progress of a set of stories: abandoned/superseded stories are left out of the total."""
    excluded = sum(1 for s in statuses if s in EXCLUDED_STATUSES)
    total = len(statuses) - excluded
    done = sum(1 for s in statuses if s in DONE_STATUSES)
    return {"done": done, "total": total, "excluded": excluded,
            "percent": round(100 * done / total) if total else None}


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_decisions(text: str) -> dict:
    """Count decision markers in the tables of a `decisions-autonomie.md`.

    Only table rows whose first cell is a decision/action id are counted (legend lines and recap
    tables are not). For each row, the marker is taken from the LAST cell that has one, and inside
    that cell from its first marker: a status column wins over a marker quoted in the free text.
    """
    counts = {v: 0 for v in DECISION_MARKERS.values()}
    counts["unmarked"] = 0
    open_items: list[dict] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = _split_row(line)
        if not cells or not _DECISION_ID.match(cells[0].strip("*")):
            continue
        marker = None
        for cell in reversed(cells[1:]):
            m = _MARKER.search(cell)
            if m:
                marker = m.group(0)
                break
        kind = DECISION_MARKERS.get(marker, "unmarked") if marker else "unmarked"
        counts[kind] += 1
        if kind in ("pending", "blocked"):
            label = max(cells[1:], key=len) if len(cells) > 1 else ""
            open_items.append({"id": cells[0].strip("*"), "kind": kind, "text": _shorten(label)})
    return {**counts, "open": open_items}


def _shorten(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _epic_title(epic_dir: Path) -> str | None:
    prd = epic_dir / "prd.md"
    if not prd.is_file():
        return None
    try:
        with prd.open(encoding="utf-8") as f:
            first = f.readline().strip()
    except OSError:
        return None
    title = first.lstrip("#").strip()
    # "EPIC — Title", "PRD — EPIC · Title", "PRD — EPIC : Title" → "Title".
    _, found, tail = title.partition(epic_dir.name)
    if found:
        tail = tail.lstrip(" —-·:").strip()
        if tail:
            return tail
    return title or None


def _epic_dirs(root: Path) -> list[Path]:
    return sorted(d for d in root.iterdir()
                  if d.is_dir() and not d.name.startswith((".", "_"))
                  and ((d / "stories").is_dir() or (d / "prd.md").is_file()))


def project_snapshot(prefix: str, workspace: str | Path) -> dict:
    root = Path(workspace).expanduser()
    # An empty path would resolve to the CWD: treat it as missing.
    exists = bool(str(workspace).strip()) and root.is_dir()
    out: dict = {"prefix": prefix, "workspace": str(workspace), "exists": exists, "epics": []}
    if not exists:
        return out
    try:
        tickets = Workspace(root).all_tickets()
    except Exception as e:  # noqa: BLE001 - one broken status.json must not hide the other projects
        out["error"] = f"lecture impossible : {e}"
        return out

    by_epic: dict[str, list] = {}
    for t in tickets:
        by_epic.setdefault(t.epic, []).append(t)
    epic_names = {d.name for d in _epic_dirs(root)} | set(by_epic)

    for name in epic_names:
        d = root / name
        stories = sorted(by_epic.get(name, []), key=lambda t: _natural_key(t.id))
        mtimes = [p.stat().st_mtime for p in d.glob("stories/*/status.json")]
        decisions = None
        dec = d / DECISIONS_FILE
        if dec.is_file():
            decisions = parse_decisions(dec.read_text(encoding="utf-8", errors="replace"))
            mtimes.append(dec.stat().st_mtime)
        statuses = [t.status for t in stories]
        counts: dict[str, int] = {}
        for s in statuses:
            counts[s] = counts.get(s, 0) + 1
        out["epics"].append({
            "id": name,
            "title": _epic_title(d),
            "stories": [{"id": t.id, "title": t.title, "status": t.status, "deps": t.deps,
                         "branch": t.branch, "supersededBy": t.supersededBy} for t in stories],
            "counts": counts,
            "progress": progress(statuses),
            "decisions": decisions,
            "updatedAt": _iso(max(mtimes) if mtimes else None),
        })
    # Most recently touched epics first.
    out["epics"].sort(key=lambda e: e["updatedAt"] or "", reverse=True)
    out["progress"] = progress([s["status"] for e in out["epics"] for s in e["stories"]])
    return out


def snapshot(project: str | None = None) -> dict:
    """Snapshot of every registered project, or only `project` when given."""
    projects = list_projects()
    if project is not None:
        if project not in projects:
            raise KeyError(f"projet inconnu : {project} (connus : {', '.join(sorted(projects)) or 'aucun'})")
        projects = {project: projects[project]}
    return {
        "generatedAt": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds"),
        "pipeline": PIPELINE_ORDER,
        "doneStatuses": sorted(DONE_STATUSES),
        "excludedStatuses": sorted(EXCLUDED_STATUSES),
        "projects": [project_snapshot(prefix, (cfg or {}).get("workspace", ""))
                     for prefix, cfg in projects.items()],
    }
