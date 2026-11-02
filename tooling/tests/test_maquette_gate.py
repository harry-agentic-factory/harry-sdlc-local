"""Maquette fidelity: detection, the « Fidélité à la maquette » section, and the gate that refuses a spec
without it.

What these tests pin down, beyond the happy path: a story WITHOUT a maquette must behave exactly as before
(nothing read, nothing refused), a refused gate must leave the workspace byte-for-byte untouched, and the
detection convention must not fire on a document that is not a maquette.
"""
from __future__ import annotations

import pytest

from sdlc import maquette
from sdlc.workspace import CONDITIONAL_SECTIONS, DELIVERABLE_SECTIONS, Workspace

from test_gates import make_f, run, snapshot, verdict_text  # noqa: F401 — shared fixtures and the `run` fixture

SECTION = f"## {maquette.SECTION}"

TABLE = """| Élément | Attendu (maquette) | Jeton / composant du socle | Contrôle |
|---|---|---|---|
| Icônes | quatre pastilles, la 3e répète la 1re | `Icon` | `.exd-icon svg` → `icône` = `file, list, file, file-check` |
| Trait de liaison | pointillé continu | à créer | `.exd-list::before` → `border-left-style` = `dashed` |
| Libellés | semibold, jamais en italique | `--fw-semibold` | `.exd-label` → `font-style` = `normal` |
| Alignement | pastilles alignées | — | `.exd-icon` → `présence` = `oui` |
"""


def spec(maquette_path: str | None = "E/maquettes/e-1-ecran.html", table: str = TABLE,
         deviations: str = "aucun") -> str:
    """A spec-func carrying the conditional section, in the order of the fixed format."""
    head = f"# E-1 — story\n\n## Comportement\n\nrien.\n\n"
    if maquette_path is None and not table:
        return head + "## Critères d'acceptation\n\n- **AC1** — …\n"
    block = SECTION + "\n\n"
    if maquette_path is not None:
        block += f"Maquette : {maquette_path}\n\n"
    block += table + f"\n### Écarts déclarés\n\n{deviations}\n\n"
    return head + block + "## Critères d'acceptation\n\n- **AC1** — …\n"


def with_maquette(ws, run, story="E-1", name="e-1-ecran.html", declare=True, body="<html></html>"):
    folder = ws / "E" / "maquettes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(body)
    if declare:
        run("link", story, "maquette", f"E/maquettes/{name}", ws=ws)
    return f"E/maquettes/{name}"


def write_specs(ws, story="E-1", func=None, tech=None):
    d = ws / "E" / "stories" / story
    (d / "spec-func.md").write_text(func if func is not None else spec())
    (d / "spec-tech.md").write_text(
        tech if tech is not None else spec().replace("## Comportement", "## Invariants")
                                            .replace("## Critères d'acceptation", "## Plan par repo"))


# --- AC1: no maquette, nothing changes -------------------------------------------------------------------------

def test_a_story_without_a_maquette_is_not_concerned(tmp_path, run):
    ws = make_f(tmp_path, run)
    rc, out, err = run("fidelity", "E-1", ws=ws)
    assert rc == 0, err
    story = out["stories"][0]
    assert story["maquette"] is None and story["from"] is None and story["required"] is False


def test_a_gate_passes_for_a_story_without_a_maquette(tmp_path, run):
    ws = make_f(tmp_path, run)
    (ws / "E" / "review-spec-func-verdict.md").write_text(verdict_text(target="E"))
    rc, out, err = run("validate-spec-func", "E", "--verdict", "E/review-spec-func-verdict.md", ws=ws)
    assert rc == 0, err
    assert out["outcome"] == "validated_with_reserves"


def test_check_reads_nothing_when_there_is_no_maquette(tmp_path, run):
    ws = make_f(tmp_path, run)
    ticket = Workspace(ws).load("E-1")
    (ws / "E" / "stories" / "E-1" / "spec-func.md").unlink()  # unreadable on purpose
    assert maquette.check(ticket, ws) == []                   # not even opened


# --- AC2: declaration ------------------------------------------------------------------------------------------

def test_a_declared_maquette_is_reported_with_its_source(tmp_path, run):
    ws = make_f(tmp_path, run)
    path = with_maquette(ws, run)
    write_specs(ws)
    rc, out, err = run("fidelity", "E-1", ws=ws)
    assert rc == 0, err
    story = out["stories"][0]
    assert story["required"] is True and story["from"] == "declared" and story["maquette"] == path
    assert story["specFunc"] == {"section": True, "elements": 4, "gaps": []}
    assert story["specTech"]["elements"] == 4


# --- AC3: nothing but a declaration creates the obligation ----------------------------------------------------

def test_a_maquette_file_alone_does_not_create_the_obligation(tmp_path, run):
    """Deriving the file from the story number was measured on a real repository and mis-attributed 14 of its 17
    detections: the numeric suffix of a maquette is a VERSION number. Only a declaration counts now."""
    ws = make_f(tmp_path, run)
    with_maquette(ws, run, name="e-1-ecran.html", declare=False)
    found = maquette.maquette_of(Workspace(ws).load("E-1"), ws)
    assert found.required is False and found.source is None


