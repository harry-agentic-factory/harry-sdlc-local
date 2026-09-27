"""Gate prompts (AISDLC-POASSIST-2 AC8 form, AC9 content, invariant I2)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COMMANDS = REPO / "claude" / "commands"
NEW = ("validate-spec-func", "validate-spec-tech", "validate-feature", "process-review")


@pytest.mark.parametrize("name", NEW)
def test_new_command_has_the_engine_command_form(name):
    text = (COMMANDS / f"{name}.md").read_text()
    first = text.splitlines()[0]
    assert first.endswith(": $ARGUMENTS") and not first.startswith("---")


def test_process_review_describes_the_progressive_queue():
    text = (COMMANDS / "process-review.md").read_text()
    order = [text.index(k) for k in ("Lot des évidences", "Bloquants, un par un", "Majeurs", "Le reste")]
    assert order == sorted(order)
    for decision in ("`applied`", "`other`", "`reserve`", "`rejected`", "`bypassed`", "`discuss`"):
        assert decision in text, decision
    for word in ("reprise", "status: draft", "status: signed", "review_version", "Signatures précédentes",
                 "H<n>", "Tu ne signes jamais", "validate-spec-func", "--verdict"):
        assert word in text, word


@pytest.mark.parametrize("name,gate,review", [
    ("validate-spec-func", "validate-spec-func", "review-spec-func.md"),
    ("validate-spec-tech", "validate-spec-tech", "review-spec-tech.md"),
    ("validate-feature", "validate-feature", "review-feature.md"),
])
def test_gate_commands_name_their_documents_and_the_cli(name, gate, review):
    text = (COMMANDS / f"{name}.md").read_text()
    stem = review.removesuffix(".md")
    assert review in text and f"{stem}-verdict" in text
    assert f"sdlc --project <PREFIX> {gate} " in text and "--verdict" in text
    assert "/process-review" in text and "harry-archi" in text and "Tu ne signes jamais" in text


def test_harry_archi_has_the_review_document_mode():
    text = (REPO / "claude" / "agents" / "harry-archi.md").read_text()
    sec = re.search(r"^## Mode document de revue.*?(?=^## )", text, re.M | re.S).group(0)
    for word in ("`B<n>`", "`M<n>`", "`m<n>`", "`S<n>`", "preuve obligatoire", "consensus", "Revue ciblée",
                 "version", "jamais réutilisé", "| # | Gravité | Constat | Preuve | Recommandation | Consensus |"):
        assert word in sec, word


def test_only_gate_prompts_mention_a_signed_status_and_forbid_signing():
    """I2: files of claude/ that contain `status: signed` are process-review and the validate-* commands, and each
    tells the agent it never signs."""
    hits = sorted(str(p.relative_to(REPO)) for p in (REPO / "claude").rglob("*.md")
                  if "status: signed" in p.read_text())
    allowed = {f"claude/commands/{n}.md" for n in NEW}
    assert hits and set(hits) <= allowed, hits
    for h in hits:
        assert "Tu ne signes jamais" in (REPO / h).read_text(), h


OLD = re.compile(r"validate-(func|tech|epic)\b|validate-spec(?=[\s`])")


def test_old_gate_names_only_appear_as_aliases():
    """AC9: each line of claude/, docs/ and README.md naming an old gate command also says `alias`."""
    files = list((REPO / "claude").rglob("*.md")) + list((REPO / "docs").rglob("*.md")) + [REPO / "README.md"]
    offending = [f"{p.relative_to(REPO)}:{i}" for p in files
                 for i, line in enumerate(p.read_text().splitlines(), 1)
                 if OLD.search(line) and "alias" not in line]
    assert offending == []


def test_run_story_starts_unattended_at_feature_validated():
    text = (COMMANDS / "run-story.md").read_text()
    assert "À partir de `feature_validated`" in text
    assert "| `feature_validated` | `/implement`" in text
    assert "| `spec_validated` | **GATE FEATURE**" in text
