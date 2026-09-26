"""`DataRepoBackend`: the storage port on a local data repository and its brain.

The only module of the package that knows the data repository layout, the project manifest, the
brain library and git. Git is used READ ONLY on the data repository, through one helper (`_git`)
restricted to `rev-parse`, `ls-files`, `diff` and `log`, always with `--no-optional-locks`. Nothing
is ever committed: publication leaves the data repository modified, as an agent writing it would.

Storage keys (see `layout.py`) map to the data repository as follows:

    features/<E>/atelier/<name>.md        <ws>/<E>/<name>.md   (every root *.md but _index.md)
    features/<E>/stories/<US>/<doc>.md    <ws>/<E>/stories/<US>/<doc>.md  (level 1, not journal.md)
    missions/<M>/brief.md, sources/...    <ws>/missions/<M>/...
    runs/<uid>/...                        <ws>/runs/<uid>/...
    project/brain/@<commit>/<p>.md        brain notes at <commit> (sdlc.brain library)
    project/brain/@worktree/<p>.md        brain working copy (fallback when the brain is not git)
"""
from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .. import agentws
from ..brain import (DEFAULT_EXCLUDES, BrainError, BrainNotGit, BrainRefUnresolved, is_excluded,
                     list_notes, parse_mapping, read_notes, resolve_brain_ref)
from ..config import load_config, resolved_manifest
from ..service import Sdlc
from ..workspace import Workspace
from .layout import safe_segments
from .model import (FINAL_STATES, ROUND_HEADER_BYTES_RE, RUN_UID_RE, RunError, iso, sha256, utc_now,
                    validate_run_uid, validate_scope_id)
from .port import BrainPin, Entry, Scope

GIT_READ_SUBCOMMANDS = frozenset({"rev-parse", "ls-files", "diff", "log"})
_SCRUBBED_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX")
_BRAIN_WORKTREE_SKIP = {"node_modules", "_toDelete", "_wt", "_agentws"}
BRAIN_MAP_FILE = "brain-map.yaml"


def _read_regular(path: Path) -> bytes | None:
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _is_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _md_files(folder: Path) -> list[str]:
    """Names of the regular `*.md` files directly in `folder` (no symbolic link), sorted."""
    try:
        with os.scandir(folder) as it:
            return sorted(e.name for e in it if e.name.endswith(".md") and e.is_file(follow_symlinks=False))
    except OSError:
        return []


