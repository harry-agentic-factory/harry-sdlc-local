"""Layout of a run workspace and the storage keys it is filled from.

With `datarepo.py`, the only module that knows the storage layout (feature, mission and trace keys).
The core keeps only the keys that match one of the patterns below (Markdown only, story documents
of level 1, `journal.md` and `_index.md` excluded): same filtering whatever the backend returns.

    storage key                                   path under in/
    features/<E>/atelier/<name>.md                feature/atelier/<name>.md
    features/<E>/stories/<US>/<doc>.md            feature/stories/<US>/<doc>.md
    missions/<M>/brief.md                         mission/brief.md
    missions/<M>/sources/<p>.md                   mission/sources/<p>.md
    project/brain/@<commit>/<p>.md                brain/<p>.md
    runs/<uid>/{run.json,manifest.json,out/docs/<type>.md}   (publication only)
"""
from __future__ import annotations

import re
from pathlib import Path

from .port import Scope

RUNS_PREFIX = "runs/"
BRAIN_PREFIX_RE = re.compile(r"^project/brain/@[^/]+/$")

IN_DIRS_STORY = ("in", "in/brain", "in/feature", "in/feature/atelier", "in/feature/stories")
IN_DIRS_MISSION = ("in", "in/brain", "in/mission")
RW_DIRS = ("rw", "rw/code", "rw/scratch", "rw/out", "rw/out/docs", "rw/out/sources", "rw/out/git")
META_FILES = ("manifest.json", "settings.json")

RESERVED_KEYS = {"prd": "feature/atelier/prd.md", "refine": "feature/atelier/refine.md",
                 "brief": "mission/brief.md"}
RESERVED_PREFIXES = ("atelier", "brain", "mission", "repro", "repos")


# --- trace keys ---

def run_key(uid: str, rel: str) -> str:
    return f"{RUNS_PREFIX}{uid}/{rel}"


def doc_key(uid: str, doc_type: str) -> str:
    return run_key(uid, f"out/docs/{doc_type}.md")


def doc_rel(doc_type: str) -> str:
    """Path of a published document relative to `rw/out/`."""
    return f"docs/{doc_type}.md"


def trace_uid(key: str) -> str | None:
    """`<uid>` of a `runs/<uid>/run.json` key, else None."""
    m = re.fullmatch(r"runs/([^/]+)/run\.json", key)
    return m.group(1) if m else None


# --- pull ---

def pull_prefixes(scope: Scope) -> list[str]:
    if scope.mission:
        return [f"missions/{scope.mission}/"]
    return [f"features/{scope.feature}/"]


def safe_segments(rel: str) -> bool:
    """True when `rel` is a clean relative path (no empty, `.`, `..` segment, no NUL/backslash)."""
    if not rel or rel.startswith("/") or "\0" in rel or "\\" in rel:
        return False
    return all(s not in ("", ".", "..") for s in rel.split("/"))


def in_path(key: str, scope: Scope, brain_prefix: str | None) -> str | None:
    """Path under `in/` of a storage key, or None when the key matches no pull pattern."""
    if not key.endswith(".md") or not safe_segments(key):
        return None
    if brain_prefix and BRAIN_PREFIX_RE.fullmatch(brain_prefix) and key.startswith(brain_prefix):
        rest = key[len(brain_prefix):]
        return f"brain/{rest}" if rest else None
    parts = key.split("/")
    if scope.mission:
        if parts[:2] != ["missions", scope.mission]:
            return None
        if parts[2:] == ["brief.md"]:
            return "mission/brief.md"
        if len(parts) >= 4 and parts[2] == "sources":
            return "mission/" + "/".join(parts[2:])
        return None
    if scope.feature is None or parts[:2] != ["features", scope.feature]:
        return None
    if len(parts) == 4 and parts[2] == "atelier" and parts[3] != "_index.md":
        return f"feature/atelier/{parts[3]}"
    if len(parts) == 5 and parts[2] == "stories" and parts[4] != "journal.md":
        return f"feature/stories/{parts[3]}/{parts[4]}"
    return None


def in_dirs(scope: Scope) -> tuple[str, ...]:
    return (IN_DIRS_MISSION if scope.mission else IN_DIRS_STORY) + RW_DIRS


# --- doc read aliases (precedence: reserved keys, reserved prefixes, own story, other story) ---

def alias_candidates(k: str, story: str | None) -> list[str]:
    cands: list[str] = []
    first = k.split("/", 1)[0]
    if k in RESERVED_KEYS:
        cands.append(RESERVED_KEYS[k])
    elif first in RESERVED_PREFIXES and "/" in k:
        rest = k.split("/", 1)[1]
        if first == "atelier":
            cands.append(f"feature/atelier/{rest}.md")
        elif first in ("brain", "mission"):
            cands.append(f"{first}/{rest}.md")
    elif "/" not in k:
        if story:
            cands.append(f"feature/stories/{story}/{k}.md")
    elif k.count("/") == 1:
        us, doc = k.split("/")
        cands.append(f"feature/stories/{us}/{doc}.md")
    cands += [k + ".md", k]
    return cands


def canonical_key(in_key: str) -> str:
    """Shortest logical key of an `in/` path (the form listed by `doc list`)."""
    for alias, target in RESERVED_KEYS.items():
        if in_key == target:
            return alias
    parts = in_key.split("/")
    if in_key.endswith(".md"):
        stem = in_key[:-3]
        if len(parts) == 3 and parts[:2] == ["feature", "atelier"]:
            return "atelier/" + parts[2][:-3]
        if len(parts) == 4 and parts[:2] == ["feature", "stories"]:
            return f"{parts[2]}/{parts[3][:-3]}"
        if parts[0] == "brain" and len(parts) > 1:
            return stem
        if parts[:2] == ["mission", "sources"] and len(parts) > 2:
            return stem
    return in_key


# --- bubble ---

def settings(agent_root: str, bubble: dict) -> dict:
    """`in/settings.json`: only `<A>/in` and `<A>/rw`, `in/**` denied to Edit/Write.

    `"Edit(/" + A + "/in/**)"` with `A` absolute gives `Edit(//abs/in/**)`: in the Claude Code rule
    syntax a leading `//` is an absolute path (`/x` would be relative to the settings file).
    """
    a = agent_root
    perms: dict = {"additionalDirectories": [f"{a}/in", f"{a}/rw"]}
    allow = list(bubble.get("allow") or [])
    if allow:
        perms["allow"] = allow
    perms["deny"] = list(bubble.get("deny") or []) + [f"Edit(/{a}/in/**)", f"Write(/{a}/in/**)"]
    return {"permissions": perms}


def workspace_paths(root: Path) -> dict:
    return {
        "root": str(root), "in": str(root / "in"), "rw": str(root / "rw"),
        "out": str(root / "rw" / "out"), "code": str(root / "rw" / "code"),
        "scratch": str(root / "rw" / "scratch"), "settings": str(root / "in" / "settings.json"),
        "manifest": str(root / "in" / "manifest.json"),
    }
