"""Build hooks of the harry-sdlc package (run at build time only, stdlib + hatchling).

Single version source: the VERSION file of the repository root (one ``X.Y.Z`` line).

- Source tree (working copy, clone at a tag, ``uv add git+...#subdirectory=tooling``): ``<root>/../VERSION``.
- Unpacked sdist (``<root>/PKG-INFO`` present): ``<root>/VERSION``, embedded by the sdist target.
  ``../VERSION`` is never read there, so a foreign file next to the extraction cannot leak in.

No default value: an unreadable or non semver VERSION fails the build (``version_unresolved``).
The wheel hook embeds ``sdlc/_version.py`` from a temporary file; nothing is written in the source tree.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from hatchling.metadata.plugin.interface import MetadataHookInterface

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def resolve_version(root: str | os.PathLike[str]) -> str:
    base = Path(root)
    source = base / "VERSION" if (base / "PKG-INFO").is_file() else base.parent / "VERSION"
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"version_unresolved: cannot read {source}: {exc}") from None
    value = lines[0].strip() if lines else ""
    if not SEMVER_RE.match(value):
        raise ValueError(f"version_unresolved: {source} does not hold an X.Y.Z line (got {value!r})")
    return value


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict) -> None:
        metadata["version"] = resolve_version(self.root)


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        value = self.metadata.version
        if not SEMVER_RE.match(value):
            raise ValueError(f"version_unresolved: metadata version {value!r} is not X.Y.Z")
        self._tmpdir = tempfile.mkdtemp(prefix="harry-sdlc-build-")
        path = Path(self._tmpdir) / "_version.py"
        path.write_text(
            '"""Generated at build time from VERSION; never tracked."""\n'
            f'__version__ = "{value}"\n',
            encoding="utf-8",
        )
        build_data.setdefault("force_include", {})[str(path)] = "sdlc/_version.py"

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        tmpdir = getattr(self, "_tmpdir", None)
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
            self._tmpdir = None
