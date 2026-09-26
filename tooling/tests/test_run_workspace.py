"""Run workspace (`sdlc run`, `sdlc doc`) on a throwaway DEMO project: AC1-AC18.

Fixture (P): data repository `DEMO` (epic `DEMO-E`, stories `DEMO-E-1` with spec-func + spec-tech and
`DEMO-E-2` with spec-tech, epic `prd.md`), written by hand and committed; brain git repository with
`index.md`, `adr/0001.md`, `logo.png` committed on `main` (C1); manifest without `brainRef`.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdlc import cli
from sdlc.runws import ROUND_HEADER_RE, RUN_JSON_KEYS, RUN_UID_RE

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]
SPEC_FUNC_1 = b"# DEMO-E-1 spec-func\n\nBehaviour.\n"
SPEC_TECH_1 = b"# DEMO-E-1 spec-tech\n\nPlan \xc3\xa0 la main.\n"   # non ASCII bytes kept as is
SPEC_TECH_2 = b"# DEMO-E-2 spec-tech\n\nOther plan.\n"
PRD = b"# DEMO-E prd\n\nNeed.\n"
BRAIN_INDEX_C1 = b"# Index C1\n"
BRAIN_ADR = b"# ADR 1\n\nDecision.\n"
RECAP_DOC = b"## Recap\nOK\n"
OLD_REVIEW = (b"<!-- round 1 \xc2\xb7 run 20260101-000000-aaaaaa \xc2\xb7 agent reviewer \xc2\xb7 "
              b"2026-01-01T00:00:00Z -->\n## Recap\nfirst review\n\nBody of round 1.\n")


# --- helpers ---

def git(repo, *args, check=True) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check).stdout.strip()


def write(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def commit_all(repo: Path, msg: str = "c") -> str:
    git(repo, "add", "-A")
    git(repo, *GIT_ID, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def status_json(story: str) -> bytes:
    return json.dumps({"id": story, "epic": "DEMO-E", "title": story, "status": "spec_tech", "deps": [],
                       "repos": [], "branch": None, "mr": None, "artifacts": {}}).encode()


@dataclass
class Demo:
    tmp: Path
    data: Path
    brain: Path
    c1: str
    root_base: Path
    config: dict

    def story(self, us: str = "DEMO-E-1") -> Path:
        return self.data / "DEMO-E" / "stories" / us

    def set_config(self, **extra) -> None:
        cfg = {**self.config, **extra}
        (self.data / "sdlc.config.json").write_text(json.dumps(cfg))


def make_demo(tmp_path: Path, monkeypatch, **cfg_extra) -> Demo:
    data = tmp_path / "data"
    data.mkdir()
    git(data, "init", "-q", "-b", "main")
    config = {"prefix": "DEMO", "reposRoot": str(tmp_path), "brain": "brain", **cfg_extra}
    write(data, "sdlc.config.json", json.dumps(config).encode())
    write(data, "DEMO-E/prd.md", PRD)
    write(data, "DEMO-E/stories/DEMO-E-1/status.json", status_json("DEMO-E-1"))
    write(data, "DEMO-E/stories/DEMO-E-1/spec-func.md", SPEC_FUNC_1)
    write(data, "DEMO-E/stories/DEMO-E-1/spec-tech.md", SPEC_TECH_1)
    write(data, "DEMO-E/stories/DEMO-E-2/status.json", status_json("DEMO-E-2"))
    write(data, "DEMO-E/stories/DEMO-E-2/spec-tech.md", SPEC_TECH_2)
    commit_all(data, "data")
    brain = tmp_path / "brain"
    brain.mkdir()
    git(brain, "init", "-q", "-b", "main")
    write(brain, "index.md", BRAIN_INDEX_C1)
    write(brain, "adr/0001.md", BRAIN_ADR)
    write(brain, "logo.png", b"\x89PNG\r\n\x1a\n")
    c1 = commit_all(brain, "C1")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SDLC_WORKSPACE", str(data))
    monkeypatch.delenv("SDLC_RUN", raising=False)
    return Demo(tmp_path, data, brain, c1, tmp_path / "_agentws" / "DEMO", config)


def call(cap, *argv):
    """(exit code, stdout bytes, stderr text) of `sdlc --project DEMO <argv>`."""
    rc = cli.main(["--project", "DEMO", *[str(a) for a in argv]])
    out = cap.readouterr()
    return rc, out.out, out.err.decode("utf-8", errors="replace")


def ok(cap, *argv):
    rc, out, err = call(cap, *argv)
    assert rc == 0, err
    return json.loads(out)


def init(cap, *argv) -> dict:
    return ok(cap, "run", "init", *(argv or ("DEMO-E-1", "--agent", "reviewer")))


def add(cap, monkeypatch, doc_type: str, data: bytes, run: str):
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data)))
    return call(cap, "doc", "add", doc_type, "-", "--run", run)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_dirs(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir()}


def porcelain(repo: Path, *paths: str) -> str:
    return git(repo, "status", "--porcelain", "--untracked-files=all", *(["--", *paths] if paths else []))


@pytest.fixture
def demo(tmp_path, monkeypatch) -> Demo:
    return make_demo(tmp_path, monkeypatch)


@pytest.fixture
def cap(capsysbinary):
    return capsysbinary


# --- AC1 ---

def test_ac1_init_creates_exact_tree(demo, cap):
    res = init(cap)
    root = Path(res["root"])
    assert root.parent == demo.root_base / "DEMO-E-1" and root.is_dir()
    assert tree_dirs(root) == {
        "in", "in/brain", "in/brain/adr", "in/feature", "in/feature/atelier", "in/feature/stories",
        "in/feature/stories/DEMO-E-1", "in/feature/stories/DEMO-E-2", "rw", "rw/code", "rw/scratch",
        "rw/out", "rw/out/docs", "rw/out/sources", "rw/out/git"}
    assert set(res) == {"run_uid", "root", "in", "rw", "out", "code", "scratch", "settings", "manifest",
                        "brain", "warnings"}
    assert res["in"] == str(root / "in") and res["out"] == str(root / "rw" / "out")
    assert res["scratch"] == str(root / "rw" / "scratch") and res["code"] == str(root / "rw" / "code")
    assert res["warnings"] == []
    assert res["brain"] == {"ref": "main", "commit": demo.c1, "from": "local", "files": 2,
                            "bytes": len(BRAIN_INDEX_C1) + len(BRAIN_ADR)}


def test_ac1_run_json_exact_keys_and_values(demo, cap):
    from sdlc.migrations import engine_version
    res = init(cap)
    run = json.loads((Path(res["root"]) / "run.json").read_text())
    assert ",".join(sorted(run)) == ("agent,created_at,engine,feature,finished_at,mission,phase,published,"
                                     "reasons,run_uid,schema_version,state,story,ticket")
    assert tuple(sorted(run)) == RUN_JSON_KEYS
    assert run["state"] == "open" and run["phase"] == "reviewer" and run["agent"] == "reviewer"
    assert (run["feature"], run["story"], run["mission"], run["ticket"]) == ("DEMO-E", "DEMO-E-1", None, None)
    assert run["finished_at"] is None and run["reasons"] == [] and run["published"] == []
    assert run["engine"] == {"name": "harry-sdlc", "version": engine_version()}
    assert run["schema_version"] == 1 and run["run_uid"] == res["run_uid"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", run["created_at"])
    res2 = init(cap, "DEMO-E-1", "--agent", "dev", "--phase", "implement")
    run2 = json.loads((Path(res2["root"]) / "run.json").read_text())
    assert (run2["agent"], run2["phase"]) == ("dev", "implement")


def test_ac1_run_uid_format_and_unique(demo, cap):
    a, b = init(cap), init(cap)
    assert RUN_UID_RE.fullmatch(a["run_uid"]) and RUN_UID_RE.fullmatch(b["run_uid"])
    assert a["run_uid"] != b["run_uid"]
    assert Path(a["root"]).is_dir() and Path(b["root"]).is_dir()
    assert Path(a["root"]).name == a["run_uid"]


# --- AC2 ---

def test_ac2_pull_markdown_only(demo, cap):
    write(demo.story(), "journal.md", b"# journal\n")
    write(demo.story(), "repro/x.bin", b"\x00\x01")
    write(demo.story(), "repro/steps.md", b"# steps\n")
    res = init(cap)
    in_dir = Path(res["in"])
    files = [p for p in in_dir.rglob("*") if p.is_file()]
    assert [p for p in files if p.suffix != ".md" and p.name not in ("manifest.json", "settings.json")] == []
    assert (in_dir / "brain" / "adr" / "0001.md").is_file()
    assert not (in_dir / "brain" / "logo.png").exists()
    assert not (in_dir / "feature" / "stories" / "DEMO-E-1" / "journal.md").exists()
    assert not (in_dir / "feature" / "stories" / "DEMO-E-1" / "repro").exists()
    man = json.loads((in_dir / "manifest.json").read_text())
    md = [p for p in files if p.suffix == ".md"]
    assert len(man["files"]) == len(md) == 6


def test_ac2_excludes_status_journal_repro_index(demo, cap):
    write(demo.data, "DEMO-E/_index.md", b"# board\n")
    write(demo.data, "DEMO-E/refine.md", b"# refine\n")
    write(demo.data, "DEMO-E/spec-review.md", b"# review of specs\n")
    write(demo.data, "DEMO-E/notes.txt", b"not markdown\n")
    write(demo.story("DEMO-E-2"), "journal.md", b"# journal\n")
    res = init(cap)
    keys = [e["key"] for e in json.loads(Path(res["manifest"]).read_text())["files"]]
    assert "feature/atelier/refine.md" in keys and "feature/atelier/spec-review.md" in keys
    assert not any(k.endswith(("_index.md", "journal.md", "status.json", ".txt")) for k in keys)
    assert keys == sorted(keys)


# --- AC3 ---

def test_ac3_manifest_entry_keys_and_sha256(demo, cap):
    res = init(cap)
    man = json.loads(Path(res["manifest"]).read_text())
    assert list(man) == ["schema_version", "run_uid", "scope", "files", "brain", "dirty"]
    assert man["scope"] == {"feature": "DEMO-E", "story": "DEMO-E-1", "mission": None}
    assert {",".join(sorted(e)) for e in man["files"]} == {"key,origin,sha256,size,version"}
    for e in man["files"]:
        data = (Path(res["in"]) / e["key"]).read_bytes()
        assert e["sha256"] == sha(data) and e["size"] == len(data)
    assert man["brain"] == {"ref": "main", "commit": demo.c1}
    assert man["dirty"] == []


def test_ac3_versions_data_commit_brain_blob(demo, cap):
    res = init(cap)
    files = {e["key"]: e for e in json.loads(Path(res["manifest"]).read_text())["files"]}
    prd = files["feature/atelier/prd.md"]
    assert prd["version"] == git(demo.data, "log", "-1", "--format=%H", "--", "DEMO-E/prd.md")
    assert prd["origin"] == "DEMO-E/prd.md"
    adr = files["brain/adr/0001.md"]
    assert adr["version"] == git(demo.brain, "rev-parse", f"{demo.c1}:adr/0001.md")
    assert adr["origin"] == "adr/0001.md"
    assert files["feature/stories/DEMO-E-2/spec-tech.md"]["origin"] == "DEMO-E/stories/DEMO-E-2/spec-tech.md"


def test_ac3_dirty_file_null_version(demo, cap):
    write(demo.story(), "spec-func.md", SPEC_FUNC_1 + b"uncommitted\n")
    write(demo.story(), "notes.md", b"# untracked\n")
    res = init(cap)
    man = json.loads(Path(res["manifest"]).read_text())
    files = {e["key"]: e for e in man["files"]}
    assert files["feature/stories/DEMO-E-1/spec-func.md"]["version"] is None
    assert files["feature/stories/DEMO-E-1/notes.md"]["version"] is None
    assert files["feature/stories/DEMO-E-1/spec-tech.md"]["version"] is not None
    assert man["dirty"] == ["feature/stories/DEMO-E-1/notes.md", "feature/stories/DEMO-E-1/spec-func.md"]


# --- AC4 ---

PERMS = {"deny": ["Bash(rm -rf:*)"], "agents": {"reviewer": {"allow": ["Bash(git diff:*)"]},
                                                "dev": {"allow": ["Bash(make:*)"]}}}


def test_ac4_bubble_two_dirs_and_in_deny(demo, cap):
    res = init(cap)
    root = res["root"]
    perms = json.loads(Path(res["settings"]).read_text())["permissions"]
    assert perms["additionalDirectories"] == [f"{root}/in", f"{root}/rw"]
    assert f"Edit(/{root}/in/**)" in perms["deny"] and f"Write(/{root}/in/**)" in perms["deny"]
    assert len([d for d in perms["deny"] if re.search(r"in/\*\*", d)]) >= 2
    for rule in perms["deny"][-2:]:
        assert rule.split("(", 1)[1].startswith("//") and not rule.split("(", 1)[1].startswith("///")
    assert "allow" not in perms


def test_ac4_bubble_role_allow_and_shared_deny(demo, cap):
    demo.set_config(permissions=PERMS)
    res = init(cap)
    perms = json.loads(Path(res["settings"]).read_text())["permissions"]
    assert perms["allow"] == ["Bash(git diff:*)"]
    assert perms["deny"][0] == "Bash(rm -rf:*)" and len(perms["deny"]) == 3


def test_ac4_no_data_or_brain_path(demo, cap):
    res = init(cap)
    text = Path(res["settings"]).read_text()
    assert str(demo.data) not in text and str(demo.brain) not in text


# --- AC5 ---

def test_ac5_unknown_story_creates_nothing(demo, cap):
    rc, out, err = call(cap, "run", "init", "DEMO-E-99", "--agent", "reviewer")
    assert rc != 0 and "DEMO-E-99" in json.loads(err)["error"]
    assert json.loads(err)["error"] == "story_unknown:DEMO-E-99"
    assert not (demo.root_base / "DEMO-E-99").exists()
    assert not demo.root_base.exists()


@pytest.mark.parametrize("argv,code", [
    (["DEMO-E-1"], "agent_missing"),
    (["DEMO-E-1", "--agent", "Bad Agent"], "agent_invalid"),
    (["--agent", "reviewer"], "scope_invalid"),
    (["DEMO-E-1", "--mission", "inc-1", "--agent", "reviewer"], "scope_invalid"),
    (["../x", "--agent", "reviewer"], "scope_invalid"),
    (["--mission", "a/b", "--agent", "reviewer"], "scope_invalid"),
])
def test_init_scope_invalid_and_agent_missing(demo, cap, argv, code):
    rc, out, err = call(cap, "run", "init", *argv)
    assert rc == 1 and out == b""
    assert json.loads(err)["error"].split(":", 1)[0] == code
    assert not demo.root_base.exists()


# --- AC6 ---

def test_ac6_doc_read_aliases_exact_bytes(demo, cap, monkeypatch):
    res = init(cap)
    monkeypatch.setenv("SDLC_RUN", res["root"])
    for key, expected in [
        ("spec-tech", SPEC_TECH_1),
        ("DEMO-E-2/spec-tech", SPEC_TECH_2),
        ("brain/adr/0001", git_show(demo.brain, f"{demo.c1}:adr/0001.md")),
        ("prd", PRD),
        ("DEMO-E-1/spec-func", SPEC_FUNC_1),
    ]:
        rc, out, err = call(cap, "doc", "read", key)
        assert rc == 0, err
        assert out == expected, key


def git_show(repo: Path, obj: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), "show", obj], capture_output=True, check=True).stdout


def test_ac6_unknown_key_lists_keys(demo, cap, monkeypatch):
    res = init(cap)
    monkeypatch.setenv("SDLC_RUN", res["root"])
    rc, out, err = call(cap, "doc", "read", "unknown")
    assert rc != 0 and out == b""
    msg = json.loads(err)["error"]
    assert msg.startswith("unknown_key:unknown; available:") and "prd" in msg and "brain/index" in msg


def test_ac6_doc_list_six_entries(demo, cap):
    res = init(cap)
    lst = ok(cap, "doc", "list", "--run", res["root"])
    assert len(lst) == 6
    assert [d["key"] for d in lst] == sorted(["prd", "DEMO-E-1/spec-func", "DEMO-E-1/spec-tech",
                                              "DEMO-E-2/spec-tech", "brain/adr/0001", "brain/index"])
    assert all(set(d) == {"key", "path", "version"} for d in lst)
    prd = next(d for d in lst if d["key"] == "prd")
    assert prd["path"] == "feature/atelier/prd.md" and prd["version"]


@pytest.mark.parametrize("key", ["../x", "/etc/passwd", "brain/../../x", "feature/../../run.json",
                                 "../../seal.json", "manifest.json", "settings.json"])
def test_doc_read_rejects_traversal(demo, cap, key):
    res = init(cap)
    rc, out, err = call(cap, "doc", "read", key, "--run", res["root"])
    assert rc == 1 and out == b""
    assert json.loads(err)["error"].startswith("unknown_key:")


def test_doc_commands_without_project(demo, cap, monkeypatch):
    res = init(cap)
    empty_home = demo.tmp / "empty-home"
    empty_home.mkdir()
    elsewhere = demo.tmp / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.delenv("SDLC_WORKSPACE")
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("SDLC_RUN", res["root"])
    rc = cli.main(["doc", "read", "spec-tech"])
    assert rc == 0 and cap.readouterr().out == SPEC_TECH_1
    rc = cli.main(["doc", "list"])
    assert rc == 0 and len(json.loads(cap.readouterr().out)) == 6
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(RECAP_DOC)))
    rc = cli.main(["doc", "add", "review", "-"])
    out = json.loads(cap.readouterr().out)
    assert rc == 0 and out["added"] == "review" and out["sha256"] == sha(RECAP_DOC)
    monkeypatch.delenv("SDLC_RUN")
    rc = cli.main(["doc", "list"])
    assert rc == 1 and json.loads(cap.readouterr().err)["error"].startswith("run_not_set")


# --- AC7 ---

def test_ac7_doc_add_once_per_type(demo, cap, monkeypatch):
    res = init(cap)
    rc, out, err = add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    assert rc == 0, err
    got = json.loads(out)
    target = Path(res["out"]) / "docs" / "review.md"
    assert got == {"added": "review", "path": str(target), "sha256": sha(RECAP_DOC)}
    before = sha(target.read_bytes())
    rc, out, err = add(cap, monkeypatch, "review", b"## Recap\nsecond\n", res["root"])
    assert rc != 0 and json.loads(err)["error"] == "doc_exists:review"
    assert sha(target.read_bytes()) == before
    assert os.listdir(Path(res["out"]) / "docs") == ["review.md"]


def test_ac7_unknown_type_lists_types(demo, cap, monkeypatch):
    res = init(cap)
    rc, out, err = add(cap, monkeypatch, "poem", b"x", res["root"])
    msg = json.loads(err)["error"]
    assert rc != 0 and msg.startswith("type_invalid:poem")
    for t in ("review", "acceptance", "demo", "deploy", "implement", "nonreg", "findings", "report"):
        assert t in msg
    assert os.listdir(Path(res["out"]) / "docs") == []


def test_doc_add_from_file(demo, cap, tmp_path):
    res = init(cap)
    src = write(tmp_path, "src/demo.md", b"## Recap\ndemo\n")
    rc, out, err = call(cap, "doc", "add", "demo", src, "--run", res["root"])
    assert rc == 0 and (Path(res["out"]) / "docs" / "demo.md").read_bytes() == b"## Recap\ndemo\n"


# --- AC8 ---

def _published_review(demo, cap, monkeypatch, *finish_args):
    write(demo.story(), "review.md", OLD_REVIEW)
    res = init(cap)
    manifest = Path(res["manifest"]).read_bytes()
    assert add(cap, monkeypatch, "review", RECAP_DOC, res["root"])[0] == 0
    fin = ok(cap, "run", "finish", res["run_uid"], *finish_args)
    return res, manifest, fin


def test_ac8_finish_prepends_round_2_byte_exact(demo, cap, monkeypatch):
    res, _, fin = _published_review(demo, cap, monkeypatch)
    uid = res["run_uid"]
    new = (demo.story() / "review.md").read_bytes()
    first = new.split(b"\n", 1)[0].decode()
    assert re.match(rf"^<!-- round 2 · run {uid} · agent reviewer · ", first)
    assert ROUND_HEADER_RE.fullmatch(first)
    assert new.endswith(OLD_REVIEW)
    assert new == first.encode() + b"\n" + RECAP_DOC + b"\n" + OLD_REVIEW
    assert fin == {"run_uid": uid, "state": "published", "warnings": [],
                   "published": [{"type": "review", "round": 2, "path": f"runs/{uid}/out/docs/review.md"}]}


def test_ac8_trace_at_data_root(demo, cap, monkeypatch):
    res, manifest, fin = _published_review(demo, cap, monkeypatch)
    uid = res["run_uid"]
    trace = demo.data / "runs" / uid
    run = json.loads((trace / "run.json").read_text())
    assert run["state"] == "published" and run["finished_at"] and run["story"] == "DEMO-E-1"
    assert tuple(sorted(run)) == RUN_JSON_KEYS and run["published"] == fin["published"]
    assert (trace / "manifest.json").read_bytes() == manifest
    assert (trace / "out" / "docs" / "review.md").read_bytes() == RECAP_DOC
    assert not (demo.story() / "runs").exists()
    assert sorted(p.relative_to(trace).as_posix() for p in trace.rglob("*") if p.is_file()) == [
        "manifest.json", "out/docs/review.md", "run.json"]


def test_ac8_artifact_linked_and_workspace_removed(demo, cap, monkeypatch):
    res, _, _ = _published_review(demo, cap, monkeypatch)
    got = ok(cap, "get", "DEMO-E-1")
    assert got["artifacts"]["review"] == "DEMO-E/stories/DEMO-E-1/review.md"
    assert not Path(res["root"]).exists()


# --- AC9 ---

def test_ac9_status_sees_published_recap(demo, cap, monkeypatch):
    _published_review(demo, cap, monkeypatch)
    st = ok(cap, "status", "DEMO-E-1")
    arts = st["tickets"][0]["artifacts"]
    review = next(a for a in arts if a["kind"] == "review")
    assert review["produced"] is True and "OK" in review["recap"]


# --- AC10 ---

def test_ac10_in_modified_rejects_nothing_published(demo, cap, monkeypatch):
    write(demo.story(), "review.md", OLD_REVIEW)
    commit_all(demo.data)
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    with open(Path(res["in"]) / "feature" / "atelier" / "prd.md", "ab") as f:
        f.write(b"x\n")
    before = (sha((demo.story() / "review.md").read_bytes()), porcelain(demo.data))
    rc, out, err = call(cap, "run", "finish", res["run_uid"])
    got = json.loads(out)
    assert rc == 1 and got["state"] == "rejected" and got["published"] == []
    assert got["reasons"] == ["in_modified:feature/atelier/prd.md"] and "prd.md" in got["reasons"][0]
    assert (sha((demo.story() / "review.md").read_bytes()), porcelain(demo.data)) == before
    assert Path(res["root"]).is_dir()
    run = json.loads((Path(res["root"]) / "run.json").read_text())
    assert run["state"] == "rejected" and run["reasons"] == got["reasons"]


def test_manifest_rewrite_detected_by_seal(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    prd = Path(res["in"]) / "feature" / "atelier" / "prd.md"
    prd.write_bytes(b"forged\n")
    man_path = Path(res["manifest"])
    man = json.loads(man_path.read_text())
    for e in man["files"]:
        if e["key"] == "feature/atelier/prd.md":
            e["sha256"], e["size"] = sha(b"forged\n"), 7
    man_path.write_text(json.dumps(man, indent=2) + "\n")
    rc, out, _ = call(cap, "run", "finish", res["run_uid"])
    assert rc == 1 and json.loads(out)["reasons"] == ["in_modified:manifest.json"]
    assert not (demo.data / "runs").exists()


def test_in_file_removed_or_added_rejected(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    (Path(res["in"]) / "brain" / "index.md").unlink()
    write(Path(res["in"]), "feature/extra.md", b"x")
    os.symlink("/", Path(res["in"]) / "brain" / "link")
    rc, out, _ = call(cap, "run", "finish", res["run_uid"])
    assert rc == 1 and json.loads(out)["reasons"] == [
        "in_modified:brain/index.md", "in_modified:brain/link", "in_modified:feature/extra.md"]


# --- AC11 ---

def _finish_rejected(demo, cap, uid):
    rc, out, _ = call(cap, "run", "finish", uid)
    assert rc == 1
    assert porcelain(demo.data, "DEMO-E", "runs") == ""
    return json.loads(out)


def test_ac11_unexpected_file_docs(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    write(Path(res["out"]), "docs/notes.txt", b"x")
    write(Path(res["out"]), "extra/y.md", b"y")
    got = _finish_rejected(demo, cap, res["run_uid"])
    assert got["reasons"] == ["unexpected_file:docs/notes.txt", "unexpected_file:extra/y.md"]


def test_ac11_too_large(demo, cap, monkeypatch):
    res = init(cap)
    assert add(cap, monkeypatch, "review", b"## Recap\n" + b"x" * (2 * 1024 * 1024), res["root"])[0] == 0
    got = _finish_rejected(demo, cap, res["run_uid"])
    assert got["reasons"] == ["too_large:docs/review.md"]


def test_ac11_agent_bundle_in_out_git_rejected(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    write(Path(res["out"]), "git/x.bundle", b"bundle")
    got = _finish_rejected(demo, cap, res["run_uid"])
    assert "unexpected_file:git/x.bundle" in got["reasons"]


def test_symlink_in_out_rejected(demo, cap):
    res = init(cap)
    target = write(demo.tmp, "elsewhere/doc.md", RECAP_DOC)
    os.symlink(target, Path(res["out"]) / "docs" / "review.md")
    os.symlink("/", Path(res["out"]) / "sources" / "root")
    got = _finish_rejected(demo, cap, res["run_uid"])
    assert got["reasons"] == ["unexpected_file:docs/review.md", "unexpected_file:sources/root"]


# --- AC12 ---

def test_ac12_second_finish_already_published(demo, cap, monkeypatch):
    res, _, _ = _published_review(demo, cap, monkeypatch, "--keep")
    assert Path(res["root"]).is_dir()
    review = (demo.story() / "review.md").read_bytes()
    assert ok(cap, "run", "finish", res["run_uid"]) == {"run_uid": res["run_uid"], "already": "published"}
    assert ok(cap, "run", "finish", res["root"]) == {"run_uid": res["run_uid"], "already": "published"}
    assert (demo.story() / "review.md").read_bytes() == review
    assert len(re.findall(rb"(?m)^<!-- round", review)) == 2


def test_ac12_warnings_no_recap_sources(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", b"# no recap here\n", res["root"])
    write(Path(res["out"]), "sources/logs/a.log", b"log")
    fin = ok(cap, "run", "finish", res["run_uid"])
    assert fin["state"] == "published" and sorted(fin["warnings"]) == ["no_recap", "sources_not_published"]
    assert not (demo.data / "runs" / res["run_uid"] / "out" / "sources").exists()


def test_ac12_scratch_never_published(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    write(Path(res["scratch"]), "draft-zq81.md", b"scratch-content-zq81\n")
    write(Path(res["code"]), "code-zq81.txt", b"code-content-zq81\n")
    ok(cap, "run", "finish", res["run_uid"])
    for p in demo.data.rglob("*"):
        if ".git" in p.parts:
            continue
        assert "zq81" not in p.name
        if p.is_file():
            assert b"zq81" not in p.read_bytes()


# --- AC13 ---

def test_ac13_list_and_clean(demo, cap, monkeypatch):
    pub, _, _ = _published_review(demo, cap, monkeypatch)
    a, b = init(cap), init(cap)
    lst = ok(cap, "run", "list", "DEMO-E-1")
    assert len([r for r in lst if r["state"] == "open"]) == 2
    assert len([r for r in lst if r["state"] == "published"]) >= 1
    assert [r["run_uid"] for r in lst] == sorted(r["run_uid"] for r in lst)
    assert all(set(r) == {"run_uid", "story", "mission", "agent", "state", "created_at", "root"} for r in lst)
    published = next(r for r in lst if r["run_uid"] == pub["run_uid"])
    assert published["root"] is None and published["agent"] == "reviewer"
    before = porcelain(demo.data)
    assert ok(cap, "run", "clean", a["run_uid"]) == {"run_uid": a["run_uid"], "cleaned": True}
    assert porcelain(demo.data) == before and not Path(a["root"]).exists()
    lst = ok(cap, "run", "list", "DEMO-E-1")
    assert [r["run_uid"] for r in lst if r["state"] == "open"] == [b["run_uid"]]
    assert ok(cap, "run", "list", "DEMO-E-2") == []
    assert ok(cap, "run", "clean", b["root"])["cleaned"] is True
    rc, _, err = call(cap, "run", "clean", a["run_uid"])
    assert rc == 1 and json.loads(err)["error"] == f"run_unknown:{a['run_uid']}"


def test_list_ignores_bubble_entries_and_partial(demo, cap):
    res = init(cap)
    base = demo.root_base / "DEMO-E-1"
    (base / ".claude").mkdir()
    (base / "scratch").mkdir()
    (base / "README.md").write_text("# bubble\n")
    partial = base / ".20260101-000000-abcdef.partial"
    partial.mkdir()
    (partial / "run.json").write_text(json.dumps({"run_uid": "20260101-000000-abcdef", "state": "open"}))
    lst = ok(cap, "run", "list")
    assert [r["run_uid"] for r in lst] == [res["run_uid"]] and lst[0]["root"] == res["root"]


def test_finish_unknown_run(demo, cap):
    rc, _, err = call(cap, "run", "finish", "20260101-000000-abcdef")
    assert rc == 1 and json.loads(err)["error"] == "run_unknown:20260101-000000-abcdef"


# --- AC15 ---

def test_ac15_brain_default_main_commit_only(demo, cap):
    c2 = _brain_c2(demo)
    write(demo.brain, "adr/0001.md", b"# ADR 1 modified, not committed\n")
    write(demo.brain, "draft.md", b"# draft\n")
    res = init(cap)
    in_brain = Path(res["in"]) / "brain"
    assert (in_brain / "index.md").read_bytes() == git_show(demo.brain, f"{c2}:index.md")
    assert (in_brain / "adr" / "0001.md").read_bytes() == git_show(demo.brain, f"{c2}:adr/0001.md") == BRAIN_ADR
    assert not (in_brain / "draft.md").exists()
    man = json.loads(Path(res["manifest"]).read_text())
    assert man["brain"] == {"ref": "main", "commit": c2}


def _brain_c2(demo) -> str:
    git(demo.brain, *GIT_ID, "tag", "v1", demo.c1)
    write(demo.brain, "index.md", b"# Index C2\n")
    return commit_all(demo.brain, "C2")


def test_ac15_brain_ref_tag(demo, cap):
    _brain_c2(demo)
    demo.set_config(brainRef="v1")
    res = init(cap)
    assert (Path(res["in"]) / "brain" / "index.md").read_bytes() == BRAIN_INDEX_C1
    assert res["brain"]["ref"] == "v1" and res["brain"]["commit"] == demo.c1 and res["brain"]["from"] == "tag"
    assert json.loads(Path(res["manifest"]).read_text())["brain"] == {"ref": "v1", "commit": demo.c1}


def test_ac15_brain_ref_unresolved_warns(demo, cap):
    demo.set_config(brainRef="v9")
    res = init(cap)
    assert [p for p in (Path(res["in"]) / "brain").rglob("*") if p.is_file()] == []
    assert res["warnings"] == ["brain_ref_unresolved"]
    assert json.loads(Path(res["manifest"]).read_text())["brain"] == {"ref": "v9", "commit": None}


def test_ac15_origin_first_no_fetch(demo, cap):
    c2 = _brain_c2(demo)
    bare = demo.tmp / "brain.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(demo.brain), str(bare)], check=True, capture_output=True)
    b2 = demo.tmp / "b2"
    subprocess.run(["git", "clone", "-q", str(bare), str(b2)], check=True, capture_output=True)
    git(b2, "reset", "-q", "--hard", demo.c1)
    demo.set_config(brain=str(b2))
    res = init(cap)
    assert res["brain"]["commit"] == c2 and res["brain"]["from"] == "origin"
    assert git(b2, "rev-parse", "main") == demo.c1
    assert (Path(res["in"]) / "brain" / "index.md").read_bytes() == b"# Index C2\n"


def test_ac15_master_default(demo, cap):
    m = demo.tmp / "brain-master"
    m.mkdir()
    git(m, "init", "-q", "-b", "master")
    write(m, "index.md", b"# M\n")
    commit_all(m)
    demo.set_config(brain=str(m))
    res = init(cap)
    assert res["brain"]["ref"] == "master" and res["brain"]["files"] == 1


def test_ac15_brain_not_git_fallback(demo, cap):
    plain = demo.tmp / "plain-brain"
    write(plain, "index.md", b"# plain\n")
    write(plain, "sub/n.md", b"# n\n")
    for skipped in (".hidden/x.md", "node_modules/x.md", "_toDelete/x.md", "_wt/x.md", "_agentws/x.md",
                    ".claude/x.md", "hooks/x.md", "logo.png"):
        write(plain, skipped, b"skip\n")
    demo.set_config(brain=str(plain))
    res = init(cap)
    in_brain = Path(res["in"]) / "brain"
    assert sorted(p.relative_to(in_brain).as_posix() for p in in_brain.rglob("*") if p.is_file()) == [
        "index.md", "sub/n.md"]
    assert res["warnings"] == ["brain_not_git"]
    man = json.loads(Path(res["manifest"]).read_text())
    assert man["brain"] == {"ref": None, "commit": None}
    brain_entries = [e for e in man["files"] if e["key"].startswith("brain/")]
    assert all(e["version"] is None for e in brain_entries)
    assert not any(k.startswith("brain/") for k in man["dirty"])


def test_brain_missing_warns(demo, cap):
    demo.set_config(brain=str(demo.tmp / "nowhere"))
    res = init(cap)
    assert res["warnings"] == ["brain_missing"] and res["brain"]["files"] == 0
    cfg = dict(demo.config)
    cfg.pop("brain")
    (demo.data / "sdlc.config.json").write_text(json.dumps(cfg))
    assert init(cap)["warnings"] == ["brain_missing"]


def test_brain_map_invalid_commit_and_worktree(demo, cap):
    write(demo.brain, "brain-map.yaml", b"bogus: [x]\n")
    commit_all(demo.brain, "bad map")
    res = init(cap)
    assert res["warnings"] == ["brain_map_invalid"]
    assert [p for p in (Path(res["in"]) / "brain").rglob("*") if p.is_file()] == []
    plain = demo.tmp / "plain-brain"
    write(plain, "index.md", b"# plain\n")
    write(plain, "brain-map.yaml", b"exclude:\n  - {broken\nnot yaml at all\n")
    demo.set_config(brain=str(plain))
    res = init(cap)
    assert res["warnings"] == ["brain_map_invalid", "brain_not_git"]
    assert [p for p in (Path(res["in"]) / "brain").rglob("*") if p.is_file()] == []


def test_brain_map_excludes_applied(demo, cap):
    write(demo.brain, "brain-map.yaml", b"exclude:\n  - adr/\n")
    commit_all(demo.brain, "map")
    res = init(cap)
    in_brain = Path(res["in"]) / "brain"
    assert (in_brain / "index.md").is_file() and not (in_brain / "adr").exists()


# --- AC16 ---

def _neighbour_run(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    in_dir = Path(res["in"])
    write(in_dir, "repos/web/app.py", b"print('x')\n")
    steps = write(in_dir, "repro/steps.md", b"# steps\n")
    man_path = Path(res["manifest"])
    man = json.loads(man_path.read_text())
    man["files"].append({"key": "repos/web", "commit": "a" * 40, "role": "neighbour"})
    man["files"].append({"key": "repro/steps.md", "version": None, "sha256": sha(steps.read_bytes()),
                         "size": steps.stat().st_size, "origin": "repro/steps.md"})
    data = (json.dumps(man, indent=2, ensure_ascii=False) + "\n").encode()
    man_path.write_bytes(data)
    seal_path = Path(res["root"]) / "seal.json"
    seal = json.loads(seal_path.read_text())
    seal["manifest_sha256"] = sha(data)
    seal_path.write_text(json.dumps(seal))
    return res


def test_ac16_neighbour_subtree_delegated(demo, cap, monkeypatch):
    res = _neighbour_run(demo, cap, monkeypatch)
    write(Path(res["in"]), "repos/web/app.py", b"changed by the agent, checked by git elsewhere\n")
    write(Path(res["in"]), "repos/web/new.txt", b"new\n")
    rc, out, _ = call(cap, "run", "finish", res["run_uid"], "--keep")
    assert rc == 0 and json.loads(out)["state"] == "published"
    assert (demo.data / "runs" / res["run_uid"] / "manifest.json").read_bytes() == Path(res["manifest"]).read_bytes()
    lst = ok(cap, "doc", "list", "--run", res["root"])
    assert "repro/steps.md" in [d["key"] for d in lst] and "repos/web" not in [d["key"] for d in lst]
    rc, out, _ = call(cap, "doc", "read", "repro/steps", "--run", res["root"])
    assert rc == 0 and out == b"# steps\n"


def test_ac16_repro_modified_rejected(demo, cap, monkeypatch):
    res = _neighbour_run(demo, cap, monkeypatch)
    write(Path(res["in"]), "repro/steps.md", b"# steps, edited\n")
    before = porcelain(demo.data)
    rc, out, _ = call(cap, "run", "finish", res["run_uid"], "--keep")
    assert rc == 1 and "in_modified:repro/steps.md" in json.loads(out)["reasons"]
    assert porcelain(demo.data) == before


def test_ac16_unregistered_repos_dir_rejected(demo, cap, monkeypatch):
    res = _neighbour_run(demo, cap, monkeypatch)
    write(Path(res["in"]), "repos/other/x", b"x\n")
    before = porcelain(demo.data)
    rc, out, _ = call(cap, "run", "finish", res["run_uid"], "--keep")
    assert rc == 1 and json.loads(out)["reasons"] == ["in_modified:repos/other/x"]
    assert porcelain(demo.data) == before


# --- AC17 ---

def test_ac17_nonreg_and_implement_round_1(demo, cap, monkeypatch):
    old_impl = b"# DEMO-E-1 implement\n\nWritten by the interactive command.\n"
    write(demo.story(), "implement.md", old_impl)
    r1 = init(cap, "DEMO-E-1", "--agent", "nonreg-runner")
    assert add(cap, monkeypatch, "nonreg", b"## Recap\nall green\n", r1["root"])[0] == 0
    f1 = ok(cap, "run", "finish", r1["run_uid"])
    assert f1["published"][0]["type"] == "nonreg" and f1["published"][0]["round"] == 1
    head = (demo.story() / "nonreg.md").read_bytes().split(b"\n", 1)[0].decode()
    assert re.match(rf"^<!-- round 1 · run {r1['run_uid']} · agent nonreg-runner · ", head)
    r2 = init(cap, "DEMO-E-1", "--agent", "dev")
    assert add(cap, monkeypatch, "implement", b"## Recap\ndone\n", r2["root"])[0] == 0
    f2 = ok(cap, "run", "finish", r2["run_uid"])
    assert f2["published"][0]["type"] == "implement" and f2["published"][0]["round"] == 1
    impl = (demo.story() / "implement.md").read_bytes()
    assert impl.startswith(b"<!-- round 1 \xc2\xb7 run " + r2["run_uid"].encode()) and impl.endswith(old_impl)


def _headers(n: int) -> bytes:
    return b"".join(f"<!-- round {i} · run 20260101-00000{i}-abcdef · agent reviewer · "
                    f"2026-01-01T00:00:0{i}Z -->\n## Recap\nround {i}\n\n".encode() for i in range(n, 0, -1))


@pytest.mark.parametrize("existing,expected", [(None, 1), (0, 1), (1, 2), (3, 4)])
def test_round_numbering_0_1_3_existing(demo, cap, monkeypatch, existing, expected):
    if existing is not None:
        write(demo.story(), "review.md", b"# DEMO-E-1 review\n" if existing == 0 else _headers(existing))
    old = (demo.story() / "review.md").read_bytes() if existing is not None else b""
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    fin = ok(cap, "run", "finish", res["run_uid"])
    assert fin["published"][0]["round"] == expected
    new = (demo.story() / "review.md").read_bytes()
    assert new.endswith(old)
    assert ROUND_HEADER_RE.fullmatch(new.split(b"\n", 1)[0].decode()).group(1) == str(expected)


# --- AC18 ---

def _mission(demo):
    write(demo.data, "missions/inc-042/brief.md", b"# Incident 42\n\nUsers cannot log in.\n")
    write(demo.data, "missions/inc-042/sources/logs.md", b"# logs\n")
    write(demo.data, "missions/inc-042/sources/deep/trace.md", b"# trace\n")
    write(demo.data, "missions/inc-042/sources/dump.bin", b"\x00")
    commit_all(demo.data, "mission")


def test_ac18_mission_scope_tree_and_read(demo, cap):
    _mission(demo)
    res = ok(cap, "run", "init", "--mission", "inc-042", "--agent", "investigator")
    root = Path(res["root"])
    assert root.parent == demo.root_base / "inc-042"
    assert (root / "in" / "mission" / "sources" / "logs.md").is_file()
    assert (root / "in" / "mission" / "sources" / "deep" / "trace.md").is_file()
    assert not (root / "in" / "mission" / "sources" / "dump.bin").exists()
    assert not (root / "in" / "feature").exists()
    run = json.loads((root / "run.json").read_text())
    assert (run["mission"], run["story"], run["feature"]) == ("inc-042", None, None)
    rc, out, _ = call(cap, "doc", "read", "brief", "--run", root)
    assert rc == 0 and out == (demo.data / "missions" / "inc-042" / "brief.md").read_bytes()
    rc, out, _ = call(cap, "doc", "read", "mission/sources/deep/trace", "--run", root)
    assert rc == 0 and out == b"# trace\n"
    keys = [d["key"] for d in ok(cap, "doc", "list", "--run", root)]
    assert "brief" in keys and "mission/sources/logs" in keys


def test_ac18_mission_rounds_from_traces(demo, cap, monkeypatch):
    _mission(demo)
    rounds = []
    for _ in range(2):
        res = ok(cap, "run", "init", "--mission", "inc-042", "--agent", "investigator")
        add(cap, monkeypatch, "findings", b"## Recap\nroot cause\n", res["root"])
        fin = ok(cap, "run", "finish", res["run_uid"])
        rounds.append(fin["published"][0]["round"])
        assert (demo.data / "runs" / res["run_uid"] / "out" / "docs" / "findings.md").is_file()
    assert rounds == [1, 2]
    changed = [line[3:] for line in porcelain(demo.data).splitlines()]
    assert changed and all(p.startswith("runs/") for p in changed)
    lst = ok(cap, "run", "list", "--mission", "inc-042")
    assert [r["state"] for r in lst] == ["published", "published"]


def test_ac18_unknown_mission_creates_nothing(demo, cap):
    rc, _, err = call(cap, "run", "init", "--mission", "inc-999", "--agent", "investigator")
    assert rc != 0 and json.loads(err)["error"] == "mission_unknown:inc-999"
    assert not (demo.root_base / "inc-999").exists()


# --- safety ---

def test_datarepo_git_read_only(demo, cap, monkeypatch):
    count = git(demo.data, "rev-list", "--count", "HEAD")
    seen: list[list[str]] = []
    real_run = subprocess.run

    def spy(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd and cmd[0] == "git" and str(demo.data) in cmd:
            i = cmd.index("-C") + 2
            while cmd[i].startswith("-"):
                i += 1
            seen.append(cmd)
            assert "--no-optional-locks" in cmd
            assert cmd[i] in {"rev-parse", "ls-files", "diff", "log"}, cmd
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    ok(cap, "run", "finish", res["run_uid"])
    monkeypatch.setattr(subprocess, "run", real_run)
    assert seen
    assert git(demo.data, "rev-list", "--count", "HEAD") == count


def test_scratch_and_code_never_walked(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    for d in (Path(res["scratch"]), Path(res["code"])):
        locked = write(d, "locked.md", b"secret\n")
        os.chmod(locked, 0)
        os.symlink("/", d / "root-link")
        os.mkfifo(d / "fifo")
    fin = ok(cap, "run", "finish", res["run_uid"])
    assert fin["state"] == "published" and fin["warnings"] == []
    assert not Path(res["root"]).exists()


# --- run identity sealed (post-review PM-027) and checked bytes published (PM-028) ---

def _tamper_run_json(res: dict, **fields) -> None:
    rj = Path(res["root"]) / "run.json"
    run = json.loads(rj.read_text())
    run.update(fields)
    rj.write_text(json.dumps(run))


def _assert_refused_nothing_published(demo, res, rc, out, err, *fields):
    assert rc == 1 and out == b""
    error = json.loads(err)["error"]
    assert error.startswith("run_invalid:") and all(f in error for f in fields), error
    assert not (demo.data / "runs").exists()
    assert not (demo.story("DEMO-E-1") / "review.md").exists()
    assert not (demo.story("DEMO-E-2") / "review.md").exists()
    assert Path(res["root"]).is_dir()


def test_seal_holds_run_identity(demo, cap):
    res = init(cap)
    seal = json.loads((Path(res["root"]) / "seal.json").read_text())
    run = json.loads((Path(res["root"]) / "run.json").read_text())
    assert set(seal) == {"manifest_sha256", "settings_sha256", "run"}
    assert seal["run"] == {k: run[k] for k in ("run_uid", "agent", "phase", "feature", "story", "mission",
                                               "ticket")}


def test_run_json_agent_header_injection_refused(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    _tamper_run_json(res, agent="x · 2026 -->\n<!-- round 99 · run 20260101-000000-abcdef · agent evil · z -->")
    rc, out, err = call(cap, "run", "finish", res["run_uid"])
    _assert_refused_nothing_published(demo, res, rc, out, err, "agent")


def test_run_json_story_redirect_refused(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    _tamper_run_json(res, story="DEMO-E-2")
    rc, out, err = call(cap, "run", "finish", res["run_uid"])
    _assert_refused_nothing_published(demo, res, rc, out, err, "story")


@pytest.mark.parametrize("fields", [{"agent": "dev"}, {"phase": "implement"}, {"feature": "DEMO-X"},
                                    {"story": None, "mission": "inc-1"}, {"ticket": "T-1"}])
def test_run_json_identity_tampering_refused(demo, cap, monkeypatch, fields):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    _tamper_run_json(res, **fields)
    rc, out, err = call(cap, "run", "finish", res["run_uid"])
    _assert_refused_nothing_published(demo, res, rc, out, err, *fields)
    _tamper_run_json(res, **{k: v for k, v in json.loads((Path(res["root"]) / "seal.json").read_text())
                             ["run"].items()})
    assert ok(cap, "run", "finish", res["run_uid"])["state"] == "published"


def test_seal_identity_forged_with_run_json_refused_by_manifest_scope(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    seal_path = Path(res["root"]) / "seal.json"
    seal = json.loads(seal_path.read_text())
    seal["run"]["story"] = "DEMO-E-2"
    seal_path.write_text(json.dumps(seal))
    _tamper_run_json(res, story="DEMO-E-2")
    rc, out, err = call(cap, "run", "finish", res["run_uid"])
    _assert_refused_nothing_published(demo, res, rc, out, err, "scope")


def test_seal_without_identity_refused(demo, cap, monkeypatch):
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    seal_path = Path(res["root"]) / "seal.json"
    seal = json.loads(seal_path.read_text())
    del seal["run"]
    seal_path.write_text(json.dumps(seal))
    rc, out, err = call(cap, "run", "finish", res["run_uid"])
    _assert_refused_nothing_published(demo, res, rc, out, err, "seal.json")


def test_finish_publishes_checked_bytes_not_a_later_swap(demo, cap, monkeypatch):
    from sdlc.runws import controls
    res = init(cap)
    add(cap, monkeypatch, "review", RECAP_DOC, res["root"])
    secret = write(demo.tmp, "outside/secret.md", b"## Recap\nsecret outside the workspace\n")
    doc = Path(res["out"]) / "docs" / "review.md"
    manifest = Path(res["manifest"])
    manifest_bytes = manifest.read_bytes()
    real_check = controls.check

    def check_then_swap(*a, **kw):
        result = real_check(*a, **kw)
        doc.unlink()
        os.symlink(secret, doc)                # swapped after the checks, before publication
        manifest.write_bytes(b'{"forged": true}\n')
        return result

    monkeypatch.setattr(controls, "check", check_then_swap)
    fin = ok(cap, "run", "finish", res["run_uid"])
    assert fin["state"] == "published"
    published = (demo.story("DEMO-E-1") / "review.md").read_bytes()
    assert published.endswith(RECAP_DOC) and b"secret" not in published
    assert (demo.data / "runs" / res["run_uid"] / "manifest.json").read_bytes() == manifest_bytes
