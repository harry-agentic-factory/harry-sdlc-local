"""Run workspace library contracts: injected backend (AC19), port, idempotence, safety, stdlib only."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import sdlc.runws as runws
from sdlc.runws import (DOC_TYPES, RUN_JSON_KEYS, RUN_STATES, BrainPin, DataRepoBackend, DocumentRepository,
                        RunError, RunSource, Scope, doc_add, doc_list, doc_read, run_clean, run_finish, run_init,
                        run_list)
from sdlc.runws import lifecycle
from test_run_workspace import RECAP_DOC, git, make_demo, porcelain, write

PKG = Path(runws.__file__).parent
COMMIT = "c" * 40
BRAIN = f"project/brain/@{COMMIT}/"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class MemoryBackend:
    """In-memory `DocumentRepository` + `RunSource` (no workspace discovery: `root=` is required)."""

    def __init__(self, docs: dict[str, bytes] | None = None, *, scope: Scope | None = None,
                 bubble: dict | None = None):
        self.store: dict[str, bytes] = dict(docs if docs is not None else {
            "features/DEMO-E/atelier/prd.md": b"# prd\n",
            "features/DEMO-E/stories/DEMO-E-1/spec-func.md": b"# f1\n",
            "features/DEMO-E/stories/DEMO-E-1/spec-tech.md": b"# t1\n",
            "features/DEMO-E/stories/DEMO-E-2/spec-tech.md": b"# t2\n",
            BRAIN + "index.md": b"# index\n",
            BRAIN + "adr/0001.md": b"# adr\n",
        })
        self.scope = scope or Scope("DEMO-E", "DEMO-E-1", None)
        self.bubble_perms = bubble or {"allow": [], "deny": []}
        self.puts: list[tuple[str, dict]] = []
        self.rounds: dict[tuple, int] = {}
        self.by_uid: dict[tuple, int] = {}

    def get(self, key, version=None):
        if key not in self.store:
            raise KeyError(key)
        return self.store[key]

    def list(self, prefix):
        return [{"key": k, "version": "v-" + sha(v)[:8], "sha256": sha(v), "size": len(v), "origin": "mem/" + k}
                for k, v in sorted(self.store.items()) if k.startswith(prefix)]

    def versions(self, key):
        return ["v-" + sha(self.store[key])[:8]] if key in self.store else []

    def put(self, key, content, meta):
        if key in self.store:
            if self.store[key] != content:
                raise RunError("put_conflict", key)
        else:
            self.store[key] = content
        self.puts.append((key, meta))
        res = {"key": key, "version": None}
        if meta.get("category") == "artifact":
            scope = meta.get("story") or meta.get("ticket") or meta.get("mission")
            idem = (scope, meta["kind"], meta["run_uid"])
            if idem not in self.by_uid:
                self.rounds[(scope, meta["kind"])] = self.rounds.get((scope, meta["kind"]), 0) + 1
                self.by_uid[idem] = self.rounds[(scope, meta["kind"])]
            res["round"] = self.by_uid[idem]
        return res

    def locate(self, *, story, mission):
        if story != self.scope.story or mission != self.scope.mission:
            raise RunError("story_unknown" if story else "mission_unknown", story or mission)
        return self.scope

    def brain(self):
        return BrainPin("main", COMMIT, "local", BRAIN, None, ())

    def bubble(self, agent):
        return self.bubble_perms


def mem_init(tmp_path, backend=None, **kw):
    backend = backend or MemoryBackend()
    kw.setdefault("story", "DEMO-E-1")
    return backend, run_init(None, agent="reviewer", root=tmp_path / "worker", backend=backend, **kw)


# --- AC19 ---

def test_ac19_memory_backend_root_injected(tmp_path, monkeypatch):
    demo = make_demo(tmp_path, monkeypatch)
    before = porcelain(demo.data)
    mb, res = mem_init(tmp_path)
    root = Path(res["root"])
    assert res["root"].startswith(str(tmp_path / "worker") + "/")
    assert (root / "in" / "feature" / "atelier" / "prd.md").read_bytes() == b"# prd\n"
    assert (root / "in" / "brain" / "adr" / "0001.md").read_bytes() == b"# adr\n"
    man = json.loads(Path(res["manifest"]).read_text())
    assert len(man["files"]) == 6 and man["brain"] == {"ref": "main", "commit": COMMIT}
    assert {e["origin"] for e in man["files"]} == {"mem/" + k for k in mb.store}
    assert porcelain(demo.data) == before and not (tmp_path / "_agentws").exists()
    assert isinstance(mb, DocumentRepository) and isinstance(mb, RunSource)


def test_ac19_publication_only_via_put(tmp_path, monkeypatch):
    demo = make_demo(tmp_path, monkeypatch)
    before = porcelain(demo.data)
    mb, res = mem_init(tmp_path)
    doc_add("review", RECAP_DOC, run=res["root"])
    fin = run_finish(res["root"], backend=mb)
    uid = res["run_uid"]
    assert fin == {"run_uid": uid, "state": "published", "warnings": [],
                   "published": [{"type": "review", "round": 1, "path": f"runs/{uid}/out/docs/review.md"}]}
    keys = [k for k, _ in mb.puts]
    assert keys == [f"runs/{uid}/out/docs/review.md", f"runs/{uid}/manifest.json", f"runs/{uid}/run.json"]
    assert mb.puts[0][1] == {"category": "artifact", "kind": "review", "run_uid": uid, "agent": "reviewer",
                             "phase": "reviewer", "feature": "DEMO-E", "story": "DEMO-E-1", "mission": None,
                             "ticket": None, "at": mb.puts[0][1]["at"]}
    assert mb.puts[1][1] == {"category": "run_meta", "run_uid": uid}
    assert not any("seal" in k for k in keys)
    trace = json.loads(mb.store[f"runs/{uid}/run.json"])
    assert tuple(sorted(trace)) == RUN_JSON_KEYS and trace["state"] == "published"
    assert porcelain(demo.data) == before and not (tmp_path / "_agentws").exists()
    assert not Path(res["root"]).exists()


def test_root_required_without_discovery(tmp_path):
    with pytest.raises(RunError, match="^root_required"):
        run_init(None, agent="reviewer", story="DEMO-E-1", backend=MemoryBackend())
    mb, res = mem_init(tmp_path)
    with pytest.raises(RunError, match="^root_required"):
        run_finish(res["run_uid"], backend=mb)


# --- contracts ---

def test_runws_stdlib_only():
    allowed = set(sys.stdlib_module_names) | {"sdlc"}
    for path in sorted(PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots = [node.module.split(".")[0]]
            else:
                continue
            assert set(roots) <= allowed, (path.name, roots)


def test_public_api_all():
    expected = {"run_init", "run_finish", "run_clean", "run_list", "doc_read", "doc_list", "doc_add",
                "DocumentRepository", "RunSource", "Entry", "Scope", "BrainPin", "DataRepoBackend", "RunError",
                "DOC_TYPES", "RUN_STATES", "RUN_JSON_KEYS", "RUN_UID_RE", "ROUND_HEADER_RE", "SCHEMA_VERSION",
                "DOC_MAX_BYTES"}
    assert expected <= set(runws.__all__)
    assert all(hasattr(runws, n) for n in runws.__all__)
    out = subprocess.run([sys.executable, "-c", "import sdlc.runws as r; print(sorted(r.__all__))"],
                         capture_output=True, text=True, check=True, cwd=PKG.parents[1]).stdout
    assert out.strip() == str(sorted(runws.__all__))
    assert DOC_TYPES == ("review", "acceptance", "demo", "deploy", "implement", "nonreg", "findings", "report")
    assert RUN_STATES == ("open", "published", "rejected", "failed", "timeout")
    for path in PKG.glob("*.py"):
        if path.name != "cli.py":
            text = path.read_text(encoding="utf-8")
            assert "print(" not in text and "sys.exit" not in text, path.name


def test_core_filters_non_markdown(tmp_path):
    docs = MemoryBackend().store
    docs.update({
        "features/DEMO-E/atelier/x.png": b"png",
        "features/DEMO-E/atelier/_index.md": b"# board\n",
        "features/DEMO-E/stories/DEMO-E-1/status.json": b"{}",
        "features/DEMO-E/stories/DEMO-E-1/journal.md": b"# journal\n",
        "features/DEMO-E/stories/DEMO-E-1/repro/steps.md": b"# steps\n",
        "features/OTHER/atelier/prd.md": b"# other epic\n",
        "features/DEMO-E/stories/DEMO-E-1/../../../escape.md": b"# escape\n",
        "missions/inc-1/brief.md": b"# not this scope\n",
        BRAIN + "logo.png": b"png",
    })
    mb, res = mem_init(tmp_path, MemoryBackend(docs))
    keys = [e["key"] for e in json.loads(Path(res["manifest"]).read_text())["files"]]
    assert keys == ["brain/adr/0001.md", "brain/index.md", "feature/atelier/prd.md",
                    "feature/stories/DEMO-E-1/spec-func.md", "feature/stories/DEMO-E-1/spec-tech.md",
                    "feature/stories/DEMO-E-2/spec-tech.md"]
    files = sorted(p.relative_to(res["in"]).as_posix() for p in Path(res["in"]).rglob("*") if p.is_file())
    assert files == sorted(keys + ["manifest.json", "settings.json"])
    assert not (tmp_path / "escape.md").exists() and not (tmp_path / "worker" / "escape.md").exists()


def test_rejected_finish_never_calls_put(tmp_path):
    mb, res = mem_init(tmp_path)
    doc_add("review", RECAP_DOC, run=res["root"])
    (Path(res["in"]) / "feature" / "atelier" / "prd.md").write_bytes(b"changed\n")
    fin = run_finish(res["root"], backend=mb)
    assert fin["state"] == "rejected" and fin["reasons"] == ["in_modified:feature/atelier/prd.md"]
    assert mb.puts == []
    (Path(res["in"]) / "feature" / "atelier" / "prd.md").write_bytes(b"# prd\n")
    assert run_finish(res["root"], backend=mb)["state"] == "published"   # replayable after a fix


def test_put_add_only_conflict(tmp_path, monkeypatch):
    make_demo(tmp_path, monkeypatch)
    b = DataRepoBackend.from_project("DEMO")
    key = "runs/20260101-000000-abcdef/manifest.json"
    assert b.put(key, b"a", {"category": "run_meta"}) == {"key": key, "version": None}
    assert b.put(key, b"a", {"category": "run_meta"}) == {"key": key, "version": None}
    with pytest.raises(RunError, match="^put_conflict"):
        b.put(key, b"b", {"category": "run_meta"})
    assert b.get(key) == b"a"
    for bad in ("DEMO-E/prd.md", "runs/../x/run.json", "runs/bad-uid/run.json",
                "runs/20260101-000000-abcdef/other.json", "runs/20260101-000000-abcdef/out/docs/../../x.md"):
        with pytest.raises(RunError, match="^put_invalid_key"):
            b.put(bad, b"x", {})


def test_finish_replay_after_crash_single_header(tmp_path, monkeypatch):
    demo = make_demo(tmp_path, monkeypatch)
    b = DataRepoBackend.from_project("DEMO")
    res = run_init("DEMO", agent="reviewer", story="DEMO-E-1", backend=b)
    doc_add("review", RECAP_DOC, run=res["root"])
    real_put = DataRepoBackend.put

    def failing_put(self, key, content, meta):
        if key.endswith("/run.json"):
            raise OSError("simulated crash")
        return real_put(self, key, content, meta)

    monkeypatch.setattr(DataRepoBackend, "put", failing_put)
    with pytest.raises(OSError):
        run_finish(res["run_uid"], backend=b)
    assert json.loads((Path(res["root"]) / "run.json").read_text())["state"] == "open"
    monkeypatch.setattr(DataRepoBackend, "put", real_put)
    fin = run_finish(res["run_uid"], backend=b)
    assert fin["state"] == "published" and fin["published"][0]["round"] == 1
    review = (demo.story() / "review.md").read_bytes()
    lines = [ln for ln in review.decode().splitlines()
             if runws.ROUND_HEADER_RE.fullmatch(ln) and runws.ROUND_HEADER_RE.fullmatch(ln).group(2) == res["run_uid"]]
    assert len(lines) == 1 and review.count(RECAP_DOC) == 1


def test_init_atomic_on_failure(tmp_path, monkeypatch):
    real_write = lifecycle._write

    def failing(path, data):
        if path.name == "settings.json":
            raise OSError("disk full")
        return real_write(path, data)

    monkeypatch.setattr(lifecycle, "_write", failing)
    with pytest.raises(OSError):
        mem_init(tmp_path)
    assert list((tmp_path / "worker").iterdir()) == []


def test_run_uid_supplied_validated_and_exists(tmp_path):
    mb = MemoryBackend()
    with pytest.raises(RunError, match="^run_uid_invalid"):
        mem_init(tmp_path, mb, run_uid="2026-bad")
    uid = "20260102-030405-0a1b2c"
    _, res = mem_init(tmp_path, mb, run_uid=uid)
    assert res["run_uid"] == uid and Path(res["root"]).name == uid
    with pytest.raises(RunError, match="^run_exists"):
        mem_init(tmp_path, mb, run_uid=uid)
    doc_add("review", RECAP_DOC, run=res["root"])
    run_finish(res["root"], backend=mb)
    assert not Path(res["root"]).exists()
    with pytest.raises(RunError, match=f"^run_exists:{uid}$"):
        mem_init(tmp_path, mb, run_uid=uid)


def test_no_data_repo_commit(tmp_path, monkeypatch):
    demo = make_demo(tmp_path, monkeypatch)
    head = git(demo.data, "rev-parse", "HEAD")
    res = run_init("DEMO", agent="reviewer", story="DEMO-E-1")
    doc_add("review", RECAP_DOC, run=res["root"])
    run_finish(res["run_uid"], backend=DataRepoBackend.from_project("DEMO"))
    assert git(demo.data, "rev-parse", "HEAD") == head
    changed = porcelain(demo.data)
    assert "runs/" in changed and "DEMO-E/stories/DEMO-E-1/review.md" in changed


def test_agent_root_paths(tmp_path):
    mb = MemoryBackend(bubble={"allow": ["Bash(ls:*)"], "deny": ["Bash(rm:*)"]})
    _, res = mem_init(tmp_path, mb, agent_root="/work")
    text = Path(res["settings"]).read_text()
    perms = json.loads(text)["permissions"]
    assert perms == {"additionalDirectories": ["/work/in", "/work/rw"], "allow": ["Bash(ls:*)"],
                     "deny": ["Bash(rm:*)", "Edit(//work/in/**)", "Write(//work/in/**)"]}
    assert res["root"] not in text and str(tmp_path) not in text
    assert res["root"].startswith(str(tmp_path / "worker"))
    for bad in ("work", "", "/work/../x", "relative/path"):
        with pytest.raises(RunError, match="^agent_root_invalid"):
            mem_init(tmp_path, agent_root=bad)


def test_finish_outcome_timeout_failed(tmp_path):
    mb, res = mem_init(tmp_path)
    doc_add("review", b"partial\n", run=res["root"])
    with pytest.raises(RunError, match="^outcome_invalid"):
        run_finish(res["root"], backend=mb, outcome="crashed")
    fin = run_finish(res["root"], backend=mb, outcome="timeout", keep=True)
    assert fin["state"] == "timeout" and fin["warnings"] == ["no_recap"] and len(fin["published"]) == 1
    assert json.loads(mb.store[f"runs/{res['run_uid']}/run.json"])["state"] == "timeout"
    assert run_finish(res["root"], backend=mb) == {"run_uid": res["run_uid"], "already": "timeout"}
    mb2, res2 = mem_init(tmp_path)
    (Path(res2["in"]) / "brain" / "index.md").write_bytes(b"x")
    fin2 = run_finish(res2["root"], backend=mb2, outcome="failed")
    assert fin2["state"] == "rejected" and mb2.puts == []
    (Path(res2["in"]) / "brain" / "index.md").write_bytes(b"# index\n")
    assert run_finish(res2["root"], backend=mb2, outcome="failed")["state"] == "failed"


def test_doc_read_alias_precedence(tmp_path):
    docs = MemoryBackend().store
    docs.update({
        "features/DEMO-E/stories/brain/index.md": b"# story named brain\n",
        "features/DEMO-E/stories/atelier/prd.md": b"# story named atelier\n",
        "features/DEMO-E/atelier/spec-review.md": b"# spec review\n",
    })
    _, res = mem_init(tmp_path, MemoryBackend(docs))
    run = res["root"]
    assert doc_read("brain/index", run=run) == b"# index\n"
    assert doc_read("atelier/prd", run=run) == b"# prd\n"
    assert doc_read("prd", run=run) == b"# prd\n"
    assert doc_read("atelier/spec-review", run=run) == b"# spec review\n"
    assert doc_read("spec-tech", run=run) == b"# t1\n"
    assert doc_read("DEMO-E-2/spec-tech", run=run) == b"# t2\n"
    assert doc_read("feature/stories/brain/index", run=run) == b"# story named brain\n"
    assert doc_read("feature/stories/brain/index.md", run=run) == b"# story named brain\n"
    assert doc_read("brain/index.md", run=run) == b"# index\n"
    with pytest.raises(RunError, match="^unknown_key:brief"):
        doc_read("brief", run=run)
    keys = [d["key"] for d in doc_list(run=run)]
    assert "brain/index" in keys and "brain/index.md" not in keys and "atelier/spec-review" in keys


def test_mission_scope_memory_backend(tmp_path):
    mb = MemoryBackend({"missions/inc-7/brief.md": b"# brief\n", "missions/inc-7/sources/a/b.md": b"# b\n",
                        "missions/inc-7/sources/c.txt": b"c", "missions/inc-8/brief.md": b"# other\n"},
                       scope=Scope(None, None, "inc-7"))
    res = run_init(None, agent="investigator", mission="inc-7", root=tmp_path / "w", backend=mb)
    assert doc_read("brief", run=res["root"]) == b"# brief\n"
    assert doc_read("mission/sources/a/b", run=res["root"]) == b"# b\n"
    assert json.loads(Path(res["manifest"]).read_text())["scope"] == {"feature": None, "story": None,
                                                                       "mission": "inc-7"}
    doc_add("findings", RECAP_DOC, run=res["root"])
    assert run_finish(res["root"], backend=mb)["published"][0]["round"] == 1
    assert mb.puts[0][1]["mission"] == "inc-7" and mb.puts[0][1]["story"] is None


def test_clean_and_list_by_path_memory_backend(tmp_path):
    mb, res = mem_init(tmp_path)
    assert run_list(backend=mb) == []                          # no discovery, no trace yet
    assert run_clean(res["root"]) == {"run_uid": res["run_uid"], "cleaned": True}
    with pytest.raises(RunError, match="^run_unknown"):
        run_clean(res["root"])
    with pytest.raises(RunError, match="^run_unknown"):
        run_clean(tmp_path)                                      # not a run workspace: never removed
    assert tmp_path.is_dir()


def test_doc_add_refuses_symlinked_out(tmp_path):
    _, res = mem_init(tmp_path)
    docs = Path(res["out"]) / "docs"
    os.rename(docs, Path(res["out"]) / "docs-real")
    os.symlink(Path(res["out"]) / "docs-real", docs)
    with pytest.raises(RunError, match="^run_invalid"):
        doc_add("review", b"x", run=res["root"])


def test_run_error_str():
    assert str(RunError("story_unknown", "DEMO-E-99")) == "story_unknown:DEMO-E-99"
    assert str(RunError("run_not_set")) == "run_not_set"
