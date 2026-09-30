"""AISDLC-POASSIST-14 (PRD D27) — at the feature gate each role verdict decides only its findings.

Fixture = the documents of live run #4 (FEAT-59643d4e743f): a review with a `Rôle` column, a PO verdict
deciding M3/m1/m2/S1 and a tech-lead verdict deciding the rest. The platform test suite replays the SAME
files (platform/tests/fixtures/gates/roles-run4/) so both sides give the same readiness.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sdlc import gates

FIXTURES = Path(__file__).parent / "fixtures" / "gate_roles"


def _signed(text: str) -> str:
    text = re.sub(r"^status:.*$", "status: signed", text, count=1, flags=re.M)
    text = re.sub(r"^outcome:.*$", "outcome: validated_with_reserves", text, count=1, flags=re.M)
    text = re.sub(r"^signed_by:.*$", "signed_by: Anis", text, count=1, flags=re.M)
    return re.sub(r"^signed_at:.*$", "signed_at: 2026-09-30T14:00:00+00:00", text, count=1, flags=re.M)


def _check(tmp_path: Path, verdict_text: str, review_text: str | None = None, role_file: str = "po"):
    (tmp_path / "review-feature.md").write_text(
        review_text if review_text is not None else (FIXTURES / "review-feature.md").read_text("utf-8"), "utf-8")
    name = f"review-feature-verdict-{role_file}.md"
    (tmp_path / name).write_text(_signed(verdict_text), "utf-8")
    return gates.check_verdict(tmp_path, name, "feature", "FEAT-59643d4e743f", review="review-feature.md")


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text("utf-8")


def _strip_role_column(review: str) -> str:
    out = []
    for line in review.splitlines():
        cells = line.split("|")
        if line.startswith("|") and len(cells) > 3:
            del cells[2]
        out.append("|".join(cells))
    return "\n".join(out)


@pytest.mark.parametrize("cell,expected", [
    ("[po]", ("po",)), ("techlead", ("techlead",)), ("Tech lead", ("techlead",)), ("TL", ("techlead",)),
    ("[po+techlead]", ("po", "techlead")), ("les deux", ("po", "techlead")), ("both", ("po", "techlead")),
    ("PO, TL", ("po", "techlead")), ("", ("po", "techlead")), ("???", ("po", "techlead")),
])
def test_parse_roles(cell, expected):
    assert gates.parse_roles(cell) == expected


def test_review_roles_read_by_header_run4():
    roles = gates.review_roles(_fixture("review-feature.md"))
    assert roles["M1"] == ("techlead",) and roles["m1"] == ("po",)
    assert roles["M3"] == ("po", "techlead") and roles["S1"] == ("po", "techlead")
    assert sorted(gates.findings_for_role(_fixture("review-feature.md"), "po")) == ["M3", "S1", "m1", "m2"]


def test_role_column_found_by_header_whatever_its_position():
    review = "---\nversion: 1\n---\n| # | Gravité | Constat | Pour |\n|---|---|---|---|\n| M1 | majeur | x | TL |\n"
    assert gates.review_roles(review) == {"M1": ("techlead",)}


def test_run4_po_verdict_is_ready(tmp_path):
    v = _check(tmp_path, _fixture("review-feature-verdict-po.md"))
    assert sorted(v.decisions) == ["M3", "S1", "m1", "m2"]


def test_run4_techlead_verdict_is_ready(tmp_path):
    v = _check(tmp_path, _fixture("review-feature-verdict-techlead.md"), role_file="techlead")
    assert sorted(v.decisions) == ["M1", "M2", "M3", "S1", "S2", "m3", "m4"]


def test_a_role_verdict_missing_one_of_its_findings_is_refused_naming_the_role(tmp_path):
    text = "\n".join(line for line in _fixture("review-feature-verdict-po.md").splitlines()
                     if not line.startswith("| m1 "))
    with pytest.raises(gates.GateRefused) as exc:
        _check(tmp_path, text)
    assert exc.value.code == "undecided" and "m1" in str(exc.value) and "role po" in str(exc.value)


def test_a_decision_on_another_roles_finding_is_ignored(tmp_path):
    text = _fixture("review-feature-verdict-po.md").replace(
        "| S1 | reserve", "| M1 | discuss | — | — |\n| S1 | reserve")
    v = _check(tmp_path, text)
    assert "M1" not in v.decisions


def test_review_without_role_column_keeps_both_roles_deciding_everything(tmp_path):
    review = _strip_role_column(_fixture("review-feature.md"))
    assert "Rôle" not in review
    with pytest.raises(gates.GateRefused) as exc:
        _check(tmp_path, _fixture("review-feature-verdict-po.md"), review)
    assert exc.value.code == "undecided" and "M1" in str(exc.value)


def test_verdict_decisions_read_by_header():
    text = ("## Décisions\n| # | Suite | Motif | Décision |\n|---|---|---|---|\n"
            "| M1 | later | because | rejeté |\n")
    assert gates.verdict_decisions(text) == {"M1": ("rejected", "because")}
