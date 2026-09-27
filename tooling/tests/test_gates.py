"""Spec and feature gates (AISDLC-POASSIST-2): the CLI records a gate only on a verdict signed by a human.

Fixture F: epic E with stories E-1, E-2, review E/review-spec-func.md (findings B1, M1, m1, S1) and its verdict.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sdlc import cli, gates
from sdlc.post_mortem import PostMortemStore

REPO = Path(__file__).resolve().parents[2]

REVIEW = """---
kind: review
gate: {gate}
target: {target}
version: 1
reviewer: harry-archi
date: 2026-09-27
---
# {target} — revue

## Synthèse

Recommandation : validate_with_reserves.

## Constats

| # | Gravité | Constat | Preuve | Recommandation | Consensus |
|---|---|---|---|---|---|
| B1 | bloquant | AC3 not testable | spec-func.md §AC3 | rewrite AC3 | 0.9 |
| M1 | majeur | no error message | cli.py:42 | add one | 0.7 |
| m1 | mineur | typo | spec-func.md §1 | fix | 0.95 |
| S1 | suggestion | rename | spec-tech.md §2 | rename | 0.4 |
"""

DECISIONS = {"B1": ("applied", ""), "M1": ("reserve", "acceptable for V1"),
             "m1": ("bypassed", "out of scope"), "S1": ("rejected", "naming is fine")}


def verdict_text(gate="spec_func", target="E", status="signed", outcome="validated_with_reserves",
                 signed_by="Anis", review="E/review-spec-func.md", role=None, decisions=None,
                 review_version="1", extra_rows="") -> str:
    fm = [f"kind: verdict", f"gate: {gate}", f"target: {target}", f"review: {review}",
          f"review_version: {review_version}", f"status: {status}", f"outcome: {outcome}",
          f"signed_by: {signed_by}", "signed_at: 2026-09-27T21:05Z"]
    if role:
        fm.append(f"role: {role}")
    rows = "\n".join(f"| {i} | {d} | {why} | |" for i, (d, why) in (decisions or DECISIONS).items())
    return ("---\n" + "\n".join(fm) + "\n---\n# verdict\n\n## Décisions\n\n| # | Décision | Motif | Suite |\n"
            "|---|---|---|---|\n" + rows + extra_rows + "\n")


def sdlc_run(ws: Path, *argv: str, monkeypatch, capsys) -> tuple[int, dict, str]:
    monkeypatch.setenv("SDLC_WORKSPACE", str(ws))
    rc = cli.main(list(argv))
    cap = capsys.readouterr()
    out = json.loads(cap.out) if cap.out.strip() else {}
    return rc, out, cap.err


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    def _run(*argv, ws: Path | None = None):
        return sdlc_run(ws or tmp_path, *argv, monkeypatch=monkeypatch, capsys=capsys)
    return _run


def make_f(ws: Path, run, status="spec_func", gate="spec_func", review_target="E") -> Path:
    run("create-epic", "E", "Demo", ws=ws)
    for sid in ("E-1", "E-2"):
        run("create-ticket", "E", sid, "story", ws=ws)
        path = {"spec_func": ["spec_func"], "spec_tech": ["spec_tech"],
                "spec_validated": ["spec_tech", "spec_validated"]}[status]
        for st in path:
            rc, _, err = run("set-status", sid, st, ws=ws)
            assert rc == 0, err
    name = gates.GATES[gate].review_file
    (ws / "E" / name).write_text(REVIEW.format(gate=gate, target=review_target))
    return ws


def snapshot(ws: Path) -> dict[str, bytes]:
    return {str(p.relative_to(ws)): p.read_bytes() for p in sorted(ws.rglob("*")) if p.is_file()}


def status_of(run, sid, ws) -> str:
    return run("get", sid, ws=ws)[1]["status"]


# --- parsing units ---------------------------------------------------------------------------------------------

def test_front_matter_parsing():
    assert gates.front_matter("---\na: 1\nb: 'x y'\n---\nbody") == {"a": "1", "b": "x y"}
    assert gates.front_matter("no front matter") == {}
    assert gates.front_matter("---\na: 1\n") == {}          # unterminated


def test_review_findings_and_verdict_decisions():
    assert gates.review_findings(REVIEW.format(gate="spec_func", target="E")) == \
        {"B1": "B", "M1": "M", "m1": "m", "S1": "S"}
    text = verdict_text(extra_rows="\n| H1 | Réserve | added by the PO | |")
    d = gates.verdict_decisions(text)
    assert d["M1"] == ("reserve", "acceptable for V1") and d["H1"] == ("reserve", "added by the PO")
    # rows outside `## Décisions` are ignored (e.g. a human additions table)
    assert gates.verdict_decisions("## Ajouts\n| H2 | majeur | x |\n") == {}


def test_blob_ref_equals_git_hash_object(tmp_path):
    p = tmp_path / "f.md"
    p.write_text("héllo\n")
    git = subprocess.run(["git", "hash-object", str(p)], capture_output=True, text=True, check=True).stdout
    assert gates.blob_ref(p) == git.strip()[:12]


def test_every_engine_agent_is_an_agent_identity():
    agents = [p.stem for p in (REPO / "claude" / "agents").glob("*.md")]
    assert agents
    for name in agents + ["harry", "Harry-Archi", "claude", "Claude Code", ""]:
        assert gates.is_agent_identity(name), name
    assert not gates.is_agent_identity("Anis Bessa")


# --- AC1: names and aliases ------------------------------------------------------------------------------------

def test_ac1_alias_and_canonical_are_the_same(tmp_path, run):
    outs = []
    for cmd in ("validate-func", "validate-spec-func"):
        ws = make_f(tmp_path / cmd, run)
        (ws / "E" / "review-spec-func-verdict.md").write_text(verdict_text())
        rc, out, err = run(cmd, "E", "--verdict", "E/review-spec-func-verdict.md", ws=ws)
        assert rc == 0, err
        outs.append(out)
    assert outs[0] == outs[1]
    assert outs[0]["gate"] == "spec_func" and outs[0]["advanced"] == ["E-1", "E-2"]


def test_ac1_help_lists_canonical_names_and_aliases():
    help_text = subprocess.run([shutil.which("python3") or "python3", "-m", "sdlc.cli", "-h"],
                               cwd=REPO / "tooling", capture_output=True, text=True).stdout
    for name in ("validate-spec-func (validate-func)", "validate-spec-tech (validate-spec, validate-tech)",
                 "validate-feature (validate-epic)"):
        assert name in help_text, name


def test_ac1_ambiguous_prefix_is_refused(tmp_path, run):
    make_f(tmp_path, run)
    rc, _, err = run("validate-f", "E")
    assert rc == 1 and "validate-feature" in err and "validate-func" in err


# --- AC2: refusals, nothing written ----------------------------------------------------------------------------

@pytest.mark.parametrize("case,expected", [
    ("no_verdict", "--verdict"),
    ("draft", "draft"),
    ("agent", "human"),
    ("missing_file", "not found"),
    ("undecided", "M1"),
    ("discuss", "B1"),
    ("wrong_gate", "gate"),
    ("wrong_target", "target"),
    ("no_reason", "S1"),
    ("stale_review_version", "version"),
])
def test_ac2_refused_without_any_write(tmp_path, run, case, expected):
    ws = make_f(tmp_path, run)
    vpath = ws / "E" / "review-spec-func-verdict.md"
    decisions = dict(DECISIONS)
    kwargs = {}
    if case == "draft":
        kwargs["status"] = "draft"
    elif case == "agent":
        kwargs["signed_by"] = "harry-archi"
    elif case == "undecided":
        decisions.pop("M1")
    elif case == "discuss":
        decisions["B1"] = ("discuss", "")
    elif case == "wrong_gate":
        kwargs["gate"] = "spec_tech"
    elif case == "wrong_target":
        kwargs["target"] = "E-1"
    elif case == "no_reason":
        decisions["S1"] = ("rejected", "")
    elif case == "stale_review_version":
        kwargs["review_version"] = "0"
    if case != "missing_file":
        vpath.write_text(verdict_text(decisions=decisions, **kwargs))
    before = snapshot(ws)
    argv = ["validate-spec-func", "E"] + ([] if case == "no_verdict" else ["--verdict", str(vpath.relative_to(ws))])
    rc, out, err = run(*argv)
    assert rc == 1 and out == {}
    assert expected in json.loads(err)["error"], err
    assert snapshot(ws) == before
    assert status_of(run, "E-1", ws) == "spec_func"
    assert not (ws / "E" / "stories" / "E-1" / "journal.md").exists()


def test_ac2_argparse_does_not_hide_the_message(tmp_path, run):
    make_f(tmp_path, run)
    rc, _, err = run("validate-func", "E")          # old name, no verdict
    assert rc == 1 and "signed by a human" in json.loads(err)["error"]


# --- AC3 / AC4: transition, journal, links, debt ---------------------------------------------------------------

def test_ac3_ac4_signed_verdict_records_everything(tmp_path, run):
    ws = make_f(tmp_path, run)
    vrel = "E/review-spec-func-verdict.md"
    (ws / vrel).write_text(verdict_text())
    rc, out, err = run("validate-spec-func", "E", "--verdict", vrel)
    assert rc == 0, err
    assert out["advanced"] == ["E-1", "E-2"] and out["outcome"] == "validated_with_reserves"
    assert out["signedBy"] == ["Anis"] and len(out["debt"]) == 2
    for sid in ("E-1", "E-2"):
        t = run("get", sid)[1]
        assert t["status"] == "spec_func_validated"
        assert t["artifacts"]["review_spec_func"] == "E/review-spec-func.md"
        assert t["artifacts"]["review_spec_func_verdict"] == vrel
        journal = (ws / "E" / "stories" / sid / "journal.md").read_text()
        entry = journal.split("\n## ")[1]
        assert "spec_func -> spec_func_validated" in entry and "validated_with_reserves" in entry
        assert "Anis" in entry.splitlines()[0]
        assert f"review-spec-func.md@{gates.blob_ref(ws / 'E/review-spec-func.md')}" in entry
        assert f"review-spec-func-verdict.md@{gates.blob_ref(ws / vrel)} (signed" in entry
    items = PostMortemStore(ws).list(kind="debt")
    assert [(i.text.split("]")[0] + "]", i.severity, i.agent, i.epic, i.status) for i in items] == [
        ("[spec_func E M1]", "medium", "human", "E", "open"),
        ("[spec_func E m1]", "low", "human", "E", "open"),
    ]


def test_ac4_debt_is_idempotent(tmp_path, run):
    ws = make_f(tmp_path, run)
    vrel = "E/review-spec-func-verdict.md"
    (ws / vrel).write_text(verdict_text())
    assert run("validate-spec-func", "E", "--verdict", vrel)[0] == 0
    # put the stories back in spec_func through the raw state tool, then replay the same command
    for sid in ("E-1", "E-2"):
        p = ws / "E" / "stories" / sid / "status.json"
        data = json.loads(p.read_text())
        data["status"] = "spec_func"
        p.write_text(json.dumps(data))
    rc, out, err = run("validate-spec-func", "E", "--verdict", vrel)
    assert rc == 0, err
    assert len(PostMortemStore(ws).list(kind="debt")) == 2
    assert len(out["debt"]) == 2


# --- AC5: returned ---------------------------------------------------------------------------------------------

def test_ac5_returned_records_without_transition(tmp_path, run):
    ws = make_f(tmp_path, run)
    vrel = "E/review-spec-func-verdict.md"
    (ws / vrel).write_text(verdict_text(outcome="returned"))
    rc, out, err = run("validate-spec-func", "E", "--verdict", vrel)
    assert rc == 0, err
    assert out["advanced"] == [] and out["outcome"] == "returned" and out["recorded"] == ["E-1", "E-2"]
    assert status_of(run, "E-1", ws) == "spec_func"
    assert "returned" in (ws / "E" / "stories" / "E-1" / "journal.md").read_text()
    assert run("get", "E-1")[1]["artifacts"]["review_spec_func_verdict"] == vrel


# --- AC6: technical gate on a story ----------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["validate-spec-tech", "validate-spec", "validate-tech"])
def test_ac6_story_target(tmp_path, run, cmd):
    ws = make_f(tmp_path, run, status="spec_tech", gate="spec_tech", review_target="E-1")
    sd = ws / "E" / "stories" / "E-1"
    (ws / "E" / "review-spec-tech.md").rename(sd / "review-spec-tech.md")
    rrel = "E/stories/E-1/review-spec-tech.md"
    vrel = "E/stories/E-1/review-spec-tech-verdict.md"
    (ws / vrel).write_text(verdict_text(gate="spec_tech", target="E-1", review=rrel, outcome="validated"))
    rc, out, err = run(cmd, "E-1", "--verdict", vrel)
    assert rc == 0, err
    assert out["advanced"] == ["E-1"]
    assert status_of(run, "E-1", ws) == "spec_validated" and status_of(run, "E-2", ws) == "spec_tech"
    debt = PostMortemStore(ws).list(kind="debt")
    assert {i.story for i in debt} == {"E-1"}


def test_ac6_verdict_for_the_epic_refused_on_a_story(tmp_path, run):
    ws = make_f(tmp_path, run, status="spec_tech", gate="spec_tech")
    vrel = "E/review-spec-tech-verdict.md"
    (ws / vrel).write_text(verdict_text(gate="spec_tech", target="E", review="E/review-spec-tech.md"))
    rc, _, err = run("validate-spec-tech", "E-1", "--verdict", vrel)
    assert rc == 1 and "target" in json.loads(err)["error"]


def test_story_not_in_source_state_is_refused(tmp_path, run):
    ws = make_f(tmp_path, run)
    vrel = "E/stories/E-1/review-spec-tech-verdict.md"
    (ws / vrel).write_text(verdict_text(gate="spec_tech", target="E-1"))
    rc, _, err = run("validate-spec-tech", "E-1", "--verdict", vrel)
    assert rc == 1 and "spec_func" in json.loads(err)["error"]


# --- AC7: feature gate -----------------------------------------------------------------------------------------

def _feature(ws, role, outcome="validated"):
    vrel = f"E/review-feature-verdict-{role}.md"
    (ws / vrel).write_text(verdict_text(gate="feature", target="E", review="E/review-feature.md", role=role,
                                        outcome=outcome, signed_by="Anis" if role == "po" else "Tech Lead"))
    return vrel


def test_ac7_two_roles_then_transition(tmp_path, run):
    ws = make_f(tmp_path, run, status="spec_validated", gate="feature")
    rc, out, err = run("validate-feature", "E", "--verdict", _feature(ws, "po"))
    assert rc == 0, err
    assert out["advanced"] == [] and out["waiting"] == ["techlead"]
    assert run("get", "E-1")[1]["artifacts"]["review_feature_verdict_po"] == "E/review-feature-verdict-po.md"
    assert status_of(run, "E-1", ws) == "spec_validated"
    rc, out, err = run("validate-epic", "E", "--verdict", _feature(ws, "techlead"))
    assert rc == 0, err
    assert out["advanced"] == ["E-1", "E-2"] and out["waiting"] == []
    assert set(out["verdicts"]) == {"po", "techlead"}
    assert status_of(run, "E-2", ws) == "feature_validated"
    assert run("set-status", "E-1", "implemented")[0] == 0


def test_ac7_both_roles_at_once_and_duplicate_role(tmp_path, run):
    ws = make_f(tmp_path, run, status="spec_validated", gate="feature")
    po = _feature(ws, "po")
    rc, _, err = run("validate-feature", "E", "--verdict", po, "--verdict", po)
    assert rc == 1 and "same role" in json.loads(err)["error"]
    rc, out, err = run("validate-feature", "E", "--verdict", po, "--verdict", _feature(ws, "techlead"))
    assert rc == 0 and out["advanced"] == ["E-1", "E-2"], err


def test_ac7_returned_role_blocks_the_transition(tmp_path, run):
    ws = make_f(tmp_path, run, status="spec_validated", gate="feature")
    rc, out, _ = run("validate-feature", "E", "--verdict", _feature(ws, "po"),
                     "--verdict", _feature(ws, "techlead", outcome="returned"))
    assert rc == 0 and out["advanced"] == [] and out["outcome"] == "returned"


def test_ac7_earlier_verdict_turned_draft_counts_as_missing(tmp_path, run):
    ws = make_f(tmp_path, run, status="spec_validated", gate="feature")
    po = _feature(ws, "po")
    assert run("validate-feature", "E", "--verdict", po)[0] == 0
    (ws / po).write_text((ws / po).read_text().replace("status: signed", "status: draft"))
    rc, out, _ = run("validate-feature", "E", "--verdict", _feature(ws, "techlead"))
    assert rc == 0 and out["waiting"] == ["po"] and out["advanced"] == []


def test_ac7_lagging_story_refused_and_superseded_ignored(tmp_path, run):
    ws = make_f(tmp_path, run, status="spec_validated", gate="feature")
    run("create-ticket", "E", "E-3", "late")
    run("set-status", "E-3", "spec_tech")
    rc, _, err = run("validate-feature", "E", "--verdict", _feature(ws, "po"))
    assert rc == 1 and "E-3 (spec_tech)" in json.loads(err)["error"]
    p = ws / "E" / "stories" / "E-3" / "status.json"
    data = json.loads(p.read_text())
    data["supersededBy"] = "E-2"
    p.write_text(json.dumps(data))
    rc, out, err = run("validate-feature", "E", "--verdict", _feature(ws, "po"))
    assert rc == 0 and out["recorded"] == ["E-1", "E-2"], err


def test_ac7_feature_gate_targets_an_epic(tmp_path, run):
    ws = make_f(tmp_path, run, status="spec_validated", gate="feature")
    rc, _, err = run("validate-feature", "E-1", "--verdict", _feature(ws, "po"))
    assert rc == 1 and "epic" in json.loads(err)["error"]


def test_ac7_role_is_required(tmp_path, run):
    ws = make_f(tmp_path, run, status="spec_validated", gate="feature")
    vrel = "E/review-feature-verdict.md"
    (ws / vrel).write_text(verdict_text(gate="feature", target="E", review="E/review-feature.md"))
    rc, _, err = run("validate-feature", "E", "--verdict", vrel)
    assert rc == 1 and "role" in json.loads(err)["error"]


# --- AC10: status hints ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("status,command", [("spec_func", "validate-spec-func"),
                                            ("spec_tech", "validate-spec-tech"),
                                            ("spec_validated", "validate-feature")])
def test_ac10_status_awaiting_names_the_gate(tmp_path, run, status, command):
    make_f(tmp_path, run, status=status)
    rc, out, _ = run("status", "E-1")
    assert rc == 0 and command in out["tickets"][0]["awaiting"]
