"""Rule « Écrire un document vivant » (AISDLC-RUNWS-13): written once in the persona, pointed to by every
writer of a living document (AC15), reminded to the off-mode prompts of `run-ticket.js`, and a `conflict`
returned by a role stops the workflow with `doc_conflict` (AC14).
Skipped when `node` is absent, unless SDLC_REQUIRE_NODE=1 (then it fails).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
JS = HERE / "js"
REPO = HERE.parent.parent
SCRIPT = REPO / "claude" / "workflows" / "run-ticket.js"
PERSONA = REPO / "claude" / "sdlc" / "harry.md"
TITLE = "Écrire un document vivant"
POINTER = ("> **Avant d'écrire un document vivant** du dépôt data : règle « Écrire un document vivant » de la "
           "persona (`~/.claude/sdlc/harry.md`).")
WRITERS = [f"claude/commands/{c}.md" for c in
           ("scope", "refine", "spec-func", "spec-tech", "full-spec", "implement", "post-mortem", "investigate",
            "process-review")] + \
          [f"claude/agents/{a}.md" for a in
           ("reviewer", "recetteur", "deployer", "demo", "fixer", "harry-archi", "nonreg-runner")]
OFF_PROMPTS = ("reviewPrompt", "deployPrompt", "promotePrompt", "recettePrompt", "fixPrompt")
RW_PROMPTS = ("reviewPromptRW", "deployPromptRW", "recettePromptRW", "fixPromptRW", "promotePromptRW")
OFF_ROLE_LABELS = ("review:", "deploy:", "redeploy:", "recette:", "recette-main:", "fix:", "promote:")
NODE = shutil.which("node")


def node_or_skip() -> str:
    if NODE is None:
        if os.environ.get("SDLC_REQUIRE_NODE") == "1":
            raise RuntimeError("node is required (SDLC_REQUIRE_NODE=1) but was not found")
        pytest.skip("node is not installed")
    return NODE


def harness(scenario: Path) -> dict:
    argv = [node_or_skip(), str(JS / "run_ticket_harness.mjs"), "--script", str(SCRIPT), "--scenario", str(scenario)]
    p = subprocess.run(argv, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def template(src: str, name: str) -> str:
    """Body of `const <name> = (...) => `...`` in run-ticket.js."""
    m = re.search(rf"^const {name} = \([^)]*\) => `(.*?)(?<!\\)`\n", src, re.M | re.S)
    assert m, name
    return m.group(1)


# --- AC15: the rule, once, and its pointers ---

def test_persona_has_the_rule_once():
    text = PERSONA.read_text()
    assert text.count(f"## {TITLE}\n") == 1
    sec = re.search(rf"^## {TITLE}\n(.*?)(?=^## |\Z)", text, re.M | re.S).group(1)
    for word in ("git hash-object", "Edit/Write", "session principale", "modified since read", "sed -i", "tee",
                 "sdlc journal", "doc <type> refait sur", "Session interactive", "Sous-agent"):
        assert word in sec, word
    for step in ("1. **Lire**", "2. **Juste avant d'écrire**", "3. **Conflit**"):
        assert step in sec, step
    block = re.search(r"```json\n(.*?)```", sec, re.S).group(1)
    keys = json.loads(block.replace("<", "").replace(">", ""))["conflict"].keys()
    assert list(keys) == ["doc", "base", "latest", "intermediate", "divergent", "intended"]


@pytest.mark.parametrize("path", WRITERS)
def test_writer_points_to_the_rule(path):
    text = (REPO / path).read_text()
    assert text.count(POINTER) == 1, path
    assert "git hash-object" not in text, path          # pointer only, never a copy of the rule


def test_sixteen_writers_and_no_copy_elsewhere():
    assert len(WRITERS) == 16
    pointing = sorted(str(p.relative_to(REPO)) for p in (REPO / "claude").rglob("*.md") if POINTER in p.read_text())
    assert pointing == sorted(WRITERS)
    copies = sorted(str(p.relative_to(REPO)) for p in (REPO / "claude").rglob("*")
                    if p.is_file() and "git hash-object" in p.read_text(errors="replace"))
    assert copies == ["claude/sdlc/harry.md", "claude/workflows/run-ticket.js"]


# --- AC15(3): run-ticket.js prompts ---

def test_rule_in_the_five_off_prompts_only():
    src = SCRIPT.read_text()
    for name in OFF_PROMPTS:
        assert template(src, name).endswith("\n${LIVING_DOC_RULE}"), name
    for name in RW_PROMPTS + ("prepPrompt", "prepareRW", "finishRW", "rwHead", "statusPrompt"):
        body = template(src, name)
        assert "LIVING_DOC_RULE" not in body and "hash-object" not in body, name
    assert src.count("${LIVING_DOC_RULE}") == len(OFF_PROMPTS)
    rule = re.search(r"^const LIVING_DOC_RULE = `(.*?)(?<!\\)`\n", src, re.M | re.S).group(1)
    for word in ("git hash-object", "Edit/Write", "set-status", "conflict: {doc, base, latest, intermediate, "
                 "divergent, intended}", "journal ${TICKET} --entry"):
        assert word in rule, word
    assert rule.count("\n") == 3                        # 4 lines


@pytest.mark.parametrize("name", ["happy", "review_human", "fix_loop", "promote", "fix_from"])
def test_off_goldens_role_prompts_end_with_the_rule(name):
    golden = json.loads((JS / "golden" / f"off_{name}.json").read_text())
    for c in golden["calls"]:
        has = "\n**Écrire un document vivant** (règle de la persona)" in c["prompt"]
        assert has == c["label"].startswith(OFF_ROLE_LABELS), c["label"]


def test_rw_role_prompts_carry_no_rule(tmp_path):
    sc = json.loads((JS / "scenarios" / "off_happy.json").read_text())
    sc["args"]["runWorkspace"] = True
    sc["args"]["review"] = "auto"
    sc["responses"] = {"review:": [{"conform": True}], "deploy:": [{"ok": True, "version": "v1"}],
                       "recette:": [{"pass": True}]}
    p = tmp_path / "rw.json"
    p.write_text(json.dumps(sc))
    out = harness(p)
    assert out["result"]["reason"] == "await_validation"
    assert all("hash-object" not in c["prompt"] and "document vivant" not in c["prompt"] for c in out["calls"])


# --- AC14: a `conflict` stops the workflow ---

def test_doc_conflict_matches_golden():
    argv = [node_or_skip(), str(JS / "run_ticket_harness.mjs"), "--script", str(SCRIPT), "--scenario",
            str(JS / "scenarios" / "off_doc_conflict.json")]
    p = subprocess.run(argv, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert p.stdout == (JS / "golden" / "off_doc_conflict.json").read_text()
    out = json.loads(p.stdout)
    sc = json.loads((JS / "scenarios" / "off_doc_conflict.json").read_text())
    assert out["result"] == {"stopped_at": "review", "reason": "needs_human", "detail": "doc_conflict",
                             "conflict": sc["responses"]["review:"][0]["conflict"], "status_now": "implemented"}
    assert [c["label"] for c in out["calls"]] == ["prepare:DEMO-E-1", "review:DEMO-E-1", "status:DEMO-E-1"]
    status = out["calls"][-1]
    assert status["agentType"] == "general-purpose" and status["phase"] == "Review"
    assert "`sdlc --project DEMO get DEMO-E-1`" in status["prompt"]
    assert not any("set-status" in c["prompt"] for c in out["calls"][2:])


def test_without_conflict_the_same_scenario_goes_on(tmp_path):
    sc = json.loads((JS / "scenarios" / "off_doc_conflict.json").read_text())
    del sc["responses"]["review:"][0]["conflict"]
    p = tmp_path / "noconflict.json"
    p.write_text(json.dumps(sc))
    out = harness(p)
    labels = [c["label"] for c in out["calls"]]
    assert "status:DEMO-E-1" not in labels and labels[:3] == ["prepare:DEMO-E-1", "review:DEMO-E-1", "deploy:DEMO-E-1"]


def test_agent_already_transitioned_still_stops(tmp_path):
    sc = json.loads((JS / "scenarios" / "off_doc_conflict.json").read_text())
    sc["responses"]["status:"] = [{"status": "reviewed"}]
    p = tmp_path / "transitioned.json"
    p.write_text(json.dumps(sc))
    out = harness(p)
    assert out["result"]["detail"] == "doc_conflict" and out["result"]["status_now"] == "reviewed"
    assert [c["label"] for c in out["calls"]][-1] == "status:DEMO-E-1"


@pytest.mark.parametrize("label,stop", [("deploy:", "deploy"), ("recette:", "recette"), ("fix:", "recette")])
def test_conflict_of_later_steps_stops_there(tmp_path, label, stop):
    sc = json.loads((JS / "scenarios" / "off_doc_conflict.json").read_text())
    conflict = sc["responses"]["review:"][0].pop("conflict")
    sc["responses"].update({"deploy:": [{"ok": True, "version": "v1"}], "recette:": [{"pass": False, "repro": "r"}],
                            "fix:": [{"fixed": True}], "redeploy:": [{"ok": True}]})
    first = sc["responses"][label][0]
    sc["responses"][label] = [{**first, "conflict": conflict}]
    p = tmp_path / "later.json"
    p.write_text(json.dumps(sc))
    out = harness(p)
    assert out["result"]["stopped_at"] == stop and out["result"]["detail"] == "doc_conflict"
    assert out["calls"][-1]["label"] == "status:DEMO-E-1"
    assert out["calls"][-2]["label"] == f"{label}DEMO-E-1"


def test_status_unreadable_gives_null(tmp_path):
    sc = json.loads((JS / "scenarios" / "off_doc_conflict.json").read_text())
    sc["responses"]["status:"] = [{"error": "boom"}]
    p = tmp_path / "err.json"
    p.write_text(json.dumps(sc))
    assert harness(p)["result"]["status_now"] is None
