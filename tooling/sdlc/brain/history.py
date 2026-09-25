"""`history`: `git log --follow` of one note, newest first, renames followed."""
from __future__ import annotations

from pathlib import Path

from . import gitio
from .gitio import BrainError
from .ref import resolve_in


def history(repo: str | Path, path: str, ref: str | None = None) -> list[dict]:
    """[{commit, date, author, message, path}] of `path` (relative to the brain) up to `ref`
    (None = `HEAD`). `path` is the file name at each commit; `author` is the name only."""
    brain = gitio.open_brain(repo)
    commit = resolve_in(brain, ref if ref is not None else "HEAD").commit
    raw = gitio.log_follow(brain.top, commit, brain.prefix + path)
    entries: list[dict] = []
    current = path          # fallback for a commit listed without file name (merge)
    named = True
    for token in raw.split(b"\0"):
        token = token.decode("utf-8", errors="replace").lstrip("\n")
        if not token:
            continue
        if "\x1f" in token:
            sha, date, author, subject = (token.split("\x1f", 3) + ["", "", ""])[:4]
            entries.append({"commit": sha, "date": date, "author": author, "message": subject,
                            "path": current})
            named = False
        elif entries and not named:
            current = token[len(brain.prefix):] if token.startswith(brain.prefix) else token
            entries[-1]["path"] = current
            named = True
    if not entries:
        raise BrainError("note_not_found", f"no history for {path} at {commit}")
    return entries
