"""Release scripts: check-tag-version.sh (AC4), changelog-section.sh, wheel-smoke.sh (negative cases)."""
from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

import enginefx as fx

CHECK = fx.SCRIPTS / "check-tag-version.sh"
SECTION = fx.SCRIPTS / "changelog-section.sh"
SMOKE = fx.SCRIPTS / "wheel-smoke.sh"


def sh(*argv: str | Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", *map(str, argv)], capture_output=True, text=True, env=env)


def tree_state(root: Path) -> list[tuple]:
    rows = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            st = os.lstat(Path(dirpath) / name)
            rows.append((os.path.relpath(Path(dirpath) / name, root), st.st_mtime_ns, st.st_size))
    return sorted(rows)


@pytest.fixture
def static_copy(tmp_path) -> Path:
    """Minimal engine root whose tooling/pyproject.toml carries a static version line."""
    root = tmp_path / "engine"
    (root / "tooling").mkdir(parents=True)
    shutil.copy(fx.ENGINE_ROOT / "VERSION", root / "VERSION")
    text = (fx.TOOLING / "pyproject.toml").read_text()
    (root / "tooling" / "pyproject.toml").write_text(
        text.replace('name = "harry-sdlc"', f'name = "harry-sdlc"\nversion = "{fx.repo_version()}"'))
    return root


def test_ac4_check_tag_version_cases(static_copy):
    v = fx.repo_version()
    cases = [("v" + v, None), ("v" + fx.bump_patch(v), None), (v, None), ("main", None), ("v" + v, static_copy)]
    before = tree_state(static_copy)
    results = [sh(CHECK, tag, *([root] if root else [])) for tag, root in cases]
    assert [r.returncode for r in results] == [0, 1, 1, 1, 1]
    for (tag, _), r in zip(cases[1:], results[1:]):
        assert f"tag '{tag}'" in r.stderr and f"VERSION '{v}'" in r.stderr, r.stderr
    assert "tag_mismatch" in results[1].stderr
    assert "tag_invalid" in results[2].stderr and "tag_invalid" in results[3].stderr
    assert results[4].stderr.startswith("static_version:"), results[4].stderr
    assert tree_state(static_copy) == before  # read only


def test_check_tag_version_invalid_version_file_and_usage(tmp_path):
    root = tmp_path / "engine"
    root.mkdir()
    r = sh(CHECK, "v1.0.0", root)
    assert r.returncode == 1 and "version_invalid" in r.stderr
    (root / "VERSION").write_text("1.0.0\n1.0.1\n")
    r = sh(CHECK, "v1.0.0", root)
    assert r.returncode == 1 and "version_invalid" in r.stderr
    (root / "VERSION").write_text("1.0.0\n")
    assert sh(CHECK, "v1.0.0", root).returncode == 0
    assert sh(CHECK).returncode == 2
    assert sh(CHECK, "v1.0.0", root / "missing").returncode == 2


CHANGELOG = """# Changelog

## [Unreleased]

## [1.2.3] - 2026-01-02

### Added
- first line of 1.2.3

## [1.2.2] - 2025-01-01
- old
## [1.2.4] \u2014 2026-01-01
- long dash
## [1.2.5] - 2026-01-01

## [1.2.6]
- no date
"""


def test_changelog_section_found_and_missing(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text(CHANGELOG, encoding="utf-8")
    r = sh(SECTION, "1.2.3", f)
    assert r.returncode == 0
    assert r.stdout.strip().splitlines() == ["### Added", "- first line of 1.2.3"]
    assert sh(SECTION, "1.2.2", f).stdout.strip() == "- old"
    for missing in ("1.2.4", "1.2.5", "1.2.6", "9.9.9"):  # long dash, empty, no date, absent
        r = sh(SECTION, missing, f)
        assert r.returncode == 1 and "changelog_section_missing" in r.stderr, missing
    assert sh(SECTION, "1.2", f).returncode == 2
    r = sh(SECTION, "1.2.3", tmp_path / "none.md")
    assert r.returncode == 1 and "changelog_section_missing" in r.stderr


def test_changelog_section_version_is_literal(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text("## [1x2x3] - 2026-01-01\n- not 1.2.3\n")
    assert sh(SECTION, "1.2.3", f).returncode == 1


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory) -> Path:
    if not fx.uv_path():
        pytest.skip("uv is required to build the wheel")
    out = tmp_path_factory.mktemp("dist")
    proc = fx.build_dist(out, "--wheel")
    assert proc.returncode == 0, proc.stderr
    return next(out.glob("harry_sdlc-*-py3-none-any.whl"))


def rewrite_wheel(src: Path, dst: Path, *, drop: str | None = None, add: tuple[str, str] | None = None,
                  meta_extra: str | None = None) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for item in zin.infolist():
            if item.filename == drop:
                continue
            data = zin.read(item.filename)
            if meta_extra and item.filename.endswith(".dist-info/METADATA"):
                data = data.replace(b"\n\n", f"\n{meta_extra}\n\n".encode(), 1) if b"\n\n" in data \
                    else data + f"{meta_extra}\n".encode()
            zout.writestr(item, data)
        if add:
            zout.writestr(add[0], add[1])
    return dst


def test_wheel_smoke_rejects_wheel_with_extra_file(built_wheel, tmp_path):
    bad = rewrite_wheel(built_wheel, tmp_path / built_wheel.name, add=("tests/test_x.py", "x = 1\n"))
    r = sh(SMOKE, bad)
    assert r.returncode == 1 and "unexpected entries" in r.stderr and "tests/test_x.py" in r.stderr


@pytest.mark.parametrize("drop", ["sdlc/runws/__init__.py", "sdlc/py.typed", "sdlc/_version.py"])
def test_wheel_smoke_rejects_incomplete_wheel(built_wheel, tmp_path, drop):
    bad = rewrite_wheel(built_wheel, tmp_path / built_wheel.name, drop=drop)
    r = sh(SMOKE, bad)
    assert r.returncode == 1 and f"missing {drop}" in r.stderr


def test_wheel_smoke_rejects_dependency(built_wheel, tmp_path):
    bad = rewrite_wheel(built_wheel, tmp_path / built_wheel.name, meta_extra="Requires-Dist: requests")
    r = sh(SMOKE, bad)
    assert r.returncode == 1 and "Requires-Dist" in r.stderr


def test_wheel_smoke_accepts_built_wheel_without_pythonpath_leak(built_wheel):
    # PYTHONPATH pointing at the source tree must not hide the installed wheel (G2)
    env = dict(os.environ, PYTHONPATH=str(fx.TOOLING))
    r = sh(SMOKE, built_wheel, env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith(f"sdlc {fx.repo_version()} (release)")
    assert "unset PYTHONPATH" in SMOKE.read_text()


def test_repository_changelog_has_the_released_section():
    text = (fx.ENGINE_ROOT / "CHANGELOG.md").read_text()
    headers = [l for l in text.splitlines() if l.startswith("## [")]
    assert headers[0] == "## [Unreleased]"
    r = sh(SECTION, fx.repo_version())
    assert r.returncode == 0 and r.stdout.strip(), r.stderr
    # The content check is pinned to 0.7.0, the first packaged release, so later bumps keep passing.
    r = sh(SECTION, "0.7.0")
    assert r.returncode == 0 and r.stdout.strip(), r.stderr
    for needle in ("sdlc brain", "brainRef", "sdlc run", "sdlc doc", "sdlc clone", "runWorkspace", "--version"):
        assert needle in r.stdout, needle
