"""`sdlc maquette extract | verdict`: reading the closed form of the `Contrôle` column, and the comparison rule.

The replay on the reference case proves the COMPARATOR, not the measurement — the measurement is a manual run of
the recette-ui procedure, consigned in the story's `acceptance.md`. Keeping the two apart is the whole point: in
the case this fixture comes from, 99 pixel-alignment checks were green while the screen had lost its icons.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdlc import maquette

FIXTURE = Path(__file__).parent / "fixtures" / "maquette" / "uipolish3-parcours"
SPEC = FIXTURE / "spec-func.md"
MEASURES = FIXTURE / "mesures-06a270d4.json"


def items_of(text: str) -> list[maquette.Item]:
    section = maquette.read_section(text)
    assert section is not None
    return section.items


# --- AC11: extract --------------------------------------------------------------------------------------------

def test_extract_parses_the_closed_form():
    items = items_of(SPEC.read_text(encoding="utf-8"))
    assert [i.id for i in items] == ["icones", "trait", "italique"]
    first = items[0]
    assert first.control == maquette.Control(".exd-icon svg", "icône", "file, list, file, file-check")
    assert first.invalid is False
    assert items[1].control.prop == "border-left-style"


def test_a_cell_outside_the_closed_form_is_invalid():
    text = SPEC.read_text(encoding="utf-8").replace(
        "`.exd-label` → `font-style` = `normal`", "en clair, pas en italique")
    items = items_of(text)
    assert items[2].control is None and items[2].invalid is True


def test_a_shorthand_property_is_invalid():
    """A shorthand's computed value carries what nobody measures, so string comparison could never match."""
    text = SPEC.read_text(encoding="utf-8").replace("`border-left-style` = `dashed`", "`border-left` = `1px dashed`")
    assert items_of(text)[1].invalid is True


def test_the_path_line_and_the_deviations_are_read():
    section = maquette.read_section(SPEC.read_text(encoding="utf-8"))
    assert section.path_line == "UIPOLISH/maquettes/nouvelle-feature-v7.html"
    assert section.deviations == "aucun."


def test_a_spec_without_the_section_reads_as_none():
    assert maquette.read_section("# S\n\n## Comportement\n\nrien.\n") is None


# --- AC12: the comparison rule ---------------------------------------------------------------------------------

def test_conform_measures_give_no_deviation():
    items = items_of(SPEC.read_text(encoding="utf-8"))
    measures = {i.id: {"obtenu": i.control.value} for i in items}
    assert maquette.compare(items, measures) == []


def test_an_unmeasured_element_is_never_a_success():
    items = items_of(SPEC.read_text(encoding="utf-8"))
    measures = {i.id: {"obtenu": i.control.value} for i in items[1:]}
    out = maquette.compare(items, measures)
    assert [(d.id, d.cause) for d in out] == [("icones", maquette.NOT_MEASURED)]


def test_an_invalid_control_is_a_deviation():
    text = SPEC.read_text(encoding="utf-8").replace("`font-style` = `normal`", "normal")
    items = items_of(text)
    out = maquette.compare(items, {i.id: {"obtenu": "x"} for i in items})
    assert ("italique", maquette.CHECK_INVALID) in [(d.id, d.cause) for d in out]


def test_the_comparison_normalises_spaces_and_case():
    items = items_of(SPEC.read_text(encoding="utf-8"))
    measures = {i.id: {"obtenu": f"  {i.control.value.upper()}  "} for i in items}
    assert maquette.compare(items, measures) == []


def test_a_comma_list_is_an_ORDERED_sequence():
    """A set would collapse the duplicate: the reference expectation repeats `file` at steps 1 and 3, and an
    unordered comparison would accept a screen that drew them in any order, or dropped one."""
    items = [i for i in items_of(SPEC.read_text(encoding="utf-8")) if i.id == "icones"]
    assert maquette.compare(items, {"icones": {"obtenu": "file, list, file, file-check"}}) == []
    swapped = maquette.compare(items, {"icones": {"obtenu": "list, file, file, file-check"}})
    assert [d.cause for d in swapped] == [maquette.VALUE_DIFFERS]
    deduped = maquette.compare(items, {"icones": {"obtenu": "file, list, file-check"}})
    assert [d.cause for d in deduped] == [maquette.VALUE_DIFFERS]


# --- AC13: the replay of the reference case --------------------------------------------------------------------

def test_rejeu_uipolish3():
    """The three deviations the delivered screen carried, and nothing else."""
    items = items_of(SPEC.read_text(encoding="utf-8"))
    measures = json.loads(MEASURES.read_text(encoding="utf-8"))
    out = maquette.compare(items, measures)
    assert [d.id for d in out] == ["icones", "trait", "italique"]
    assert all(d.cause == maquette.VALUE_DIFFERS for d in out)
    assert [(d.expected, d.obtained) for d in out] == [
        ("file, list, file, file-check", "circle-dashed, circle-dashed, circle-dashed, circle-dashed"),
        ("dashed", "none"),
        ("normal", "italic"),
    ]


