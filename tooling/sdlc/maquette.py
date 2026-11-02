"""Maquette fidelity: a story's maquette, the « Fidélité à la maquette » section of its specs, and the one
comparison rule the recette replays.

Only an explicit declaration (`artifacts.maquette`) creates the obligation. Deriving the file from the story
number was tried and dropped: measured over a real data repository, it mis-attributed 14 of its 17 detections,
because the numeric suffix of a maquette is a VERSION number. A mis-detection fails closed and misleading — a gate
refuses while naming someone else's maquette — where a non-detection fails open and visible. A project that wants
a naming convention declares it in its manifest, never in the engine.

What remains is a net that cannot be wrong: when an epic holds maquettes and a story declares none, the state
report says a maquette is POSSIBLE. It never guesses which file.

Everything that reads the section or compares values lives here, and nowhere else: `sdlc maquette` and the gates
both call it.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

SECTION = "Fidélité à la maquette"
DOCS = ("spec-func.md", "spec-tech.md")
MAQUETTE_SUFFIX = ".html"

# The closed form of the `Contrôle` column: `<selector>` → `<property>` = `<value>`.
CHECK_RE = re.compile(r"^`(?P<selector>[^`]+)`\s*(?:→|->)\s*`(?P<prop>[^`]+)`\s*=\s*`(?P<value>[^`]+)`$")
# Properties that are not CSS: the name of the expected icons, or plain presence.
PSEUDO_PROPS = frozenset({"icône", "icone", "présence", "presence"})
# A shorthand's computed value carries what nobody measures (`1px dashed rgb(…)`), so string comparison could
# never match it. Only longhand is accepted.
SHORTHANDS = frozenset({
    "animation", "background", "border", "border-bottom", "border-color", "border-left", "border-radius",
    "border-right", "border-style", "border-top", "border-width", "flex", "font", "gap", "grid", "grid-area",
    "grid-template", "inset", "list-style", "margin", "outline", "overflow", "padding", "place-content",
    "place-items", "text-decoration", "transition",
})

POSSIBLE_UNDECLARED = "maquette possible, non déclarée"

# Gap causes, each distinct so a refused gate says which one applies.
DOC_MISSING = "document absent"
SECTION_MISSING = "section absente"
PATH_LINE_MISSING = "ligne « Maquette : » absente"
TABLE_EMPTY = "table vide"
FILE_MISSING = "fichier de maquette absent du disque"
PATH_MISMATCH = "chemin de la section différent du chemin déclaré"
CHECK_MALFORMED = "contrôle hors forme fermée"

# Deviation causes.
VALUE_DIFFERS = "valeur différente"
NOT_MEASURED = "non mesuré"
CHECK_INVALID = "contrôle hors forme"


# --- detection ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Detection:
    """What the engine knows about a story's maquette. `path` is None when there is none to control."""
    path: Path | None = None
    source: str | None = None  # "declared" — the only way in
    note: str | None = None
    relative: str | None = None  # as declared, relative to the data repository

    @property
    def required(self) -> bool:
        return self.path is not None


def maquette_of(ticket, root: str | Path) -> Detection:
    """The declared maquette, or none. A declared path absent from disk is still returned: the caller reports
    it, rather than silently behaving as if the story had no maquette."""
    declared = (ticket.artifacts or {}).get("maquette")
    if declared:
        return Detection(Path(root) / declared, "declared", relative=declared)
    folder = Path(root) / ticket.epic / "maquettes"
    if folder.is_dir() and any(p.is_file() and p.suffix == MAQUETTE_SUFFIX for p in folder.iterdir()):
        # The epic draws maquettes and this story declares none: worth a question in review, never a refusal.
        return Detection(note=POSSIBLE_UNDECLARED)
    return Detection()


# --- the section ----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Control:
    selector: str
    prop: str
    value: str


@dataclass(frozen=True)
class Item:
    id: str
    element: str
    expected: str
    token: str
    control: Control | None = None
    invalid: bool = False


@dataclass
class Section:
    path_line: str | None = None
    items: list[Item] = field(default_factory=list)
    deviations: str | None = None


def slug(label: str) -> str:
    bare = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", bare.lower())).strip("-")


def parse_control(cell: str) -> tuple[Control | None, bool]:
    """The closed form, or `(None, True)` — malformed, or a shorthand property."""
    m = CHECK_RE.match(cell.strip())
    if m is None:
        return None, True
    prop = m.group("prop").strip()
    if prop.lower() not in PSEUDO_PROPS and prop.lower() in SHORTHANDS:
        return None, True
    return Control(m.group("selector").strip(), prop, m.group("value").strip()), False


