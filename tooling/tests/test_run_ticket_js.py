"""`claude/workflows/run-ticket.js` through the stub harness (`js/run_ticket_harness.mjs`, no LLM).

Off mode (no `runWorkspace`): the journal of agent calls is byte-identical to the goldens captured from
the base of the story (AC16). Run workspace mode: Prepare/Finish around each role, prompts without any
data path (AC13, AC19), stops, and a real end-to-end run on the throwaway DEMO project (AC14, --exec).
Skipped when `node` is absent, unless SDLC_REQUIRE_NODE=1 (then it fails).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
JS = HERE / "js"
REPO = HERE.parent.parent
SCRIPT = REPO / "claude" / "workflows" / "run-ticket.js"
NODE = shutil.which("node")
if NODE is None:
    if os.environ.get("SDLC_REQUIRE_NODE") == "1":
        raise RuntimeError("node is required (SDLC_REQUIRE_NODE=1) but was not found")
    pytest.skip("node is not installed", allow_module_level=True)

ARGS = {"ticket": "DEMO-E-1", "epic": "DEMO-E", "prefix": "DEMO", "repoName": "app-repo",
        "sdlcRoot": "/data/demo", "repo": "/repos/app-repo", "review": "auto", "runWorkspace": True}
ROLE_LABELS = ("review:", "deploy:", "redeploy:", "recette:", "recette-main:", "fix:", "promote:")


def harness(tmp_path: Path, scenario: dict, *, exec_mode: bool = False, env: dict | None = None) -> dict:
    sc = tmp_path / f"scenario-{len(list(tmp_path.glob('scenario-*')))}.json"
    sc.write_text(json.dumps(scenario))
    argv = [NODE, str(JS / "run_ticket_harness.mjs"), "--script", str(SCRIPT), "--scenario", str(sc)]
    p = subprocess.run(argv + (["--exec"] if exec_mode else []), capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def labels(out: dict) -> list[str]:
    return [c["label"].rsplit(":DEMO-E-1", 1)[0] for c in out["calls"]]


def role_calls(out: dict) -> list[dict]:
    return [c for c in out["calls"] if c["label"].startswith(ROLE_LABELS)]


def step(out: dict, label: str, n: int = 0) -> dict:
    return [c for c in out["calls"] if c["label"] == f"{label}:DEMO-E-1"][n]


def assert_clean_role_prompts(out: dict) -> None:
    for c in role_calls(out):
        p = c["prompt"]
        assert "/data/demo" not in p and "/stories/" not in p and "set-status" not in p, c["label"]
        assert "--run " in p and "CODE=" in p, c["label"]


# --- AC16: off mode byte-identical to the base ---

@pytest.mark.parametrize("name", ["happy", "review_human", "fix_loop", "promote", "fix_from"])
def test_ac16_off_mode_matches_golden(name):
    argv = [NODE, str(JS / "run_ticket_harness.mjs"), "--script", str(SCRIPT), "--scenario",
            str(JS / "scenarios" / f"off_{name}.json")]
    p = subprocess.run(argv, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert p.stdout == (JS / "golden" / f"off_{name}.json").read_text()
    assert "runWorkspace" not in json.loads((JS / "scenarios" / f"off_{name}.json").read_text())["args"]


def test_off_mode_runworkspace_must_be_strict_true(tmp_path):
    sc = json.loads((JS / "scenarios" / "off_happy.json").read_text())
    sc["args"]["runWorkspace"] = "true"          # not the boolean: off mode
    out = harness(tmp_path, sc)
    assert out == json.loads((JS / "golden" / "off_happy.json").read_text())


# --- AC13: RW sequence, prompts without data paths ---

def fix_loop_rw() -> dict:
    return {"args": dict(ARGS), "responses": {
        "review:": [{"conform": True}], "deploy:": [{"ok": True, "version": "v1"}],
        "recette:": [{"pass": False, "repro": "run:forged-uid"}, {"pass": True}],
        "fix:": [{"fixed": True}], "redeploy:": [{"ok": True, "version": "v2"}]}}


def test_ac13_rw_sequence_and_prompts(tmp_path):
    out = harness(tmp_path, fix_loop_rw())
    assert labels(out) == [
        "prepare:reviewer", "review", "finish:reviewer", "prepare:deployer", "deploy", "finish:deployer",
        "prepare:recetteur", "recette", "finish:recetteur", "prepare:fixer", "fix", "finish:fixer",
        "prepare:deployer", "redeploy", "finish:deployer", "prepare:recetteur", "recette", "finish:recetteur"]
    assert out["result"]["reason"] == "await_validation"
    assert_clean_role_prompts(out)
    calls = out["calls"]
    for i, c in enumerate(calls):
        if c["label"].startswith(ROLE_LABELS):
            assert calls[i - 1]["label"].startswith("prepare:") and calls[i + 1]["label"].startswith("finish:")
            assert calls[i - 1]["phase"] == c["phase"] == calls[i + 1]["phase"]
            assert calls[i - 1]["agentType"] == calls[i + 1]["agentType"] == "general-purpose"
    assert "--status reviewed" in step(out, "finish:reviewer")["prompt"]
    assert "--status deployed" in step(out, "finish:deployer")["prompt"]
    assert "--status" not in step(out, "finish:recetteur", 0)["prompt"]
    assert "--status recette_ok" in step(out, "finish:recetteur", 1)["prompt"]
    assert "--status reviewed" in step(out, "finish:fixer")["prompt"]
    assert "--status deployed" in step(out, "finish:deployer", 1)["prompt"]
    prep = step(out, "prepare:reviewer")["prompt"]
    assert "`sdlc --project DEMO run init DEMO-E-1 --agent reviewer --branch feat/DEMO-E-1 --base main`" in prep
    assert [c["phase"] for c in calls if c["label"].startswith("prepare:")] == \
        ["Review", "Deploy", "Recette", "Recette", "Recette", "Recette"]
    assert "Prepare" not in [c["phase"] for c in calls]
    assert "git -C /runs/1/rw/code/app-repo diff main...HEAD" in step(out, "review")["prompt"]


def test_rw_fixer_repro_from_prepare_not_verdict(tmp_path):
    out = harness(tmp_path, fix_loop_rw())
    p = step(out, "prepare:fixer")["prompt"]
    assert "--status implemented --repro 20260101-000000-000003`" in p      # run of the tester's Prepare
    assert "forged-uid" not in p and "--repro-dir" not in p


def test_rw_prepare_failed_stops(tmp_path):
    sc = fix_loop_rw()
    sc["responses"]["prepare:deployer:"] = [{"error": "run_workspace_disabled:--branch"}]
    out = harness(tmp_path, sc)
    assert labels(out) == ["prepare:reviewer", "review", "finish:reviewer", "prepare:deployer"]
    assert out["result"] == {"stopped_at": "deploy", "reason": "needs_human", "detail": "prepare_failed",
                             "prepare": {"error": "run_workspace_disabled:--branch"}}


def test_rw_finish_rejected_stops(tmp_path):
    sc = fix_loop_rw()
    sc["responses"]["finish:reviewer:"] = [{"state": "rejected", "reasons": ["in_modified:repos/web-repo"]}]
    out = harness(tmp_path, sc)
    assert labels(out) == ["prepare:reviewer", "review", "finish:reviewer"]
    assert out["result"]["detail"] == "finish_rejected" and out["result"]["stopped_at"] == "review"
    assert out["result"]["reasons"] == ["in_modified:repos/web-repo"]
    sc["responses"]["finish:reviewer:"] = [{"run_uid": "x", "already": "published"}]
    assert harness(tmp_path, sc)["result"]["reason"] == "await_validation"


def test_rw_fix_not_fixed_stops(tmp_path):
    sc = fix_loop_rw()
    sc["responses"]["fix:"] = [{"fixed": False}]
    out = harness(tmp_path, sc)
    assert labels(out)[-3:] == ["prepare:fixer", "fix", "finish:fixer"]
    assert "--status" not in step(out, "finish:fixer")["prompt"]
    assert out["result"] == {"stopped_at": "recette", "reason": "needs_human", "detail": "fix_failed",
                             "fix": {"fixed": False}}


def test_rw_redeploy_failed_stops(tmp_path):
    sc = fix_loop_rw()
    sc["responses"]["redeploy:"] = [{"ok": False, "note": "down"}]
    out = harness(tmp_path, sc)
    assert labels(out)[-3:] == ["prepare:deployer", "redeploy", "finish:deployer"]
    assert "--status" not in step(out, "finish:deployer", 1)["prompt"]
    assert out["result"]["detail"] == "redeploy_failed"


def test_rw_review_non_conform_and_human_gate(tmp_path):
    sc = fix_loop_rw()
    sc["responses"]["review:"] = [{"conform": False, "violations": ["x"]}]
    out = harness(tmp_path, sc)
    assert labels(out) == ["prepare:reviewer", "review", "finish:reviewer"]
    assert "--status" not in step(out, "finish:reviewer")["prompt"] and out["result"]["reason"] == "needs_human"
    sc = fix_loop_rw()
    sc["args"]["review"] = "human"
    out = harness(tmp_path, sc)
    assert labels(out) == ["prepare:reviewer", "review", "finish:reviewer"]
    assert out["result"]["reason"] == "await_review"


# --- AC19: fixFrom and promote in RW ---

def test_ac19_fix_from_and_promote_rw(tmp_path):
    sc = fix_loop_rw()
    sc["args"]["fixFrom"] = "/scratch/repro-manual"
    out = harness(tmp_path, sc)
    assert labels(out)[:3] == ["prepare:fixer", "fix", "finish:fixer"]
    p = step(out, "prepare:fixer")["prompt"]
    assert "--status implemented --repro-dir /scratch/repro-manual`" in p and "--repro " not in p
    assert_clean_role_prompts(out)
    sc = {"args": dict(ARGS, promote=True), "responses": {
        "promote:": [{"ok": True, "version": "v3"}], "recette-main:": [{"pass": True}]}}
    out = harness(tmp_path, sc)
    assert labels(out) == ["prepare:promote", "promote", "finish:promote", "prepare:recette-main", "recette-main",
                           "finish:recette-main"]
    assert {c["phase"] for c in out["calls"]} == {"Promote"}
    assert "--status" not in step(out, "finish:promote")["prompt"]
    assert "--status" not in step(out, "finish:recette-main")["prompt"]
    assert "--agent deployer --phase promote --branch" in step(out, "prepare:promote")["prompt"]
    assert "--agent recetteur --phase recette-main --branch" in step(out, "prepare:recette-main")["prompt"]
    assert_clean_role_prompts(out)
    assert "remote get-url origin" in step(out, "promote")["prompt"]
    assert out["result"]["reason"] == "done"


# --- AC14: end to end on the throwaway DEMO project (--exec) ---

def test_ac14_end_to_end_exec(tmp_path, monkeypatch):
    from test_run_clone import make_code_demo
    cd = make_code_demo(tmp_path, monkeypatch)
    env = dict(os.environ)
    env["SDLC_CMD"] = f"{sys.executable} -m sdlc.cli"
    env["PYTHONPATH"] = str(REPO / "tooling") + os.pathsep + env.get("PYTHONPATH", "")
    sc = {"args": dict(ARGS, sdlcRoot=str(cd.data)), "responses": {
        "review:": [{"$reply": {"conform": True}, "$doc": "review"}],
        "deploy:": [{"$reply": {"ok": True, "version": "v1"}, "$doc": "deploy"}],
        "recette:": [{"$reply": {"pass": False, "repro": "run:{RUN_UID}"}, "$doc": "acceptance",
                      "$files": {"rw/out/sources/repro/steps.md": "# steps\n1. open the page\n"}},
                     {"$reply": {"pass": True}, "$doc": "acceptance"}],
        "fix:": [{"$reply": {"fixed": True, "commit": "stub"}, "$doc": "implement", "$commit": "fix: stub fixer"}],
        "redeploy:": [{"$reply": {"ok": True, "version": "v2"}, "$doc": "deploy"}]}}
    out = harness(tmp_path, sc, exec_mode=True, env=env)
    assert out["result"]["reason"] == "await_validation", json.dumps(out["calls"][-1], indent=1)
    fins = [c for c in out["calls"] if c["label"].startswith("finish:")]
    assert len(fins) == 6
    assert cd.status() == "recette_ok"
    story = cd.data / "DEMO-E" / "stories" / "DEMO-E-1"
    for doc, rounds in (("acceptance", 2), ("deploy", 2), ("review", 1), ("implement", 1)):
        text = (story / f"{doc}.md").read_text()
        assert len(re.findall(r"^<!-- round", text, re.M)) == rounds, doc
    log = subprocess.run(["git", "-C", str(cd.remote()), "log", "-1", "--format=%s", "feat/DEMO-E-1"],
                         capture_output=True, text=True).stdout.strip()
    assert log == "fix: stub fixer"
    lst = subprocess.run([sys.executable, "-m", "sdlc.cli", "--project", "DEMO", "run", "list", "DEMO-E-1"],
                         capture_output=True, text=True, env=env)
    rows = json.loads(lst.stdout)
    assert len(rows) == 6 and [r for r in rows if r["root"] is not None] == []
    fixer = [c for c in out["calls"] if c["label"] == "prepare:fixer:DEMO-E-1"][0]["prompt"]
    uid = re.search(r"--repro (\S+)`", fixer).group(1)
    assert (cd.data / "runs" / uid / "out" / "sources" / "repro" / "steps.md").is_file()
    for c in role_calls(out):
        assert str(cd.data) not in c["prompt"] and "/stories/" not in c["prompt"]


# --- agents and skills: section "Workspace de run" ---

AGENTS = ["reviewer", "recetteur", "deployer", "fixer", "demo", "e2e-author", "nonreg-runner"]
SKILLS = ["deploy-jenkins", "recette", "recette-ui"]


def _section(text: str) -> str | None:
    m = re.search(r"^## Workspace de run\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else None


@pytest.mark.parametrize("path", [f"claude/agents/{a}.md" for a in AGENTS] +
                         [f"claude/skills/{s}/SKILL.md" for s in SKILLS])
def test_agents_have_run_workspace_section(path):
    sec = _section((REPO / path).read_text())
    assert sec is not None, path
    assert "sdlc doc add" in sec and "stories/" not in sec and "rw/scratch/" in sec
    assert "IN" in sec and "OUT" in sec and "CODE" in sec
    if path.endswith("nonreg-runner.md"):
        assert "sdlc doc add nonreg" in sec
    if path.endswith("deployer.md") or "deploy-jenkins" in path:
        assert "CODE" in sec and "bind-mount" in sec


def test_run_story_passes_run_workspace_only_when_configured():
    text = (REPO / "claude" / "commands" / "run-story.md").read_text()
    assert "runWorkspace: true" in text and ".runWorkspace == true" in text