def test_the_fixture_holds_data_only():
    """No maquette HTML, no source file of the screen under test: the engine does not carry third-party code.
    The proof of the MEASUREMENT lives in the story's acceptance.md, not here."""
    assert sorted(p.name for p in FIXTURE.iterdir()) == ["mesures-06a270d4.json", "spec-func.md"]


# --- the CLI, including its exit code --------------------------------------------------------------------------

def test_the_cli_extracts_then_renders_a_failing_verdict(tmp_path, capsys, monkeypatch):
    from sdlc import cli

    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path))
    assert cli.main(["maquette", "extract", str(SPEC)]) == 0
    checklist = tmp_path / "checklist.json"
    checklist.write_text(capsys.readouterr().out)
    parsed = json.loads(checklist.read_text())
    assert parsed[0]["controle"]["propriete"] == "icône" and parsed[0]["invalide"] is False

    # The only subcommand with a business exit code: a deviation must fail a script that calls it.
    assert cli.main(["maquette", "verdict", str(checklist), str(MEASURES)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in payload["écarts"]] == ["icones", "trait", "italique"]
    assert payload["éléments"] == 3 and payload["mesurés"] == 3

    conform = tmp_path / "conform.json"
    conform.write_text(json.dumps({o["id"]: {"obtenu": o["controle"]["valeur"]} for o in parsed},
                                  ensure_ascii=False))
    assert cli.main(["maquette", "verdict", str(checklist), str(conform)]) == 0


def test_extract_refuses_a_spec_without_the_section(tmp_path, capsys, monkeypatch):
    from sdlc import cli

    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path))
    spec = tmp_path / "spec-func.md"
    spec.write_text("# S\n\n## Comportement\n\nrien.\n")
    assert cli.main(["maquette", "extract", str(spec)]) == 1
    assert maquette.SECTION in capsys.readouterr().err


# --- a truncated or header-less table must never lose an element in silence -----------------------------------

TRUNCATED = """## Fidélité à la maquette

Maquette : a.html

| Élément | Attendu | Socle | Contrôle |
|---|---|---|---|
| Icônes | quatre | Icon | `.a` → `font-style` = `normal` |
| Trait | pointillé | à créer |
| Italique | non |

### Écarts déclarés

aucun.
"""

NO_HEADER = """## Fidélité à la maquette

Maquette : a.html

| Icônes | quatre | Icon | `.a` → `font-style` = `normal` |
| Trait | pointillé | à créer | `.b` → `border-left-style` = `dashed` |

### Écarts déclarés

aucun.
"""


def test_a_truncated_row_is_kept_and_marked_invalid():
    """Dropping it removed a visual element from the checklist in silence: `extract` would not list it,
    `verdict` would not claim it, and the screen would ship with an element nobody ever measured."""
    items = items_of(TRUNCATED)
    assert [i.id for i in items] == ["icones", "trait", "italique"]
    assert [i.invalid for i in items] == [False, True, True]


def test_a_truncated_row_refuses_a_gate(tmp_path):
    from sdlc.workspace import Ticket, Workspace

    ws = Workspace(tmp_path)
    ws.create_epic("E", "t")
    ws.create_story(Ticket(id="E-1", epic="E", title="t", artifacts={"maquette": "E/maquettes/a.html"}))
    (tmp_path / "E" / "maquettes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "E" / "maquettes" / "a.html").write_text("<html></html>")
    for doc in ("spec-func.md", "spec-tech.md"):
        (tmp_path / "E" / "stories" / "E-1" / doc).write_text(
            TRUNCATED.replace("Maquette : a.html", "Maquette : E/maquettes/a.html"))
    gaps = maquette.check(ws.load("E-1"), tmp_path)
    assert [g.cause for g in gaps] == [maquette.CHECK_MALFORMED, maquette.CHECK_MALFORMED]


def test_a_table_without_a_header_keeps_its_first_element():
    """A header row is the one a separator FOLLOWS. Skipping `the first row` dropped the first element."""
    items = items_of(NO_HEADER)
    assert [i.id for i in items] == ["icones", "trait"]
    assert all(not i.invalid for i in items)


def test_the_cli_counts_an_invalid_element_as_not_measured(tmp_path, capsys, monkeypatch):
    """AC12's third case, at CLI level: the shape `mesurés` ends up verbatim in acceptance.md."""
    from sdlc import cli

    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path))
    spec = tmp_path / "spec-func.md"
    spec.write_text(TRUNCATED)
    assert cli.main(["maquette", "extract", str(spec)]) == 0
    checklist = tmp_path / "c.json"
    checklist.write_text(capsys.readouterr().out)
    measures = tmp_path / "m.json"
    measures.write_text(json.dumps({"icones": {"obtenu": "normal"}}, ensure_ascii=False))
    assert cli.main(["maquette", "verdict", str(checklist), str(measures)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["éléments"] == 3 and payload["mesurés"] == 1
    assert sorted(e["cause"] for e in payload["écarts"]) == [maquette.CHECK_INVALID, maquette.CHECK_INVALID]
