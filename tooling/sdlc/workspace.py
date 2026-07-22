"""Workspace `sample-proj-sdlc-local/` : les .md sont la source de vérité, `status.json` l'état.

Layout :
    <root>/<EPIC>/prd.md, refine.md, _index.md, stories/<STORY>/{spec-*.md, status.json, ...}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STORY_MD = ("spec-func.md", "spec-tech.md", "implement.md", "review.md",
            "deploy.md", "acceptance.md", "demo.md")


@dataclass
class Ticket:
    id: str
    epic: str
    title: str
    status: str = "draft"
    deps: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    branch: str | None = None
    mr: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def next_step(self) -> str | None:
        from .status import PIPELINE, Status
        try:
            i = PIPELINE.index(Status(self.status))
        except ValueError:
            return None
        return PIPELINE[i + 1].value if i + 1 < len(PIPELINE) else None


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- paths ---
    def epic_dir(self, epic: str) -> Path:
        return self.root / epic

    def story_dir(self, epic: str, story: str) -> Path:
        return self.epic_dir(epic) / "stories" / story

    def _status_path(self, epic: str, story: str) -> Path:
        return self.story_dir(epic, story) / "status.json"

    # --- scaffolding ---
    def create_epic(self, epic: str, title: str) -> Path:
        d = self.epic_dir(epic)
        (d / "stories").mkdir(parents=True, exist_ok=True)
        _write_if_absent(d / "prd.md", f"# {epic} — {title}\n\n## Context\n\n## Besoin\n")
        _write_if_absent(d / "refine.md", f"# {epic} — refine\n\n## Stories\n\n## Ordre suggéré\n")
        _write_if_absent(d / "_index.md", f"# {epic} — board\n\n| Story | Statut | MR | Déploiement |\n|---|---|---|---|\n")
        return d

    def create_story(self, ticket: Ticket) -> Path:
        d = self.story_dir(ticket.epic, ticket.id)
        d.mkdir(parents=True, exist_ok=True)
        for name in STORY_MD:
            _write_if_absent(d / name, f"# {ticket.id} — {name.removesuffix('.md')}\n")
        self._save(ticket)
        return d

    # --- state ---
    def _save(self, t: Ticket) -> None:
        payload = {
            "id": t.id, "epic": t.epic, "title": t.title, "status": t.status,
            "deps": t.deps, "repos": t.repos, "branch": t.branch, "mr": t.mr,
            "artifacts": t.artifacts,
        }
        self._status_path(t.epic, t.id).write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def load(self, story: str) -> Ticket:
        p = self._find_status(story)
        if p is None:
            raise KeyError(f"ticket introuvable: {story}")
        data = json.loads(p.read_text())
        return Ticket(**data)

    def save(self, t: Ticket) -> None:
        self._save(t)

    def _find_status(self, story: str) -> Path | None:
        for p in self.root.glob(f"*/stories/{story}/status.json"):
            return p
        return None

    # --- journal des décisions (rejets routés, etc.) — le plus RÉCENT en premier ---
    def journal_add(self, story: str, entry: str) -> Path:
        """Ajoute une entrée en **tête** du journal (newest-first), sous l'en-tête. N'écrase rien
        d'autre (les entrées plus anciennes restent, décalées vers le bas)."""
        sp = self._find_status(story)
        if sp is None:
            raise KeyError(f"ticket introuvable: {story}")
        p = sp.parent / "journal.md"
        header = f"# {story} — journal (le plus récent en premier)"
        older = ""
        if p.exists():
            rest = p.read_text(encoding="utf-8").split("\n", 1)   # retire la ligne d'en-tête
            older = rest[1].strip() if len(rest) > 1 else ""
        parts = [header, "", entry.strip()] + (["", older] if older else [])
        p.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
        return p

    def journal_path(self, story: str) -> Path | None:
        sp = self._find_status(story)
        return (sp.parent / "journal.md") if sp else None

    def all_tickets(self) -> list[Ticket]:
        out: list[Ticket] = []
        for p in sorted(self.root.glob("*/stories/*/status.json")):
            out.append(Ticket(**json.loads(p.read_text())))
        return out


def _write_if_absent(path: Path, content: str) -> None:
    if not path.exists():
        path.write_text(content)