@pytest.mark.parametrize("names", [["ecran-1.html"], ["usine-v1.html", "usine-v2.html"], ["e-1-mapping.md"]])
def test_an_epic_with_maquettes_notes_an_undeclared_story(tmp_path, run, names):
    """The only net left cannot be wrong: it reports that a maquette is POSSIBLE, never which file."""
    ws = make_f(tmp_path, run)
    folder = ws / "E" / "maquettes"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_text("x")
    found = maquette.maquette_of(Workspace(ws).load("E-1"), ws)
    assert found.required is False
    html = any(n.endswith(".html") for n in names)
    assert (found.note == maquette.POSSIBLE_UNDECLARED) is html


def test_the_note_is_reported_and_refuses_nothing(tmp_path, run):
    ws = make_f(tmp_path, run)
    with_maquette(ws, run, declare=False)
    rc, out, err = run("fidelity", "E-1", ws=ws)
    assert rc == 0, err
    assert out["stories"][0]["note"] == maquette.POSSIBLE_UNDECLARED
    assert out["stories"][0]["required"] is False
    (ws / "E" / "review-spec-func-verdict.md").write_text(verdict_text(target="E"))
    rc, _out, err = run("validate-spec-func", "E", "--verdict", "E/review-spec-func-verdict.md", ws=ws)
    assert rc == 0, err                        # a note never refuses a gate


def test_a_declared_maquette_has_no_note(tmp_path, run):
    ws = make_f(tmp_path, run)
    with_maquette(ws, run)
    assert maquette.maquette_of(Workspace(ws).load("E-1"), ws).note is None


# --- AC4 and AC5: the gate refuses, and writes nothing ---------------------------------------------------------

def _refuse(ws, run, gate="validate-spec-func", verdict_gate="spec_func"):
    name = f"E/review-{verdict_gate.replace('_', '-')}-verdict.md"
    (ws / name).write_text(verdict_text(gate=verdict_gate, target="E",
                                        review=f"E/review-{verdict_gate.replace('_', '-')}.md"))
    before = snapshot(ws)
    rc, out, err = run(gate, "E", "--verdict", name, ws=ws)
    return rc, out, err, before


def test_the_gate_refuses_a_missing_section_and_writes_nothing(tmp_path, run):
    ws = make_f(tmp_path, run)
    with_maquette(ws, run)                      # declared, but the specs keep their stub
    rc, _out, err, before = _refuse(ws, run)
    assert rc == 1
    assert "maquette_section_missing" in err and "E-1" in err and "spec-func.md" in err
    assert snapshot(ws) == before               # byte for byte


@pytest.mark.parametrize("func,cause", [
    (spec(maquette_path=None), maquette.PATH_LINE_MISSING),
    (spec(table="| Élément | Attendu (maquette) | Jeton / composant du socle | Contrôle |\n|---|---|---|---|\n"),
     maquette.TABLE_EMPTY),
    (spec(maquette_path="E/maquettes/ailleurs.html"), maquette.PATH_MISMATCH),
    (spec(table=TABLE.replace("`.exd-label` → `font-style` = `normal`", "en clair, pas en italique")),
     maquette.CHECK_MALFORMED),
    # A shorthand property is refused by the closed form: its computed value carries what nobody measures.
    (spec(table=TABLE.replace("`border-left-style` = `dashed`", "`border-left` = `1px dashed`")),
     maquette.CHECK_MALFORMED),
])
def test_each_cause_is_named_and_refused(tmp_path, run, func, cause):
    ws = make_f(tmp_path, run)
    with_maquette(ws, run)
    write_specs(ws, func=func)
    rc, _out, err, before = _refuse(ws, run)
    assert rc == 1 and cause in err
    assert snapshot(ws) == before


def test_a_maquette_declared_but_absent_from_disk_is_refused(tmp_path, run):
    ws = make_f(tmp_path, run)
    run("link", "E-1", "maquette", "E/maquettes/jamais-ecrite.html", ws=ws)
    write_specs(ws, func=spec(maquette_path="E/maquettes/jamais-ecrite.html"))
    rc, _out, err, before = _refuse(ws, run)
    assert rc == 1 and maquette.FILE_MISSING in err
    assert snapshot(ws) == before


# --- AC6: a conform section passes -----------------------------------------------------------------------------

