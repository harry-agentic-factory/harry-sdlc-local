"""What is running right now: one activity file per project, `<workspace>/_live.json`.

Agents and the orchestrator declare what they are doing through `sdlc-view activity
start|beat|stop|list`; the board and the page only read the file.

File format (schema version 1):

    {
      "version": 1,
      "running": [ {id, epic, story, what, agent, startedAt, lastBeat}, ... ],
      "recent":  [ {... same fields ..., endedAt, result, note}, ... ]   # newest first, capped
    }

Writes are atomic (temporary file in the same folder, then `os.replace`) and serialised by an
advisory lock taken on the workspace folder itself (no extra lock file), so two agents stopping at
the same second do not lose an entry.
The read path (`read_activity`) never creates, locks or rewrites anything.
"""
from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1
FILENAME = "_live.json"
RESULTS: tuple[str, ...] = ("ok", "ko", "cancelled")
# No heartbeat for this long → the entry is shown as stale (agent probably dead or stuck).
STALE_AFTER = _dt.timedelta(minutes=15)
RECENT_KEPT = 20      # finished entries kept in the file
RECENT_SHOWN = 10     # finished entries exposed by the snapshot, per project and per epic
WHAT_MAX = 200
NOTE_MAX = 500


class ActivityError(ValueError):
    pass


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).isoformat(timespec="seconds")


def _parse(iso: str | None) -> _dt.datetime | None:
    if not iso:
        return None
    try:
        t = _dt.datetime.fromisoformat(iso)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def _empty() -> dict:
    return {"version": SCHEMA_VERSION, "running": [], "recent": []}


def _clean(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = " ".join(str(text).split())
    return text[:limit] if text else None


def _load(path: Path) -> dict:
    """Parse the activity file. Missing → empty. Unreadable or newer schema → ActivityError."""
    if not path.is_file():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ActivityError(f"{path} illisible : {e}") from None
    if not isinstance(data, dict):
        raise ActivityError(f"{path} : contenu inattendu (objet JSON attendu)")
    version = data.get("version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        raise ActivityError(f"{path} : version de schéma {version!r} non supportée "
                            f"(max {SCHEMA_VERSION}) — mets sdlc-view à jour")
    running = [e for e in data.get("running") or [] if isinstance(e, dict) and e.get("id")]
    recent = [e for e in data.get("recent") or [] if isinstance(e, dict) and e.get("id")]
    return {"version": SCHEMA_VERSION, "running": running, "recent": recent}


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write `payload` so that a reader sees either the old or the new file, never a partial one."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def with_liveness(entry: dict, now: _dt.datetime) -> dict:
    """Copy of a running entry with `stale`, `elapsedS` and `idleS` computed against `now`."""
    out = dict(entry)
    started = _parse(entry.get("startedAt"))
    beat = _parse(entry.get("lastBeat")) or started
    out["elapsedS"] = int((now - started).total_seconds()) if started else None
    out["idleS"] = int((now - beat).total_seconds()) if beat else None
    out["stale"] = beat is None or now - beat >= STALE_AFTER
    return out


def read_activity(workspace: str | Path, now: _dt.datetime | None = None,
                  recent_limit: int = RECENT_SHOWN) -> dict:
    """Read-only view of a project's activity: running entries (with liveness) and recent ones.

    Never raises for a bad file: the problem is reported in `error` so one broken project does
    not hide the others on the board.
    """
    now = now or _utcnow()
    path = Path(workspace).expanduser() / FILENAME
    try:
        data = _load(path)
    except ActivityError as e:
        return {"running": [], "recent": [], "error": str(e)}
    running = sorted((with_liveness(e, now) for e in data["running"]),
                     key=lambda e: e.get("startedAt") or "")
    return {"running": running, "recent": data["recent"][:recent_limit]}


class ActivityStore:
    """The only writer of `<workspace>/_live.json`. `clock` is injectable for tests."""

    def __init__(self, workspace: str | Path, clock=None) -> None:
        self.root = Path(workspace).expanduser()
        if not self.root.is_dir():
            raise ActivityError(f"workspace introuvable : {self.root}")
        self.path = self.root / FILENAME
        self.clock = clock or _utcnow

    @contextmanager
    def _locked(self):
        fd = os.open(self.root, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            data = _load(self.path)
            yield data
            atomic_write_json(self.path, data)
        finally:
            os.close(fd)                 # closing the descriptor releases the lock

    def _new_id(self, now: _dt.datetime, taken: set[str]) -> str:
        while True:
            aid = f"act-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
            if aid not in taken:
                return aid

    def start(self, epic: str, what: str, story: str | None = None, agent: str | None = None) -> dict:
        epic = _clean(epic, 100)
        what = _clean(what, WHAT_MAX)
        if not epic:
            raise ActivityError("--epic est obligatoire")
        if not what:
            raise ActivityError("--what est obligatoire (libellé court de ce qui tourne)")
        now = self.clock()
        with self._locked() as data:
            taken = {e["id"] for e in data["running"] + data["recent"]}
            entry = {"id": self._new_id(now, taken), "epic": epic, "story": _clean(story, 100),
                     "what": what, "agent": _clean(agent, 60),
                     "startedAt": _iso(now), "lastBeat": _iso(now)}
            data["running"].append(entry)
        return dict(entry)

    def _find_running(self, data: dict, aid: str) -> dict:
        for e in data["running"]:
            if e["id"] == aid:
                return e
        if any(e["id"] == aid for e in data["recent"]):
            raise ActivityError(f"activité déjà terminée : {aid}")
        raise KeyError(f"activité inconnue : {aid}")

    def beat(self, aid: str) -> dict:
        now = self.clock()
        with self._locked() as data:
            entry = self._find_running(data, aid)
            entry["lastBeat"] = _iso(now)
        return with_liveness(entry, now)

    def stop(self, aid: str, result: str = "ok", note: str | None = None) -> dict:
        if result not in RESULTS:
            raise ActivityError(f"résultat invalide : {result!r} (attendu : {' | '.join(RESULTS)})")
        now = self.clock()
        with self._locked() as data:
            entry = self._find_running(data, aid)
            data["running"].remove(entry)
            started = _parse(entry.get("startedAt"))
            entry.update({"endedAt": _iso(now), "result": result, "note": _clean(note, NOTE_MAX),
                          "durationS": int((now - started).total_seconds()) if started else None})
            data["recent"] = [entry, *data["recent"]][:RECENT_KEPT]
        return dict(entry)

    def list(self) -> dict:
        return {"workspace": str(self.root), "file": str(self.path),
                **read_activity(self.root, now=self.clock(), recent_limit=RECENT_KEPT)}
