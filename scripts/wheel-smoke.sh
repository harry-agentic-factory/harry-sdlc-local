#!/usr/bin/env bash
# wheel-smoke.sh <wheel> -- install a built harry-sdlc wheel in a throwaway venv and check it, offline.
#
# The wheel has no dependency: pip runs with --no-index --no-deps (no network). Every command runs from a
# directory outside the source tree with PYTHONPATH unset, so the installed package is the one exercised.
# Exit 0 when every check passes, 1 at the first failure (named on stderr), 2 on usage error.
set -euo pipefail
unset PYTHONPATH

usage() { echo "usage: wheel-smoke.sh <wheel>" >&2; exit 2; }
[ $# -eq 1 ] || usage
[ -f "$1" ] || { echo "usage: wheel '$1' not found" >&2; exit 2; }
wheel="$(cd -P "$(dirname "$1")" && pwd)/$(basename "$1")"
root="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
expected="$(cat "$root/VERSION")"
py="${PYTHON:-python3}"

fail() { echo "wheel_smoke_failed: $*" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

# 1. Content of the wheel and its metadata (read with zipfile, nothing extracted).
"$py" - "$wheel" "$expected" <<'PY' || exit 1
import re, sys, zipfile
wheel, expected = sys.argv[1], sys.argv[2]
names = zipfile.ZipFile(wheel).namelist()
info = f"harry_sdlc-{expected}.dist-info/"
def fail(msg):
    print(f"wheel_smoke_failed: {msg}", file=sys.stderr); sys.exit(1)
extra = [n for n in names if not (n.startswith("sdlc/") or n.startswith(info))]
if extra:
    fail(f"unexpected entries outside sdlc/ and {info}: {extra}")
for required in ("sdlc/_version.py", "sdlc/py.typed", "sdlc/migrations/__init__.py",
                 "sdlc/brain/__init__.py", "sdlc/runws/__init__.py"):
    if required not in names:
        fail(f"missing {required}")
cached = [n for n in names if "__pycache__" in n or n.endswith(".pyc")]
if cached:
    fail(f"compiled files shipped: {cached}")
z = zipfile.ZipFile(wheel)
meta = z.read(info + "METADATA").decode()
headers = dict(l.split(": ", 1) for l in meta.split("\n\n", 1)[0].splitlines() if ": " in l)
if headers.get("Name") != "harry-sdlc":
    fail(f"Name is {headers.get('Name')!r}")
if headers.get("Version") != expected:
    fail(f"Version is {headers.get('Version')!r}, VERSION is {expected!r}")
if headers.get("Requires-Python") != ">=3.11":
    fail(f"Requires-Python is {headers.get('Requires-Python')!r}")
if re.search(r"^Requires-Dist:", meta, re.M):
    fail("the wheel declares a dependency (Requires-Dist)")
entry_points = z.read(info + "entry_points.txt").decode()
if not re.search(r"^sdlc = sdlc\.cli:main$", entry_points, re.M):
    fail("console script 'sdlc = sdlc.cli:main' missing")
PY

# 2. Install in an empty venv, offline.
"$py" -m venv "$work/venv"
vpy="$work/venv/bin/python"
PIP_DISABLE_PIP_VERSION_CHECK=1 "$vpy" -m pip install --quiet --no-index --no-deps "$wheel" \
  || fail "pip install --no-index --no-deps"

# 3. The imported package is the installed one.
purelib="$("$vpy" -c 'import os, sysconfig; print(os.path.realpath(sysconfig.get_paths()["purelib"]))')"
origin="$("$vpy" -c 'import os, sdlc; print(os.path.realpath(sdlc.__file__))')"
case "$origin" in "$purelib"/*) ;; *) fail "sdlc imported from $origin, not from the venv ($purelib)" ;; esac

# 4. Version, mode and command help.
out="$("$work/venv/bin/sdlc" --version)" || fail "sdlc --version exit code"
[ "$out" = "$expected (release)" ] || fail "sdlc --version printed '$out', expected '$expected (release)'"
got="$("$vpy" -c 'from sdlc.migrations import engine_version; print(engine_version())')"
[ "$got" = "$expected" ] || fail "engine_version() is '$got', expected '$expected'"
for args in "-h" "brain -h" "run -h" "doc -h" "clone -h"; do
  # shellcheck disable=SC2086
  "$work/venv/bin/sdlc" $args >/dev/null || fail "sdlc $args exit code"
done
brain_help="$("$work/venv/bin/sdlc" brain -h)"
for sub in normalize lint diff history snapshot; do
  case "$brain_help" in *"$sub"*) ;; *) fail "sdlc brain -h does not list '$sub'" ;; esac
done

echo "ok: $(basename "$wheel") installs offline, sdlc $out"
