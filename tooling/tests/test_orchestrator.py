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


def at_implemented(tmp_path, story="SAMPLE-T-1"):
    s = Sdlc(Workspace(tmp_path), NullBoard())
    s.create_epic("SAMPLE-T", "demo")
    s.create_ticket("SAMPLE-T", story, "t")
    for st in ("spec_func", "spec_tech", "implemented"):
        s.set_status(story, st)
    return s


def test_happy_upstream_stops_for_validation(tmp_path):
    s = at_implemented(tmp_path)
    o = run_ticket_upstream(s, "SAMPLE-T-1", dict(BASE), escalation=AUTO)
    assert o.reason == "await_validation" and o.stopped_at == "recette"
    assert s.get_ticket("SAMPLE-T-1")["status"] == "recette_ok"


def test_review_non_conform_escalates(tmp_path):
    s = at_implemented(tmp_path)
    ag = dict(BASE, reviewer=lambda c: {"conform": False, "note": "invariant X violé"})
    o = run_ticket_upstream(s, "SAMPLE-T-1", ag)
    assert o.reason == "needs_human" and o.stopped_at == "review"
    assert s.get_ticket("SAMPLE-T-1")["status"] == "implemented"  # inchangé


def test_deploy_human_confirm_gate(tmp_path):
    s = at_implemented(tmp_path)
    o = run_ticket_upstream(s, "SAMPLE-T-1", dict(BASE), escalation={"deploy": "human-confirm"})
    assert o.reason == "needs_human" and o.stopped_at == "deploy"
    assert s.get_ticket("SAMPLE-T-1")["status"] == "reviewed"


def test_fix_loop_recovers(tmp_path):
    s = at_implemented(tmp_path)
    seq = iter([{"pass": False, "repro": "repro/"}, {"pass": True}])
    calls = {"fix": 0}

    def fixer(c):
        calls["fix"] += 1
        return {"fixed": True}

    ag = dict(BASE, recetteur=lambda c: next(seq), fixer=fixer)
    o = run_ticket_upstream(s, "SAMPLE-T-1", ag, escalation=AUTO)
    assert o.reason == "await_validation" and calls["fix"] == 1
    assert s.get_ticket("SAMPLE-T-1")["status"] == "recette_ok"


def test_fix_loop_exhausts(tmp_path):
    s = at_implemented(tmp_path)
    ag = dict(BASE, recetteur=lambda c: {"pass": False, "repro": "r"})
    o = run_ticket_upstream(s, "SAMPLE-T-1", ag, escalation=AUTO, max_fix=2)
    assert o.reason == "needs_human" and o.stopped_at == "recette"


def test_flaky_bails_out(tmp_path):
    s = at_implemented(tmp_path)
    ag = dict(BASE, recetteur=lambda c: {"pass": False, "flaky": True})
    o = run_ticket_upstream(s, "SAMPLE-T-1", ag, escalation=AUTO)
    assert o.reason == "needs_human"


def test_downstream_then_accept_done(tmp_path):
    s = at_implemented(tmp_path)
    run_ticket_upstream(s, "SAMPLE-T-1", dict(BASE), escalation=AUTO)
    ag = {"e2e_author": lambda c: {"spec": "x"}, "nonreg": lambda c: {"pass": True},
          "demo": lambda c: {"demo": "d"}}
    o = run_ticket_downstream(s, "SAMPLE-T-1", ag)
    assert o.reason == "await_validation" and o.stopped_at == "demo"
    accept(s, "SAMPLE-T-1")
    assert s.get_ticket("SAMPLE-T-1")["status"] == "done"


def test_downstream_nonreg_regression(tmp_path):
    s = at_implemented(tmp_path)
    run_ticket_upstream(s, "SAMPLE-T-1", dict(BASE), escalation=AUTO)
    ag = {"e2e_author": lambda c: {"spec": "x"}, "nonreg": lambda c: {"pass": False},
          "demo": lambda c: {"demo": "d"}}
    o = run_ticket_downstream(s, "SAMPLE-T-1", ag)
    assert o.reason == "needs_human" and o.stopped_at == "nonreg"


# --- run workspace mode (AC15): one init + one finish per agent, transitions carried by finish ---

class StubRunWorkspace:
    """Records its calls and applies `status` like the engine (`run init --status`, `run finish --status`)."""

    def __init__(self, sdlc, story, reject_role=None):
        self.sdlc, self.story, self.reject_role = sdlc, story, reject_role
        self.calls: list = []
        self.n = 0

    def init(self, story, role, **opts):
        self.n += 1
        uid = f"20260101-000000-00000{self.n}"
        self.calls.append(("init", role, opts))
        if opts.get("status") and self.sdlc.get_ticket(story)["status"] != opts["status"]:
            self.sdlc.set_status(story, opts["status"])
        return {"run_uid": uid, "root": f"/runs/{uid}", "in": f"/runs/{uid}/in", "out": f"/runs/{uid}/rw/out",
                "repos": {}, "role": role}

    def finish(self, run_uid, status=None):
        self.calls.append(("finish", run_uid, status))
        inits = [c for c in self.calls if c[0] == "init"]
        if self.reject_role and inits[-1][1] == self.reject_role:
            return {"run_uid": run_uid, "state": "rejected", "reasons": ["in_modified:x"]}
        if status:
            self.sdlc.set_status(self.story, status)
        return {"run_uid": run_uid, "state": "published"}


