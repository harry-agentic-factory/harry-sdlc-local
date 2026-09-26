"""Engine version and mode (``sdlc --version``), stdlib only, no side effect at import.

Version sources, in order:

1. ``sdlc._version.__version__``: generated at build time, present in a built package only;
2. ``VERSION`` at the engine root (working copy, or a version installed by ``install.sh``);
3. the installed distribution metadata (``harry-sdlc``);
4. ``0.0.0+unknown`` (visible, never a plausible version).

Mode: ``release`` for a built package or an engine root that is a direct child of
``$HARRY_SDLC_HOME`` (default ``~/.local/share/harry-sdlc``) named ``v<version>``; ``dev`` otherwise.

This is the only module of the package that resolves a path from its own file.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

DIST_NAME = "harry-sdlc"
UNKNOWN = "0.0.0+unknown"
GIT_TIMEOUT_S = 5
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
# Variables that would make git look at another repository than the engine root.
_GIT_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                     "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR")


def engine_root() -> Path:
    """Root of the engine this module was loaded from (``tooling/sdlc/version.py`` -> root)."""
    return Path(__file__).resolve().parents[2]


def packaged_version() -> str | None:
    """Version embedded by the build, or None when running from a source tree."""
    try:
        from ._version import __version__  # type: ignore[import-not-found]
    except ImportError:
        return None
    return str(__version__)


def _root_version(root: Path) -> str | None:
    try:
        lines = (root / "VERSION").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    value = lines[0].strip() if lines else ""
    return value if _SEMVER_RE.match(value) else None


def _metadata_version() -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - stdlib on every supported Python
        return None
    try:
        return version(DIST_NAME)
    except PackageNotFoundError:
        return None


def _version_at(root: Path) -> str:
    return packaged_version() or _root_version(root) or _metadata_version() or UNKNOWN


def engine_version() -> str:
    """Exact engine version, from any install mode (never a silent default)."""
    return _version_at(engine_root())


def _harry_home(home: str | os.PathLike[str] | None) -> Path:
    if home is not None:
        return Path(home)
    env = os.environ.get("HARRY_SDLC_HOME")
    return Path(env) if env else Path.home() / ".local" / "share" / "harry-sdlc"


def engine_mode(root: str | os.PathLike[str] | None = None,
                home: str | os.PathLike[str] | None = None) -> tuple[str, str | None]:
    """``("release", None)`` or ``("dev", <physical root>)``."""
    if packaged_version() is not None:
        return ("release", None)
    real_root = Path(os.path.realpath(root if root is not None else engine_root()))
    real_home = Path(os.path.realpath(_harry_home(home)))
    if real_root.parent == real_home and real_root.name == "v" + _version_at(real_root):
        return ("release", None)
    return ("dev", str(real_root))


def _git(root: Path, *args: str) -> str | None:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_ENV}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        proc = subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args],
                              capture_output=True, text=True, env=env, timeout=GIT_TIMEOUT_S,
                              stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _dev_suffix(root: Path) -> str:
    """``<sha7>`` or ``<sha7>.dirty``; ``unknown`` when git cannot describe the root itself."""
    out = _git(root, "rev-parse", "--show-toplevel", "--short=7", "HEAD")
    lines = out.splitlines() if out else []
    if len(lines) != 2 or os.path.realpath(lines[0]) != str(root):
        return "unknown"  # no git, not a repository, or the root is only inside another one
    status = _git(root, "status", "--porcelain")
    if status is None:
        return "unknown"
    return lines[1] + (".dirty" if status.strip() else "")


def version_line(root: str | os.PathLike[str] | None = None,
                 home: str | os.PathLike[str] | None = None) -> str:
    """``X.Y.Z (release)`` or ``X.Y.Z-dev+<sha7>[.dirty] (dev: <physical root>)``."""
    mode, where = engine_mode(root, home)
    if mode == "release":
        base = packaged_version() or _version_at(Path(os.path.realpath(
            root if root is not None else engine_root())))
        return f"{base} (release)"
    real_root = Path(where or ".")
    return f"{_version_at(real_root)}-dev+{_dev_suffix(real_root)} (dev: {real_root})"
