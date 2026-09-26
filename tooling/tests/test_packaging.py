"""harry-sdlc package: build (AC1), install in an empty venv (AC2), script <-> package parity (AC3).

The installed package is always exercised with PYTHONPATH unset and from a directory outside the source
tree (G2), so a source tree on the path can never hide an incomplete wheel.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

import enginefx as fx

V = fx.repo_version()
WHEEL = f"harry_sdlc-{V}-py3-none-any.whl"
SDIST = f"harry_sdlc-{V}.tar.gz"

pytestmark = pytest.mark.skipif(fx.uv_path() is None, reason="uv is required to build the package")


@pytest.fixture(scope="module")
def dist(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    proc = fx.build_dist(out)  # default path of uv: sdist first, then the wheel from the unpacked sdist
    assert proc.returncode == 0, proc.stderr
    return out


@pytest.fixture(scope="module")
def wheel(dist) -> Path:
    return dist / WHEEL


@pytest.fixture(scope="module")
def names(wheel) -> list[str]:
    return zipfile.ZipFile(wheel).namelist()


def metadata(wheel: Path) -> str:
    return zipfile.ZipFile(wheel).read(f"harry_sdlc-{V}.dist-info/METADATA").decode()


def clean_env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV") and not k.startswith(("SDLC_", "HARRY_SDLC_"))}
    env.update(HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    env.update(fx.git_env(home))
    return env


@pytest.fixture(scope="module")
def venv(tmp_path_factory, wheel) -> Path:
    base = tmp_path_factory.mktemp("venv")
    env = clean_env(base)
    subprocess.run([sys.executable, "-m", "venv", str(base / "venv")], check=True, env=env)
    proc = subprocess.run([str(base / "venv" / "bin" / "python"), "-m", "pip", "install", "--quiet",
                           "--disable-pip-version-check", "--no-index", "--no-deps", str(wheel)],
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return base / "venv"


def in_venv(venv: Path, *argv: str, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(venv / "bin" / argv[0]), *argv[1:]], cwd=cwd, env=clean_env(home),
                          capture_output=True, text=True)


# ---- AC1 -------------------------------------------------------------------------------------------------

def test_ac1_build_produces_wheel_and_sdist(dist):
    built = sorted(n for n in os.listdir(dist) if n != ".gitignore")  # uv marks its output folder ignored
    assert built == sorted([WHEEL, SDIST])


def test_ac1_wheel_contains_only_sdlc(names):
    assert [n for n in names if not re.match(rf"^(sdlc/|harry_sdlc-{re.escape(V)}\.dist-info/)", n)] == []
    assert [n for n in names if "__pycache__" in n or n.endswith(".pyc")] == []
    assert not any(n.startswith(("sdlc/tests", "tests/", "cockpit/", "claude/")) for n in names)


def test_ac1_wheel_ships_brain_runws_migrations(names):
    source = sorted(str(p.relative_to(fx.TOOLING)) for p in (fx.TOOLING / "sdlc").rglob("*.py")
                    if "__pycache__" not in p.parts and p.name != "_version.py")
    assert source and set(source) <= set(names)
    for required in ("sdlc/_version.py", "sdlc/py.typed", "sdlc/migrations/__init__.py",
                     "sdlc/brain/__init__.py", "sdlc/runws/__init__.py", "sdlc/version.py"):
        assert required in names, required
    assert sum(n == "sdlc/py.typed" for n in names) == 1  # inv. 41


def test_ac1_no_requires_dist(wheel):
    meta = metadata(wheel)
    assert not re.search(r"^Requires-Dist:", meta, re.M)
    assert re.search(r"^Name: harry-sdlc$", meta, re.M)
    assert re.search(rf"^Version: {re.escape(V)}$", meta, re.M)
    assert re.search(r"^Requires-Python: >=3\.11$", meta, re.M)
    entry_points = zipfile.ZipFile(wheel).read(f"harry_sdlc-{V}.dist-info/entry_points.txt").decode()
    assert re.search(r"^sdlc = sdlc\.cli:main$", entry_points, re.M)
    version_py = zipfile.ZipFile(wheel).read("sdlc/_version.py").decode()
    assert f'__version__ = "{V}"' in version_py


def test_ac1_no_static_version():
    text = (fx.TOOLING / "pyproject.toml").read_text()
    assert not re.search(r"^\s*version\s*=", text, re.M)
    assert 'dynamic = ["version"]' in text and 'name = "harry-sdlc"' in text
    assert "dependencies = []" in text and "optional-dependencies" not in text
    assert 'build-backend = "hatchling.build"' in text and 'packages = ["sdlc"]' in text
    assert 'sdlc = "sdlc.cli:main"' in text
    assert "[tool.hatch.build.hooks.custom]" not in text  # inv. 38: build hook on the wheel target only
    assert "[tool.hatch.build.targets.wheel.hooks.custom]" in text


def test_ac1_sdist_carries_version_file(dist):
    with tarfile.open(dist / SDIST) as tar:
        members = tar.getnames()
        assert f"harry_sdlc-{V}/VERSION" in members
        assert tar.extractfile(f"harry_sdlc-{V}/VERSION").read().decode().strip() == V
    assert not any(m.endswith("sdlc/_version.py") for m in members)
    assert not any(m.startswith(f"harry_sdlc-{V}/tests") for m in members)


def test_ac1_wheel_from_sdist_equals_direct_wheel(tmp_path, names, wheel):
    proc = fx.build_dist(tmp_path, "--wheel")
    assert proc.returncode == 0, proc.stderr
    direct = tmp_path / WHEEL
    assert sorted(zipfile.ZipFile(direct).namelist()) == sorted(names)
    version_line = re.compile(r"^Version: .*$", re.M)
    assert version_line.findall(metadata(direct)) == version_line.findall(metadata(wheel)) == [f"Version: {V}"]


def tree_listing(root: Path) -> list[tuple]:
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in dirnames + filenames:
            if name.endswith(".pyc"):
                continue
            p = Path(dirpath) / name
            st = os.lstat(p)
            rows.append((str(p.relative_to(root)), st.st_mtime_ns if p.is_file() else 0))
    return sorted(rows)


def test_ac1_build_leaves_tree_clean(tmp_path):
    before = tree_listing(fx.TOOLING)
    proc = fx.build_dist(tmp_path / "out")
    assert proc.returncode == 0, proc.stderr
    assert tree_listing(fx.TOOLING) == before
    assert not (fx.TOOLING / "sdlc" / "_version.py").exists()


def _tooling_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "engine" / "tooling"
    shutil.copytree(fx.TOOLING, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "cockpit",
                                                                    "dist", "_version.py"))
    return dst


@pytest.mark.parametrize("content", [None, "not-a-version\n", "1.2\n"])
def test_build_fails_without_a_valid_version(tmp_path, content):
    tooling = _tooling_copy(tmp_path)
    if content is not None:
        (tooling.parent / "VERSION").write_text(content)
    proc = subprocess.run([fx.uv_path(), "build", "--wheel", "--out-dir", str(tmp_path / "out")],
                          cwd=tooling, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "version_unresolved" in proc.stdout + proc.stderr
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("*.whl"))


# ---- AC2 -------------------------------------------------------------------------------------------------

def test_ac2_venv_install_has_no_deps(venv, tmp_path):
    proc = in_venv(venv, "python", "-m", "pip", "list", "--format", "json", "--disable-pip-version-check",
                   cwd=tmp_path, home=tmp_path)
    assert proc.returncode == 0, proc.stderr
    pkgs = {p["name"].lower(): p["version"] for p in json.loads(proc.stdout)}
    pkgs = {k: v for k, v in pkgs.items() if k not in ("pip", "setuptools", "wheel")}
    assert pkgs == {"harry-sdlc": V}


def test_ac2_version_release(venv, tmp_path):
    proc = in_venv(venv, "sdlc", "--version", cwd=tmp_path, home=tmp_path)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, f"{V} (release)\n", "")
    origin = in_venv(venv, "python", "-c", "import os, sdlc; print(os.path.realpath(sdlc.__file__))",
                     cwd=tmp_path, home=tmp_path).stdout.strip()
    purelib = in_venv(venv, "python", "-c",
                      "import os, sysconfig; print(os.path.realpath(sysconfig.get_paths()['purelib']))",
                      cwd=tmp_path, home=tmp_path).stdout.strip()
    assert origin.startswith(purelib + os.sep), (origin, purelib)


def test_engine_version_packaged_outside_checkout(venv, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    code = ("from sdlc.migrations import engine_version as a; from sdlc.version import engine_version as b, "
            "engine_mode; print(a(), b(), engine_mode()[0])")
    proc = in_venv(venv, "python", "-c", code, cwd=empty, home=empty)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == [V, V, "release"]
    assert "0.1.0" not in proc.stdout


def test_ac2_help_and_subcommand_help(venv, tmp_path):
    for args in (["-h"], ["run", "-h"], ["doc", "-h"], ["clone", "-h"]):
        proc = in_venv(venv, "sdlc", *args, cwd=tmp_path, home=tmp_path)
        assert proc.returncode == 0, (args, proc.stderr)
    assert "--version" in in_venv(venv, "sdlc", "-h", cwd=tmp_path, home=tmp_path).stdout
    brain = in_venv(venv, "sdlc", "brain", "-h", cwd=tmp_path, home=tmp_path)
    assert brain.returncode == 0
    for sub in ("normalize", "lint", "diff", "history", "snapshot"):
        assert sub in brain.stdout, sub
        assert in_venv(venv, "sdlc", "brain", sub, "-h", cwd=tmp_path, home=tmp_path).returncode == 0, sub


def _module_level_imports(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []

    def walk(nodes):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue  # lazy imports (e.g. mcp in mcp_server.build_server) are allowed
            if isinstance(node, ast.Import):
                out.extend((0, a.name) for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                out.append((node.level, node.module or ""))
            for field in ("body", "orelse", "finalbody", "handlers"):
                walk(getattr(node, field, []) or [])
    walk(tree.body)
    return out


def test_wheel_stdlib_only(wheel):
    z = zipfile.ZipFile(wheel)
    offenders = []
    for name in z.namelist():
        if not name.endswith(".py"):
            continue
        for level, module in _module_level_imports(ast.parse(z.read(name).decode(), name)):
            root = module.split(".")[0]
            if level == 0 and root not in sys.stdlib_module_names and root != "sdlc":
                offenders.append((name, module))
    assert offenders == []


# ---- AC3 -------------------------------------------------------------------------------------------------

def _demo_project(base: Path, script_env: dict[str, str]) -> None:
    """The DEMO project of demo/demo-cli.sh (init, manifest, epic, stories with deps, one transition)."""
    data = base / "demo-sdlc-local"
    for repo in ("app-repo", "web-repo"):
        (base / repo).mkdir()
        fx.git("init", "-q", "-b", "main", cwd=base / repo)
        fx.git("commit", "-q", "--allow-empty", "-m", "init", cwd=base / repo)
    (base / "demo-brain").mkdir()
    (base / "demo-brain" / "README.md").write_text("# Demo brain\n")
    sdlc = [str(fx.ENGINE_ROOT / "bin" / "sdlc")]

    def run(*args: str) -> None:
        proc = subprocess.run([*sdlc, *args], cwd=base, env=script_env, capture_output=True, text=True)
        assert proc.returncode == 0, (args, proc.stderr)

    run("init-project", "DEMO", "--path", str(data), "--repos", "app-repo,web-repo")
    cfg = data / "sdlc.config.json"
    d = json.loads(cfg.read_text())
    d["reposRoot"], d["brain"] = str(base), "demo-brain"
    cfg.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    run("--project", "DEMO", "create-epic", "DEMO-PAY", "Payment funnel")
    run("--project", "DEMO", "create-ticket", "DEMO-PAY", "DEMO-PAY-2", "payment core", "--repos", "app-repo")
    run("--project", "DEMO", "create-ticket", "DEMO-PAY", "DEMO-PAY-1", "payment page", "--deps", "DEMO-PAY-2",
        "--repos", "web-repo")
    run("--project", "DEMO", "create-ticket", "DEMO-PAY", "DEMO-PAY-3", "receipt", "--deps", "DEMO-PAY-1",
        "--repos", "app-repo,web-repo")
    run("--project", "DEMO", "set-status", "DEMO-PAY-2", "spec_func")


def test_ac3_script_and_package_same_json(venv, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    script_env = clean_env(home)
    _demo_project(tmp_path, script_env)
    commands = [["projects"], ["get", "DEMO-PAY-1"], ["status", "DEMO-PAY"], ["next", "DEMO-PAY"], ["list"],
                ["config"]]
    for cmd in commands:
        argv = ["--project", "DEMO", *cmd]
        a = subprocess.run([str(fx.ENGINE_ROOT / "bin" / "sdlc"), *argv], cwd=tmp_path, env=script_env,
                           capture_output=True, text=True)
        b = in_venv(venv, "sdlc", *argv, cwd=tmp_path, home=home)
        assert a.returncode == b.returncode == 0, (cmd, a.stderr, b.stderr)
        assert json.loads(a.stdout) == json.loads(b.stdout), cmd