def _sub_dirs(folder: Path) -> list[str]:
    try:
        with os.scandir(folder) as it:
            return sorted(e.name for e in it if e.is_dir(follow_symlinks=False))
    except OSError:
        return []


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class DataRepoBackend:
    """`DocumentRepository` + `RunSource` on a data repository (plus workspace discovery)."""

    def __init__(self, manifest: dict, brain_ref: str | None = None):
        self.manifest = manifest
        self.ws = Path(manifest["workspace"])
        self.prefix = manifest.get("prefix")
        self.brain_path = manifest.get("brain")
        self.brain_ref = brain_ref
        self.permissions = manifest.get("permissions") or {}
        self._cache: dict[str, tuple[bytes, str | None]] = {}
        self._brain_commit: str | None = None
        self._brain_notes: list | None = None
        self._brain_excludes: tuple[str, ...] = tuple(DEFAULT_EXCLUDES)

    @classmethod
    def from_project(cls, project: str | None = None) -> "DataRepoBackend":
        man = resolved_manifest(project)
        cfg = load_config(man["workspace"])
        return cls(man, cfg.get("brainRef"))

    # --- workspace discovery (outside the port) ---

    def default_root(self, scope_id: str) -> Path:
        return agentws.agentws_path(self.manifest, validate_scope_id(scope_id))

    def _agent_base(self) -> Path:
        return agentws.agentws_path(self.manifest, "_").parent

    def iter_workspaces(self) -> Iterator[Path]:
        base = self._agent_base()
        for scope_dir in _sub_dirs(base):
            for name in _sub_dirs(base / scope_dir):
                if RUN_UID_RE.fullmatch(name) and _read_regular(base / scope_dir / name / "run.json") is not None:
                    yield base / scope_dir / name

    def find_workspace(self, uid: str) -> Path | None:
        validate_run_uid(uid)
        for w in self.iter_workspaces():
            if w.name == uid:
                return w
        return None

    # --- git, read only ---

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        if not args or args[0] not in GIT_READ_SUBCOMMANDS:
            raise RunError("git_refused", f"git sub-command not allowed: {args[:1]}")
        env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_ENV}
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_LITERAL_PATHSPECS"] = "1"
        return subprocess.run(["git", "--no-optional-locks", "-C", str(self.ws), *args],
                              capture_output=True, env=env, check=False)

    def _data_versions(self, rels: list[str], scope_rel: str) -> dict[str, str | None]:
        """Version of each data file: sha of the last commit touching it, None if dirty/untracked."""
        out: dict[str, str | None] = {r: None for r in rels}
        if not rels:
            return out
        p = self._git("rev-parse", "--is-inside-work-tree")
        if p.returncode != 0 or p.stdout.strip() != b"true":
            return out
        if self._git("rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
            return out
        tracked = self._git("ls-files", "-z", "--", scope_rel)
        modified = self._git("diff", "--name-only", "-z", "--relative", "HEAD", "--", scope_rel)
        if tracked.returncode != 0 or modified.returncode != 0:
            return out
        tracked_set = {x.decode("utf-8", "surrogateescape") for x in tracked.stdout.split(b"\0") if x}
        modified_set = {x.decode("utf-8", "surrogateescape") for x in modified.stdout.split(b"\0") if x}
        for rel in rels:
            if rel not in tracked_set or rel in modified_set:
                continue
            log = self._git("log", "-1", "--format=%H", "--", rel)
            sha = log.stdout.decode().strip()
            out[rel] = sha if log.returncode == 0 and sha else None
        return out

    # --- storage key <-> data repository path ---

    def _data_rel(self, key: str) -> str | None:
        """Path relative to the data repository of a data key (None if not a data key)."""
        if not safe_segments(key):
            return None
        parts = key.split("/")
        if parts[0] == "features" and len(parts) == 4 and parts[2] == "atelier":
            return f"{parts[1]}/{parts[3]}"
        if parts[0] == "features" and len(parts) == 5 and parts[2] == "stories":
            return f"{parts[1]}/stories/{parts[3]}/{parts[4]}"
        if parts[0] == "missions" and len(parts) >= 3:
            return key
        if parts[0] == "runs" and len(parts) >= 3:
            return key
        return None

    def _entries(self, keyed: list[tuple[str, str]], scope_rel: str | None) -> list[Entry]:
        """Entries for [(key, rel)] read from the data repository (versions when `scope_rel`)."""
        found: list[tuple[str, str, bytes]] = []
        for key, rel in keyed:
            data = _read_regular(self.ws / rel)
            if data is not None:
                found.append((key, rel, data))
        versions = self._data_versions([r for _, r, _ in found], scope_rel) if scope_rel else {}
        out: list[Entry] = []
        for key, rel, data in found:
            v = versions.get(rel)
            self._cache[key] = (data, v)
            out.append(Entry(key=key, version=v, sha256=sha256(data), size=len(data), origin=rel))
        return sorted(out, key=lambda e: e["key"])

    def _feature_keys(self, epic: str) -> list[tuple[str, str]]:
        base = self.ws / epic
        keyed = [(f"features/{epic}/atelier/{n}", f"{epic}/{n}") for n in _md_files(base) if n != "_index.md"]
        for us in _sub_dirs(base / "stories"):
            for n in _md_files(base / "stories" / us):
                if n != "journal.md":
                    keyed.append((f"features/{epic}/stories/{us}/{n}", f"{epic}/stories/{us}/{n}"))
        return keyed

    def _mission_keys(self, mission: str) -> list[tuple[str, str]]:
        base = self.ws / "missions" / mission
        keyed: list[tuple[str, str]] = []
        if "brief.md" in _md_files(base):
            keyed.append((f"missions/{mission}/brief.md", f"missions/{mission}/brief.md"))
        src = base / "sources"
        if _is_dir(src):
            for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if not os.path.islink(os.path.join(dirpath, d)))
                for n in sorted(filenames):
                    full = Path(dirpath) / n
                    if n.endswith(".md") and not full.is_symlink():
                        rel = full.relative_to(self.ws).as_posix()
                        keyed.append((rel, rel))
        return keyed

    def _trace_keys(self) -> list[tuple[str, str]]:
        base = self.ws / "runs"
        return [(f"runs/{u}/run.json", f"runs/{u}/run.json") for u in _sub_dirs(base)
                if RUN_UID_RE.fullmatch(u) and _read_regular(base / u / "run.json") is not None]

    # --- brain ---

    def brain(self) -> BrainPin:
        self._brain_commit, self._brain_notes = None, None
        if not self.brain_path or not os.path.isdir(self.brain_path):
            return BrainPin(None, None, None, None, None, ("brain_missing",))
        try:
            rr = resolve_brain_ref(self.brain_path, self.brain_ref)
        except BrainNotGit:
            try:
                self._brain_excludes = self._brain_worktree_excludes()
            except BrainError:
                return BrainPin(None, None, None, None, None, ("brain_map_invalid", "brain_not_git"))
            return BrainPin(None, None, None, "project/brain/@worktree/", None, ("brain_not_git",))
        except BrainRefUnresolved:
            return BrainPin(self.brain_ref, None, None, None, None, ("brain_ref_unresolved",))
        except BrainError as e:
            if e.code == "brain_not_found":
                return BrainPin(None, None, None, None, None, ("brain_missing",))
            raise
        try:
            notes = list_notes(self.brain_path, rr.commit)
        except BrainError as e:
            if e.code.startswith("mapping_"):
                return BrainPin(rr.ref, rr.commit, rr.source, None, None, ("brain_map_invalid",))
            raise
        self._brain_commit, self._brain_notes = rr.commit, notes
        return BrainPin(rr.ref, rr.commit, rr.source, f"project/brain/@{rr.commit}/", len(notes), ())

    def _brain_commit_entries(self, commit: str) -> list[Entry]:
        if self._brain_commit != commit or self._brain_notes is None:
            self._brain_notes = list_notes(self.brain_path, commit)
            self._brain_commit = commit
        notes = self._brain_notes
        contents = read_notes(self.brain_path, commit, [n.path for n in notes]) if notes else {}
        out: list[Entry] = []
        for n in notes:
            data = contents[n.path]
            key = f"project/brain/@{commit}/{n.path}"
            self._cache[key] = (data, n.blob)
            out.append(Entry(key=key, version=n.blob, sha256=sha256(data), size=len(data), origin=n.path))
        return sorted(out, key=lambda e: e["key"])

    def _brain_worktree_excludes(self) -> tuple[str, ...]:
        """Default exclusions + `exclude:` of `brain-map.yaml` read on disk (BrainError if invalid)."""
        data = _read_regular(Path(self.brain_path) / BRAIN_MAP_FILE)
        excludes = tuple(DEFAULT_EXCLUDES)
        if data is not None:
            excludes += parse_mapping(data, BRAIN_MAP_FILE).excludes
        return excludes

    def _brain_worktree_list(self) -> list[Entry]:
        """Fallback when the brain is not git: every `*.md` of its working copy."""
        root = Path(self.brain_path)
        out: list[Entry] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in _BRAIN_WORKTREE_SKIP
                                 and not os.path.islink(os.path.join(dirpath, d)))
            for n in sorted(filenames):
                if not n.endswith(".md"):
                    continue
                rel = (Path(dirpath) / n).relative_to(root).as_posix()
                if is_excluded(rel, self._brain_excludes):
                    continue
                data = self._brain_worktree_read(rel)
                if data is None:
                    continue
                key = f"project/brain/@worktree/{rel}"
                self._cache[key] = (data, None)
                out.append(Entry(key=key, version=None, sha256=sha256(data), size=len(data), origin=rel))
        return sorted(out, key=lambda e: e["key"])

    def _brain_worktree_read(self, rel: str) -> bytes | None:
        if not safe_segments(rel):
            return None
        return _read_regular(Path(self.brain_path) / rel)

    # --- RunSource ---

    def locate(self, *, story: str | None, mission: str | None) -> Scope:
        if not os.path.isdir(self.ws):
            raise RunError("workspace_not_found", str(self.ws))
        if story is not None:
            validate_scope_id(story)
            try:
                t = Workspace(self.ws).load(story)
            except KeyError as e:
                raise RunError("story_unknown", story) from e
            return Scope(t.epic, story, None)
        validate_scope_id(mission)
        if _read_regular(self.ws / "missions" / mission / "brief.md") is None:
            raise RunError("mission_unknown", mission)
        return Scope(None, None, mission)

    def bubble(self, agent: str) -> dict:
        perms = self.permissions
        role = ((perms.get("agents") or {}).get(agent) or {})
        return {"allow": list(role.get("allow") or []), "deny": list(perms.get("deny") or [])}

    # --- DocumentRepository ---

    def list(self, prefix: str) -> list[Entry]:
        parts = prefix.split("/")
        if prefix.startswith("project/brain/@") and len(parts) >= 3:
            at = parts[2][1:]
            if at == "worktree":
                if not self.brain_path:
                    return []
                entries = self._brain_worktree_list()
            else:
                entries = self._brain_commit_entries(at)
        elif parts[0] == "features" and len(parts) >= 2 and parts[1]:
            entries = self._entries(self._feature_keys(validate_scope_id(parts[1])), parts[1])
        elif parts[0] == "missions" and len(parts) >= 2 and parts[1]:
            m = validate_scope_id(parts[1])
            entries = self._entries(self._mission_keys(m), f"missions/{m}")
        elif parts[0] == "runs":
            entries = self._entries(self._trace_keys(), None)
        else:
            return []
        return [e for e in entries if e["key"].startswith(prefix)]

    def get(self, key: str, version: str | None = None) -> bytes:
        cached = self._cache.get(key)
        if cached is not None and (version is None or version == cached[1]):
            return cached[0]
        if version is not None:
            raise KeyError(f"{key}@{version}")
        if key.startswith("project/brain/@worktree/"):
            data = self._brain_worktree_read(key[len("project/brain/@worktree/"):]) if self.brain_path else None
        elif key.startswith("project/brain/@"):
            at, _, rel = key[len("project/brain/@"):].partition("/")
            try:
                data = read_notes(self.brain_path, at, [rel])[rel] if self.brain_path and rel else None
            except BrainError as e:
                if e.code != "note_not_found":
                    raise
                data = None
        else:
            rel = self._data_rel(key)
            data = _read_regular(self.ws / rel) if rel else None
        if data is None:
            raise KeyError(key)
        return data

    def versions(self, key: str) -> list[str]:
        cached = self._cache.get(key)
        if key.startswith("project/brain/@"):
            return [cached[1]] if cached and cached[1] else []
        rel = self._data_rel(key)
        if rel is None:
            return []
        log = self._git("log", "--format=%H", "--", rel)
        return [x for x in log.stdout.decode().split() if x] if log.returncode == 0 else []

    @contextmanager
    def _lock(self):
        lock = self.ws / "runs" / ".lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a+b") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def put(self, key: str, content: bytes, meta: dict) -> dict:
        parts = key.split("/")
        if not safe_segments(key) or len(parts) < 3 or parts[0] != "runs" or not RUN_UID_RE.fullmatch(parts[1]):
            raise RunError("put_invalid_key", key)
        rel = "/".join(parts[2:])
        doc_type = None
        if len(parts) == 5 and parts[2:4] == ["out", "docs"] and parts[4].endswith(".md"):
            doc_type = parts[4][:-3]
        elif rel not in ("run.json", "manifest.json"):
            raise RunError("put_invalid_key", key)
        uid = parts[1]
        with self._lock():
            self._put_add_only(self.ws / key, content, key)
            res: dict = {"key": key, "version": None}
            if doc_type is not None:
                if meta.get("story"):
                    res["round"] = self._publish_story_doc(uid, doc_type, content, meta)
                else:
                    res["round"] = self._mission_round(uid, doc_type, meta.get("mission"))
        return res

    def _put_add_only(self, path: Path, content: bytes, key: str) -> None:
        if os.path.lexists(path):
            if _read_regular(path) != content:
                raise RunError("put_conflict", key)
            return
        _write_atomic(path, content)

    def _publish_story_doc(self, uid: str, doc_type: str, content: bytes, meta: dict) -> int:
        story = validate_scope_id(meta["story"])
        epic = Workspace(self.ws).load(story).epic
        rel = f"{epic}/stories/{story}/{doc_type}.md"
        target = self.ws / rel
        old = b""
        if os.path.lexists(target):
            data = _read_regular(target)
            if data is None:
                raise RunError("put_conflict", rel)
            old = data
        rounds = []
        for line in old.split(b"\n"):
            m = ROUND_HEADER_BYTES_RE.fullmatch(line.rstrip(b"\r"))
            if m:
                if m.group(2).decode() == uid:
                    return int(m.group(1))            # replay after a crash: already rendered
                rounds.append(int(m.group(1)))
        n = max(rounds, default=0) + 1
        at = meta.get("at") or iso(utc_now())
        header = f"<!-- round {n} · run {uid} · agent {meta.get('agent')} · {at} -->".encode("utf-8")
        new = header + b"\n" + content + (b"" if content.endswith(b"\n") else b"\n") \
            + (b"\n" if old else b"") + old
        _write_atomic(target, new)
        Sdlc(Workspace(self.ws)).link_artifact(story, doc_type, rel)
        return n

    def _mission_round(self, uid: str, doc_type: str, mission: str | None) -> int:
        n = 0
        for key, rel in self._trace_keys():
            if key == f"runs/{uid}/run.json":
                continue
            try:
                run = json.loads((self.ws / rel).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if run.get("mission") != mission or run.get("state") not in FINAL_STATES:
                continue
            if any(isinstance(p, dict) and p.get("type") == doc_type for p in run.get("published") or []):
                n += 1
        return n + 1