def _cells(line: str) -> list[str]:
    raw = line.strip().strip("|")
    return [c.strip() for c in raw.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def read_section(text: str) -> Section | None:
    """The `## Fidélité à la maquette` section of a spec, or None when it has none."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == f"## {SECTION}"), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    body, out, in_deviations, deviations = lines[start + 1:end], Section(), False, []
    header_seen = False
    for line in body:
        stripped = line.strip()
        if stripped.startswith("### "):
            in_deviations = slug(stripped[4:]) == slug("Écarts déclarés")
            continue
        if in_deviations:
            deviations.append(line)
            continue
        if out.path_line is None and stripped.lower().startswith("maquette :"):
            out.path_line = stripped.split(":", 1)[1].strip().strip("`")
            continue
        if not stripped.startswith("|"):
            continue
        cells = _cells(stripped)
        if _is_separator(cells):
            continue
        if not header_seen:
            header_seen = True  # the column names
            continue
        if len(cells) < 4:
            continue
        control, invalid = parse_control(cells[3])
        out.items.append(Item(slug(cells[0]), cells[0], cells[1], cells[2], control, invalid))
    joined = "\n".join(deviations).strip()
    out.deviations = joined or None
    return out


# --- what a gate refuses --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Gap:
    story: str
    doc: str
    cause: str

    def __str__(self) -> str:
        return f"{self.story} · {self.doc} : {self.cause}"


def read_spec(root: str | Path, ticket, doc: str) -> tuple[Section | None, bool]:
    """`(section, exists)` — a missing document is a fact, never an exception."""
    path = Path(root) / ticket.epic / "stories" / ticket.id / doc
    if not path.is_file():
        return None, False
    return read_section(path.read_text(encoding="utf-8")), True


def check(ticket, root: str | Path, docs: tuple[str, ...] = DOCS) -> list[Gap]:
    """Everything that makes a mocked-up story's spec non-conform, one gap per cause. Empty when the story has
    no maquette: the caller's code path is then exactly the one it was before."""
    found = maquette_of(ticket, root)
    if not found.required:
        return []
    gaps: list[Gap] = []
    exists = found.path is not None and found.path.is_file()
    for doc in docs:
        section, present = read_spec(root, ticket, doc)
        if not present:
            gaps.append(Gap(ticket.id, doc, DOC_MISSING))
            continue
        if section is None:
            gaps.append(Gap(ticket.id, doc, SECTION_MISSING))
            continue
        if not section.path_line:
            gaps.append(Gap(ticket.id, doc, PATH_LINE_MISSING))
        elif found.relative and section.path_line != found.relative:
            gaps.append(Gap(ticket.id, doc, PATH_MISMATCH))
        if not section.items:
            gaps.append(Gap(ticket.id, doc, TABLE_EMPTY))
        elif any(i.invalid for i in section.items):
            gaps.append(Gap(ticket.id, doc, CHECK_MALFORMED))
        if not exists:
            gaps.append(Gap(ticket.id, doc, FILE_MISSING))
    return gaps


# --- the comparison rule, here and nowhere else ---------------------------------------------------------------

@dataclass(frozen=True)
class Deviation:
    id: str
    expected: str
    obtained: str | None
    cause: str


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _equal(expected: str, obtained: str) -> bool:
    if "," in expected:
        # An ordered sequence, never a set: the reference expectation repeats one drawing twice, and a set
        # would collapse the duplicate.
        want = [_normalize(p) for p in expected.split(",")]
        got = [_normalize(p) for p in obtained.split(",")]
        return want == got
    return _normalize(expected) == _normalize(obtained)


def compare(items: list[Item], measures: dict) -> list[Deviation]:
    out: list[Deviation] = []
    for item in items:
        if item.invalid or item.control is None:
            out.append(Deviation(item.id, "", None, CHECK_INVALID))
            continue
        measured = measures.get(item.id)
        obtained = (measured or {}).get("obtenu") if isinstance(measured, dict) else measured
        if obtained is None:
            out.append(Deviation(item.id, item.control.value, None, NOT_MEASURED))
            continue
        if not _equal(item.control.value, str(obtained)):
            out.append(Deviation(item.id, item.control.value, str(obtained), VALUE_DIFFERS))
    return out


# --- the state report -----------------------------------------------------------------------------------------

def report(ticket, root: str | Path) -> dict:
    found = maquette_of(ticket, root)
    out: dict = {
        "id": ticket.id,
        "maquette": found.relative,
        "from": found.source,
        "required": found.required,
    }
    if found.note:
        out["note"] = found.note
    gaps = check(ticket, root) if found.required else []
    for doc in DOCS:
        section, present = read_spec(root, ticket, doc)
        key = "specFunc" if doc == "spec-func.md" else "specTech"
        out[key] = {
            "section": section is not None,
            "elements": len(section.items) if section else 0,
            "gaps": [g.cause for g in gaps if g.doc == doc] if present else ([DOC_MISSING] if found.required else []),
        }
    return out
