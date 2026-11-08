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


# --- the rule itself: written once, carried everywhere (story -2) ----------------------------------------------

PERSONA = REPO / "claude" / "sdlc" / "harry.md"
RULE_TITLE = "La maquette est une exigence"
POINTER = ("> **Quand la story a une maquette** : règle « La maquette est une exigence » de la persona "
           "(`~/.claude/sdlc/harry.md`).")
CARRIERS = [f"claude/commands/{c}.md" for c in ("spec-func", "spec-tech", "full-spec", "implement")] + \
           [f"claude/agents/{a}.md" for a in ("reviewer", "recetteur", "harry-archi")] + \
           [f"claude/skills/{s}/SKILL.md" for s in ("recette", "recette-ui")]


def test_the_rule_is_in_the_persona():
    section = re.search(rf"^## {RULE_TITLE}.*?(?=^## )", PERSONA.read_text(encoding="utf-8"), re.M | re.S)
    assert section, "the rule is missing from the persona"
    body = section.group(0)
    for key in ("Lire la maquette", "pas une inspiration", "se signale", "remonte à l'humain"):
        assert key in body, key


@pytest.mark.parametrize("rel", CARRIERS)
def test_every_carrier_points_to_the_rule(rel):
    assert POINTER in (REPO / rel).read_text(encoding="utf-8")


def test_the_rule_is_written_once():
    """The body lives only in the persona; the title appears only there and in the carriers — expressed on the
    list, never on a literal count, which would be debt as soon as a prompt is added."""
    holders = {str(p.relative_to(REPO)) for p in (REPO / "claude").rglob("*.md")
               if RULE_TITLE in p.read_text(encoding="utf-8")}
    assert holders == {"claude/sdlc/harry.md", *CARRIERS}
    bodies = [p for p in (REPO / "claude").rglob("*.md") if "pas une inspiration" in p.read_text(encoding="utf-8")]
    assert bodies == [PERSONA]


def test_the_recetteur_carries_the_comparison_in_its_three_exit_statements():
    """Amending one statement would leave the two others silent — the very defect the rule closes."""
    text = (REPO / "claude" / "agents" / "recetteur.md").read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if "pass=true" in l]
    assert len(lines) == 3, f"an exit statement was added or removed: {len(lines)}"
    body = "\n".join(text.splitlines())
    for anchor in ("sans verdict de comparaison", "comparaison à la maquette est **verte",
                   "verdict de comparaison consigné"):
        assert anchor in body, anchor


def test_the_reviewer_controls_the_table():
    text = (REPO / "claude" / "agents" / "reviewer.md").read_text(encoding="utf-8")
    assert maquette.SECTION in text and "non déclarée" in text
    assert text.index("Fidélité à la maquette") < text.index("## Sortie")


def test_both_recette_skills_make_the_step_mandatory():
    for rel in ("claude/skills/recette/SKILL.md", "claude/skills/recette-ui/SKILL.md"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "obligatoire" in text and "maquette" in text
        assert "pass: false" in text, rel


def test_harry_archi_escalates_a_human_validated_deviation():
    text = HARRY_ARCHI.read_text(encoding="utf-8")
    section = re.search(r"^## Hors de ton périmètre de décision.*?(?=^## )", text, re.M | re.S)
    assert section and "escalate: true" in section.group(0)
    assert "ne se tranche pas par délégation" in section.group(0)


def test_the_implementer_treats_the_table_like_an_invariant():
    text = (REPO / "claude" / "commands" / "implement.md").read_text(encoding="utf-8")
    assert "attendus à l'écran" in text and "avant de coder" in text


# Uppercase tokens that look like a ticket but are not: acronyms the documentation legitimately uses.
ALLOWED_UPPERCASE: set[str] = set()


def test_what_this_epic_adds_carries_no_ticket_identifier():
    """Scoped to the added text on purpose: the persona already cites older ticket ids, which is pre-existing
    debt and not this epic's to rewrite."""
    section = re.search(rf"^## {RULE_TITLE}.*?(?=^## )", PERSONA.read_text(encoding="utf-8"), re.M | re.S).group(0)
    added = [section, POINTER]
    for rel in ("claude/skills/recette-ui/SKILL.md", "claude/agents/harry-archi.md"):
        text = (REPO / rel).read_text(encoding="utf-8")
        added.append(text.split("Comparaison à la maquette", 1)[-1].split("\n## ", 1)[0])
    # Deny the SHAPE of a ticket identifier rather than a list of project names: a denylist of real
    # names would have to name them, and it would miss the next project anyway.
    ticket = re.compile(r"\b[A-Z][A-Z0-9]{2,}-[A-Z0-9]+(?:-\d+)?\b")
    for blob in added:
        found = [m for m in ticket.findall(blob) if m not in ALLOWED_UPPERCASE]
        assert not found, found
