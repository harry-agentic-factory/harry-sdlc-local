"""Golden test de l'orchestration `run-ticket` en mode STUB (agents bidon, 0 LLM).

Prouve l'enchaînement, les gates, le fix-loop et l'escalation de façon déterministe.
"""
from sdlc import Sdlc, Workspace
from sdlc.board import NullBoard
from sdlc.orchestrator import run_ticket_upstream, run_ticket_downstream, accept

BASE = {
    "reviewer": lambda c: {"conform": True},
    "deployer": lambda c: {"ok": True, "version": "1"},
    "recetteur": lambda c: {"pass": True},
    "fixer": lambda c: {"fixed": True},
}

# escalation tout-auto (par défaut, deploy = human-confirm → gate prod)
AUTO = {"review": "auto", "deploy": "auto", "recette": "auto-then-human", "nonreg": "human-on-fail"}


def at_implemented(tmp_path, story="HIA-T-1"):
    s = Sdlc(Workspace(tmp_path), NullBoard())
    s.create_epic("HIA-T", "demo")
    s.create_ticket("HIA-T", story, "t")
    for st in ("spec_func", "spec_tech", "implemented"):
        s.set_status(story, st)
    return s


def test_happy_upstream_stops_for_validation(tmp_path):
    s = at_implemented(tmp_path)
    o = run_ticket_upstream(s, "HIA-T-1", dict(BASE), escalation=AUTO)
    assert o.reason == "await_validation" and o.stopped_at == "recette"
    assert s.get_ticket("HIA-T-1")["status"] == "recette_ok"


def test_review_non_conform_escalates(tmp_path):
    s = at_implemented(tmp_path)
    ag = dict(BASE, reviewer=lambda c: {"conform": False, "note": "invariant X violé"})
    o = run_ticket_upstream(s, "HIA-T-1", ag)
    assert o.reason == "needs_human" and o.stopped_at == "review"
    assert s.get_ticket("HIA-T-1")["status"] == "implemented"  # inchangé


def test_deploy_human_confirm_gate(tmp_path):
    s = at_implemented(tmp_path)
    o = run_ticket_upstream(s, "HIA-T-1", dict(BASE), escalation={"deploy": "human-confirm"})
    assert o.reason == "needs_human" and o.stopped_at == "deploy"
    assert s.get_ticket("HIA-T-1")["status"] == "reviewed"


def test_fix_loop_recovers(tmp_path):
    s = at_implemented(tmp_path)
    seq = iter([{"pass": False, "repro": "repro/"}, {"pass": True}])
    calls = {"fix": 0}

    def fixer(c):
        calls["fix"] += 1
        return {"fixed": True}

    ag = dict(BASE, recetteur=lambda c: next(seq), fixer=fixer)
    o = run_ticket_upstream(s, "HIA-T-1", ag, escalation=AUTO)
    assert o.reason == "await_validation" and calls["fix"] == 1
    assert s.get_ticket("HIA-T-1")["status"] == "recette_ok"


def test_fix_loop_exhausts(tmp_path):
    s = at_implemented(tmp_path)
    ag = dict(BASE, recetteur=lambda c: {"pass": False, "repro": "r"})
    o = run_ticket_upstream(s, "HIA-T-1", ag, escalation=AUTO, max_fix=2)
    assert o.reason == "needs_human" and o.stopped_at == "recette"


def test_flaky_bails_out(tmp_path):
    s = at_implemented(tmp_path)
    ag = dict(BASE, recetteur=lambda c: {"pass": False, "flaky": True})
    o = run_ticket_upstream(s, "HIA-T-1", ag, escalation=AUTO)
    assert o.reason == "needs_human"


def test_downstream_then_accept_done(tmp_path):
    s = at_implemented(tmp_path)
    run_ticket_upstream(s, "HIA-T-1", dict(BASE), escalation=AUTO)
    ag = {"e2e_author": lambda c: {"spec": "x"}, "nonreg": lambda c: {"pass": True},
          "demo": lambda c: {"demo": "d"}}
    o = run_ticket_downstream(s, "HIA-T-1", ag)
    assert o.reason == "await_validation" and o.stopped_at == "demo"
    accept(s, "HIA-T-1")
    assert s.get_ticket("HIA-T-1")["status"] == "done"


def test_downstream_nonreg_regression(tmp_path):
    s = at_implemented(tmp_path)
    run_ticket_upstream(s, "HIA-T-1", dict(BASE), escalation=AUTO)
    ag = {"e2e_author": lambda c: {"spec": "x"}, "nonreg": lambda c: {"pass": False},
          "demo": lambda c: {"demo": "d"}}
    o = run_ticket_downstream(s, "HIA-T-1", ag)
    assert o.reason == "needs_human" and o.stopped_at == "nonreg"
