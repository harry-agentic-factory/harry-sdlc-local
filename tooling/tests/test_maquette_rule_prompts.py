"""The prompts that carry the maquette fidelity: the comparison step of `recette-ui` and the gate grid.

What this pins down is ORDER, not just presence: the comparison must come before the step concludes, because the
defect it closes is a passe that measured alignment to the pixel and never looked at the drawing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from sdlc import maquette

REPO = Path(__file__).resolve().parents[2]
RECETTE_UI = REPO / "claude" / "skills" / "recette-ui" / "SKILL.md"
HARRY_ARCHI = REPO / "claude" / "agents" / "harry-archi.md"
COMMANDS = REPO / "claude" / "commands"


def headings(text: str) -> list[str]:
    return re.findall(r"(?m)^##\s+(.+)$", text)


# --- the comparison step of recette-ui -------------------------------------------------------------------------

def test_the_comparison_step_sits_between_the_criteria_and_the_discipline():
    titles = headings(RECETTE_UI.read_text(encoding="utf-8"))
    compare = next(i for i, h in enumerate(titles) if "Comparaison à la maquette" in h)
    criteria = next(i for i, h in enumerate(titles) if h.startswith("2. Vérifier chaque critère"))
    discipline = next(i for i, h in enumerate(titles) if h.startswith("3. Discipline"))
    assert criteria < compare < discipline


def test_the_comparison_step_keeps_the_four_points_in_order():
    text = RECETTE_UI.read_text(encoding="utf-8")
    step = text.split("Comparaison à la maquette", 1)[1].split("\n## ", 1)[0]
    order = [step.index(k) for k in ("Servir la maquette", "Captures côte à côte", "Élément par élément",
                                     "mesures d'alignement au pixel, qui closent")]
    assert order == sorted(order), "the alignment measurements close the step, they do not open it"


def test_the_comparison_step_is_mandatory_and_blocks_a_pass():
    step = RECETTE_UI.read_text(encoding="utf-8").split("Comparaison à la maquette", 1)[1].split("\n## ", 1)[0]
    assert "obligatoire" in step
    assert "sans valeur obtenue" in step and "`pass`" in step
    assert "sdlc maquette extract" in step and "sdlc maquette verdict" in step


def test_the_comparison_step_names_no_script():
    """The tool is a CLI subcommand: `sdlc` is a launcher injecting PYTHONPATH, and install.sh does not link
    claude/scripts, so a script there could not import the engine module."""
    assert list((REPO / "claude" / "scripts").glob("maquette_*")) == []
    assert "claude/scripts/maquette" not in RECETTE_UI.read_text(encoding="utf-8")


# --- the gate grid ---------------------------------------------------------------------------------------------

def test_the_gate_grid_asks_about_the_maquette_and_produces_a_blocking_finding():
    section = re.search(r"^## Mode document de revue.*?(?=^## )", HARRY_ARCHI.read_text(encoding="utf-8"),
                        re.M | re.S).group(0)
    for word in (maquette.SECTION, "contredit-elle la maquette", "`B<n>`", "preuve", "n'entre pas dans ton "
                 "périmètre", maquette.POSSIBLE_UNDECLARED):
        assert word in section, word


# --- the conditional section in every prompt that writes a spec ------------------------------------------------

@pytest.mark.parametrize("command", ["spec-func", "spec-tech", "full-spec"])
def test_every_spec_writing_prompt_mentions_the_conditional_section(command):
    assert maquette.SECTION in (COMMANDS / f"{command}.md").read_text(encoding="utf-8")


def test_the_one_pass_command_states_both_halves_of_the_defect():
    """`full-spec.md` duplicates the fixed formats IN PROSE and allows skipping the functional spec. Both had to
    be amended, or a story framed in one pass would be refused by a gate the prompt never mentioned."""
    text = (COMMANDS / "full-spec.md").read_text(encoding="utf-8")
    assert text.count(maquette.SECTION) == 2, "one mention per prose enumeration of a fixed format"
    skip = text.split("Adaptatif", 1)[1].split("\n\n", 1)[0]
    assert "sauf si la" in skip and "maquette" in skip


def test_the_closed_form_is_described_where_a_spec_is_written():
    for command in ("spec-func", "spec-tech"):
        text = (COMMANDS / f"{command}.md").read_text(encoding="utf-8")
        assert "forme fermée" in text and "longhand" in text
        assert "suite ordonnée" in text