def _recording(agents):
    seen: list = []

    def wrap(name, fn):
        def call(ctx):
            seen.append((name, ctx))
            return fn(ctx)
        return call
    return {k: wrap(k, v) for k, v in agents.items()}, seen


def test_ac15_run_workspace_init_finish_per_agent(tmp_path):
    s = at_implemented(tmp_path)
    seq = iter([{"pass": False, "repro": "forged"}, {"pass": True}])
    ag, seen = _recording(dict(BASE, recetteur=lambda c: next(seq)))
    rw = StubRunWorkspace(s, "SAMPLE-T-1")
    o = run_ticket_upstream(s, "SAMPLE-T-1", ag, escalation=AUTO, run_workspace=rw)
    assert o.reason == "await_validation"
    roles = [c[1] for c in rw.calls if c[0] == "init"]
    assert roles == ["reviewer", "deployer", "recetteur", "fixer", "recetteur"] == \
        [n for n, _ in seen] and len([c for c in rw.calls if c[0] == "finish"]) == len(seen)
    kinds = [c[0] for c in rw.calls]
    assert kinds == ["init", "finish"] * 5
    statuses = [c[2] for c in rw.calls if c[0] == "finish"]
    assert statuses == ["reviewed", "deployed", None, "reviewed", "recette_ok"]
    fixer_init = [c for c in rw.calls if c[0] == "init" and c[1] == "fixer"][0]
    assert fixer_init[2] == {"status": "implemented", "repro": "20260101-000000-000003"}


def test_ac15_ctx_has_run_no_data_paths(tmp_path):
    s = at_implemented(tmp_path)
    ag, seen = _recording(dict(BASE))
    run_ticket_upstream(s, "SAMPLE-T-1", ag, escalation=AUTO, run_workspace=StubRunWorkspace(s, "SAMPLE-T-1"))
    for _, ctx in seen:
        assert "root" in ctx["run"] and "artifacts" not in ctx and "bubble" not in ctx
        assert not any(isinstance(v, str) and str(tmp_path) in v for v in ctx.values())


def test_ac15_final_status_identical_happy_and_fix_loop(tmp_path):
    def fix_loop():
        seq = iter([{"pass": False, "repro": "r"}, {"pass": True}])
        return dict(BASE, recetteur=lambda c: next(seq))
    for i, agents in enumerate((lambda: dict(BASE), fix_loop)):
        plain = at_implemented(tmp_path / f"plain{i}")
        o1 = run_ticket_upstream(plain, "SAMPLE-T-1", agents(), escalation=AUTO)
        rw = at_implemented(tmp_path / f"rw{i}")
        o2 = run_ticket_upstream(rw, "SAMPLE-T-1", agents(), escalation=AUTO,
                                 run_workspace=StubRunWorkspace(rw, "SAMPLE-T-1"))
        assert (o1.stopped_at, o1.reason) == (o2.stopped_at, o2.reason)
        assert plain.get_ticket("SAMPLE-T-1")["status"] == rw.get_ticket("SAMPLE-T-1")["status"] == "recette_ok"
    s = at_implemented(tmp_path / "down")
    run_ticket_upstream(s, "SAMPLE-T-1", dict(BASE), escalation=AUTO)
    rw = StubRunWorkspace(s, "SAMPLE-T-1")
    ag = {"e2e_author": lambda c: {"spec": "x"}, "nonreg": lambda c: {"pass": True}, "demo": lambda c: {"demo": "d"}}
    o = run_ticket_downstream(s, "SAMPLE-T-1", ag, run_workspace=rw)
    assert o.reason == "await_validation" and [c[1] for c in rw.calls if c[0] == "init"] == \
        ["e2e-author", "nonreg-runner", "demo"] and all(c[2] is None for c in rw.calls if c[0] == "finish")


def test_rw_fix_not_fixed_needs_human(tmp_path):
    s = at_implemented(tmp_path)
    ag = dict(BASE, recetteur=lambda c: {"pass": False, "repro": "r"}, fixer=lambda c: {"fixed": False})
    rw = StubRunWorkspace(s, "SAMPLE-T-1")
    o = run_ticket_upstream(s, "SAMPLE-T-1", ag, escalation=AUTO, run_workspace=rw)
    assert (o.stopped_at, o.reason, o.detail) == ("recette", "needs_human", "fix failed")
    assert s.get_ticket("SAMPLE-T-1")["status"] == "implemented"
    assert [c[2] for c in rw.calls if c[0] == "finish"][-1] is None


def test_rw_finish_rejected_needs_human(tmp_path):
    s = at_implemented(tmp_path)
    ag, seen = _recording(dict(BASE))
    rw = StubRunWorkspace(s, "SAMPLE-T-1", reject_role="deployer")
    o = run_ticket_upstream(s, "SAMPLE-T-1", ag, escalation=AUTO, run_workspace=rw)
    assert (o.stopped_at, o.reason, o.detail) == ("deploy", "needs_human", "finish_rejected")
    assert [n for n, _ in seen] == ["reviewer", "deployer"] and s.get_ticket("SAMPLE-T-1")["status"] == "reviewed"