def test_a_conform_section_passes_both_spec_gates(tmp_path, run):
    ws = make_f(tmp_path, run)
    with_maquette(ws, run)
    write_specs(ws)
    (ws / "E" / "review-spec-func-verdict.md").write_text(verdict_text(target="E"))
    rc, _out, err = run("validate-spec-func", "E", "--verdict", "E/review-spec-func-verdict.md", ws=ws)
    assert rc == 0, err
    for sid in ("E-1", "E-2"):
        assert run("set-status", sid, "spec_tech", ws=ws)[0] == 0
    (ws / "E" / "review-spec-tech.md").write_text((ws / "E" / "review-spec-func.md").read_text()
                                                  .replace("gate: spec_func", "gate: spec_tech"))
    (ws / "E" / "review-spec-tech-verdict.md").write_text(
        verdict_text(gate="spec_tech", target="E", review="E/review-spec-tech.md"))
    rc, out, err = run("validate-spec-tech", "E", "--verdict", "E/review-spec-tech-verdict.md", ws=ws)
    assert rc == 0, err
    assert run("get", "E-1", ws=ws)[1]["status"] == "spec_validated"


# --- AC7: the feature gate names the story at fault ------------------------------------------------------------

def test_the_feature_gate_names_only_the_story_at_fault(tmp_path, run):
    ws = make_f(tmp_path, run, status="spec_validated")
    with_maquette(ws, run, story="E-1")
    write_specs(ws, story="E-1", tech=spec().replace("## Comportement", "## Invariants")
                                            .replace(SECTION + "\n\n", ""))  # section dropped from spec-tech
    for role in ("po", "techlead"):
        (ws / "E" / f"review-feature-verdict-{role}.md").write_text(
            verdict_text(gate="feature", target="E", review="E/review-feature.md", role=role))
    (ws / "E" / "review-feature.md").write_text((ws / "E" / "review-spec-func.md").read_text()
                                                .replace("gate: spec_func", "gate: feature"))
    before = snapshot(ws)
    rc, _out, err = run("validate-feature", "E", "--verdict", "E/review-feature-verdict-po.md",
                        "--verdict", "E/review-feature-verdict-techlead.md", ws=ws)
    assert rc == 1 and "maquette_section_missing" in err
    assert "E-1" in err and "E-2" not in err and "spec-tech.md" in err
    assert snapshot(ws) == before


# --- AC8: the conditional section in the format contract -------------------------------------------------------

def test_the_conditional_section_is_declared_with_its_index():
    assert CONDITIONAL_SECTIONS["spec-func.md"] == ((maquette.SECTION, 1),)
    assert CONDITIONAL_SECTIONS["spec-tech.md"] == ((maquette.SECTION, 1),)
    # index 1 = right after the first required section of each deliverable
    assert DELIVERABLE_SECTIONS["spec-func.md"][0] == "Comportement"
    assert DELIVERABLE_SECTIONS["spec-tech.md"][0] == "Invariants"


def test_a_scaffolded_story_has_no_empty_conditional_section(tmp_path, run):
    ws = make_f(tmp_path, run)
    for doc in ("spec-func.md", "spec-tech.md"):
        assert maquette.SECTION not in (ws / "E" / "stories" / "E-1" / doc).read_text()


# --- S2: a maquette attached later, and a story with no spec at all --------------------------------------------

def test_a_missing_spec_is_a_fact_not_an_error(tmp_path, run):
    ws = make_f(tmp_path, run)
    with_maquette(ws, run)
    (ws / "E" / "stories" / "E-1" / "spec-func.md").unlink()
    rc, out, err = run("fidelity", "E-1", ws=ws)
    assert rc == 0, err
    assert out["stories"][0]["specFunc"]["gaps"] == [maquette.DOC_MISSING]


def test_over_several_stories_the_note_becomes_one_line_per_epic(tmp_path, run):
    """Per story, the note repeats for every story of an epic that draws maquettes — measured at 86 of 126 on a
    real repository. A signal nobody can read is not a net, so a multi-story query aggregates it."""
    ws = make_f(tmp_path, run)
    with_maquette(ws, run, declare=False)
    rc, out, err = run("fidelity", "E", ws=ws)
    assert rc == 0, err
    assert all("note" not in s for s in out["stories"])
    assert len(out["notes"]) == 1 and out["notes"][0].startswith("E : 2 stories sans maquette déclarée")
    # one story: the note stays where it is the truth about that story
    assert run("fidelity", "E-1", ws=ws)[1]["stories"][0]["note"] == maquette.POSSIBLE_UNDECLARED


def test_no_note_when_the_epic_draws_no_maquette(tmp_path, run):
    ws = make_f(tmp_path, run)
    rc, out, err = run("fidelity", "E", ws=ws)
    assert rc == 0, err
    assert "notes" not in out and all("note" not in s for s in out["stories"])


def test_every_gate_declares_the_documents_it_controls():
    """The two dictionaries must stay in step: a gate added to GATES without its documents used to raise a
    KeyError at gate time. The fallback now covers it, and this test keeps the omission visible."""
    from sdlc import gates

    assert set(gates._MAQUETTE_DOCS) == set(gates.GATES), "a gate has no declared maquette documents"
    for docs in gates._MAQUETTE_DOCS.values():
        assert set(docs) <= set(maquette.DOCS)
