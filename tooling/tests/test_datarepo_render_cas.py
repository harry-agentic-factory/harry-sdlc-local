"""Local rendering of a round into `<STORY>/<type>.md` against a concurrent writer (AISDLC-RUNWS-13, AC13).

The interference (a human or a session editing the file with its own tools) is injected between the read
and the replacement by wrapping `datarepo._replace_if_unchanged`: the wrapper writes to the target, then
lets the real compare-and-swap run.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from sdlc.runws import datarepo
from test_run_workspace import OLD_REVIEW, RECAP_DOC, add, call, init, make_demo, ok, write

NOTE = b"note humaine\n"
REAL_CAS = datarepo._replace_if_unchanged


@pytest.fixture
def demo(tmp_path, monkeypatch):
    return make_demo(tmp_path, monkeypatch)


@pytest.fixture
def cap(capsysbinary):
    return capsysbinary


def interfere(monkeypatch, target: Path, times: int) -> list[int]:
    """Append NOTE to `target` before each of the first `times` compare-and-swap attempts."""
    real = REAL_CAS
    seen = [0]

    def wrapper(path, expected, data):
        if Path(path) == target and seen[0] < times:
            seen[0] += 1
            with open(path, "ab") as f:
                f.write(NOTE)
        return real(path, expected, data)

    monkeypatch.setattr(datarepo, "_replace_if_unchanged", wrapper)
    return seen


def leftovers(folder: Path) -> list[str]:
    return sorted(n for n in os.listdir(folder) if n.startswith("."))


def test_one_interference_redoes_and_keeps_both(demo, cap, monkeypatch):
    target = write(demo.story(), "review.md", OLD_REVIEW)
    res = init(cap)
    assert add(cap, monkeypatch, "review", RECAP_DOC, res["root"])[0] == 0
    seen = interfere(monkeypatch, target, 1)
    fin = ok(cap, "run", "finish", res["run_uid"])
    assert seen[0] == 1
    assert fin["state"] == "published" and fin["published"][0]["round"] == 2
    new = target.read_bytes()
    first = new.split(b"\n", 1)[0].decode()
    assert re.match(rf"^<!-- round 2 · run {res['run_uid']} · agent reviewer · ", first)
    assert new == first.encode() + b"\n" + RECAP_DOC + b"\n" + OLD_REVIEW + NOTE
    assert leftovers(target.parent) == []


def test_four_interferences_put_conflict_then_replay_publishes_once(demo, cap, monkeypatch):
    target = write(demo.story(), "review.md", OLD_REVIEW)
    res = init(cap)
    uid = res["run_uid"]
    assert add(cap, monkeypatch, "review", RECAP_DOC, res["root"])[0] == 0
    seen = interfere(monkeypatch, target, 4)
    rc, out, err = call(cap, "run", "finish", uid)
    assert rc == 1 and out == b""
    assert json.loads(err)["error"] == "put_conflict:DEMO-E/stories/DEMO-E-1/review.md"
    assert seen[0] == datarepo.RENDER_ATTEMPTS == 3
    assert target.read_bytes() == OLD_REVIEW + NOTE * 3          # nothing rendered, the edits kept
    assert leftovers(target.parent) == []
    assert json.loads((Path(res["root"]) / "run.json").read_text())["state"] == "open"
    assert not (demo.data / "runs" / uid / "run.json").exists()   # no final trace
    monkeypatch.setattr(datarepo, "_replace_if_unchanged", REAL_CAS)   # the concurrent writer is gone
    fin = ok(cap, "run", "finish", uid)
    assert fin["state"] == "published" and fin["published"][0]["round"] == 2
    text = target.read_bytes()
    assert len(re.findall(rb"(?m)^<!-- round 2 \xc2\xb7", text)) == 1
    assert text.endswith(OLD_REVIEW + NOTE * 3)
    assert ok(cap, "run", "finish", uid) == {"run_uid": uid, "already": "published"}
    assert target.read_bytes() == text


def test_no_interference_unchanged_rendering(demo, cap, monkeypatch):
    target = write(demo.story(), "review.md", OLD_REVIEW)
    res = init(cap)
    assert add(cap, monkeypatch, "review", RECAP_DOC, res["root"])[0] == 0
    seen = interfere(monkeypatch, target, 0)
    ok(cap, "run", "finish", res["run_uid"])
    assert seen[0] == 0
    new = target.read_bytes()
    assert new == new.split(b"\n", 1)[0] + b"\n" + RECAP_DOC + b"\n" + OLD_REVIEW


def test_file_created_meanwhile_is_kept(demo, cap, monkeypatch):
    target = demo.story() / "review.md"
    assert not target.exists()
    res = init(cap)
    assert add(cap, monkeypatch, "review", RECAP_DOC, res["root"])[0] == 0
    seen = interfere(monkeypatch, target, 1)
    fin = ok(cap, "run", "finish", res["run_uid"])
    assert seen[0] == 1 and fin["published"][0]["round"] == 1
    new = target.read_bytes()
    assert new == new.split(b"\n", 1)[0] + b"\n" + RECAP_DOC + b"\n" + NOTE


def test_replace_if_unchanged_helper(tmp_path):
    p = tmp_path / "doc.md"
    assert datarepo._replace_if_unchanged(p, None, b"a") and p.read_bytes() == b"a"
    assert not datarepo._replace_if_unchanged(p, None, b"b") and p.read_bytes() == b"a"
    assert not datarepo._replace_if_unchanged(p, b"x", b"b") and p.read_bytes() == b"a"
    assert datarepo._replace_if_unchanged(p, b"a", b"b") and p.read_bytes() == b"b"
    os.unlink(p)
    os.symlink(tmp_path / "elsewhere", p)
    assert not datarepo._replace_if_unchanged(p, None, b"c") and os.path.islink(p)
    assert leftovers(tmp_path) == []
