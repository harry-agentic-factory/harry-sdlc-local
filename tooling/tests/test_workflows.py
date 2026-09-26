"""Static checks of .github/workflows/ci.yml and release.yml (line parser, stdlib only: no yq, no act)."""
from __future__ import annotations

import re
from pathlib import Path

import enginefx as fx

WORKFLOWS = fx.ENGINE_ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
RELEASE = WORKFLOWS / "release.yml"
ALLOWED_ACTIONS = ("actions/checkout", "actions/setup-python", "actions/setup-node", "astral-sh/setup-uv")


def lines(path: Path) -> list[str]:
    return [l for l in path.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]


def top_block(path: Path, key: str) -> list[str]:
    """Lines of the top-level mapping `key:` (up to the next top-level key)."""
    out, inside = [], False
    for l in lines(path):
        if re.match(r"^\S", l):
            inside = l.startswith(f"{key}:")
            if inside and l.strip() != f"{key}:":
                out.append(l.split(":", 1)[1].strip())
            continue
        if inside:
            out.append(l.strip())
    return out


def steps(path: Path) -> list[dict[str, str]]:
    """Steps in order, as {'name', 'uses', 'run'}; a `run: |` block is joined with newlines."""
    raw = path.read_text().splitlines()
    result: list[dict[str, str]] = []
    i = 0
    while i < len(raw):
        m = re.match(r"^(\s*)- (.*)$", raw[i])
        if not m or ":" not in m.group(2):
            i += 1
            continue
        indent = len(m.group(1))
        block = [" " * (indent + 2) + m.group(2)]
        i += 1
        while i < len(raw) and (not raw[i].strip() or len(raw[i]) - len(raw[i].lstrip()) > indent):
            block.append(raw[i])
            i += 1
        step: dict[str, str] = {}
        j = 0
        while j < len(block):
            km = re.match(rf"^ {{{indent + 2}}}(name|uses|run):\s*(.*)$", block[j])
            j += 1
            if not km:
                continue
            key, value = km.group(1), km.group(2)
            if key == "run" and value == "|":
                body = []
                while j < len(block) and (not block[j].strip() or
                                          len(block[j]) - len(block[j].lstrip()) > indent + 2):
                    body.append(block[j].strip())
                    j += 1
                value = "\n".join(body).strip()
            step[key] = value
        if step:
            result.append(step)
    return result


def runs(path: Path) -> list[str]:
    return [s["run"] for s in steps(path) if "run" in s]


def first_index(items: list[str], needle: str) -> int:
    for i, item in enumerate(items):
        if needle in item:
            return i
    raise AssertionError(f"{needle!r} not found in {items}")


def test_ac4_release_trigger_tags_only():
    on = top_block(RELEASE, "on")
    assert on == ["push:", 'tags: ["v*"]'], on


def test_ac4_release_order():
    r = runs(RELEASE)
    order = ["scripts/check-tag-version.sh", "git cat-file -t", "merge-base --is-ancestor",
             "scripts/changelog-section.sh", "-m pytest", "uv build", "scripts/wheel-smoke.sh", "gh release create"]
    idx = [first_index(r, n) for n in order]
    assert idx == sorted(idx), dict(zip(order, idx))
    assert idx[1] < idx[3]  # annotated and on main before anything else is read
    assert "gh release create" in r[-1] and "--verify-tag" in r[-1] and "--notes-file" in r[-1]
    assert sum("gh release" in x for x in r) == 1


def test_release_permissions_scoped():
    assert top_block(RELEASE, "permissions") == ["{}"]
    text = RELEASE.read_text()
    assert text.count("contents: write") == 1
    job = text.split("\njobs:", 1)[1]
    assert re.search(r"^    permissions:\n      contents: write$", job, re.M)
    assert top_block(CI, "permissions") == ["contents: read"]


def test_ci_triggers_and_matrix():
    on = top_block(CI, "on")
    assert on == ["pull_request:", 'branches: [main, "epic/**"]', "push:", 'branches: [main, "epic/**"]'], on
    text = CI.read_text()
    assert 'python-version: ["3.11", "3.12"]' in text
    r = runs(CI)
    for needle in ("pytest", "uv build", "scripts/wheel-smoke.sh", "pip install pytest"):
        first_index(r, needle)
    assert first_index(r, "-m pytest") < first_index(r, "uv build") < first_index(r, "wheel-smoke.sh")


def test_same_test_environment_in_both_workflows():
    for wf in (CI, RELEASE):
        text = wf.read_text()
        assert 'SDLC_REQUIRE_NODE: "1"' in text, wf
        assert "actions/setup-node@" in text, wf
        assert "git config --global user.name ci" in text and "init.defaultBranch main" in text, wf
        assert "python -m pip install pytest" in text, wf
    assert 'python-version: "3.11"' in RELEASE.read_text()


def test_workflows_only_github_token():
    for wf in (CI, RELEASE):
        text = wf.read_text()
        assert set(re.findall(r"secrets\.\w+", text)) <= {"secrets.GITHUB_TOKEN"}, wf
        assert not re.search(r"pypi|twine|gh-action-pypi-publish", text, re.I), wf
    assert "GH_TOKEN: ${{ github.token }}" in RELEASE.read_text()


def test_actions_pinned_by_sha():
    for wf in (CI, RELEASE):
        uses = [s["uses"] for s in steps(wf) if "uses" in s]
        assert uses, wf
        for u in uses:
            m = re.fullmatch(r"([\w.-]+/[\w.-]+)@([0-9a-f]{40}) # (v\d+\.\d+\.\d+)", u)
            assert m, u
            assert m.group(1) in ALLOWED_ACTIONS, u


def test_same_check_script_in_release_and_install():
    users = [p.name for p in (RELEASE, fx.INSTALL_SH) if "check-tag-version.sh" in p.read_text()]
    assert users == ["release.yml", "install.sh"]
    assert "check-tag-version.sh" not in CI.read_text()


def test_ci_local_mirrors_the_workflow_sequence():
    text = (fx.SCRIPTS / "ci-local.sh").read_text().split("set -euo pipefail", 1)[1]  # code, not the header
    order = ["check-tag-version.sh", "git cat-file -t", "changelog-section.sh", "-m pytest", "uv build",
             "wheel-smoke.sh", "gh release create"]
    idx = [text.index(n) for n in order]
    assert idx == sorted(idx)
    assert 'echo "gh release create' in text  # printed, never executed
