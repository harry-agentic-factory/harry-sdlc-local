#!/usr/bin/env bash
# ci-local.sh [--release <tag>] [--out <dir>] -- local dry run of .github/workflows/ci.yml and release.yml.
#
# Runs the same sequence as the "run:" steps of the workflows: tests, uv build, wheel smoke. With --release,
# first the release gates (tag <-> VERSION, annotated tag reachable from origin/main when the tag exists
# locally, CHANGELOG section), then the CI sequence; the "gh release create" command that Actions would run
# is printed, never executed. Nothing is pushed, tagged or published. Build output goes to --out (default: a
# fresh mktemp -d), never into the source tree.
set -euo pipefail

usage() { echo "usage: ci-local.sh [--release <tag>] [--out <dir>]" >&2; exit 2; }
tag=""
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    --release) [ $# -ge 2 ] || usage; tag=$2; shift 2 ;;
    --out) [ $# -ge 2 ] || usage; out=$2; shift 2 ;;
    *) usage ;;
  esac
done
root="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -n "$out" ] || out="$(mktemp -d)"
mkdir -p "$out"
out="$(cd -P "$out" && pwd)"
cd "$root"
export SDLC_REQUIRE_NODE="${SDLC_REQUIRE_NODE:-1}"
step() { printf '\n== %s\n' "$*"; }

if [ -n "$tag" ]; then
  step "release: check-tag-version $tag"
  scripts/check-tag-version.sh "$tag"
  version="$(cat VERSION)"
  step "release: annotated tag reachable from origin/main"
  if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    [ "$(git cat-file -t "refs/tags/$tag")" = "tag" ] || { echo "tag_not_annotated: $tag" >&2; exit 1; }
    git merge-base --is-ancestor "refs/tags/$tag^{commit}" refs/remotes/origin/main \
      || { echo "tag_not_on_main: $tag is not an ancestor of origin/main" >&2; exit 1; }
    echo "ok: $tag is annotated and reachable from origin/main"
  else
    echo "skipped: tag $tag does not exist locally (checked by the release workflow on GitHub)"
  fi
  step "release: changelog-section $version"
  scripts/changelog-section.sh "$version" > "$out/notes.md"
  echo "ok: notes in $out/notes.md ($(wc -l < "$out/notes.md" | tr -d ' ') lines)"
fi

step "ci: pytest tooling/tests"
python3 -m pytest -q -p no:cacheprovider tooling/tests
step "ci: uv build"
(cd tooling && uv build --out-dir "$out/dist")
wheel="$(ls "$out"/dist/harry_sdlc-*-py3-none-any.whl)"
sdist="$(ls "$out"/dist/harry_sdlc-*.tar.gz)"
step "ci: wheel-smoke"
scripts/wheel-smoke.sh "$wheel"

if [ -n "$tag" ]; then
  step "release: command run by the workflow (not executed here)"
  echo "gh release create \"$tag\" \"$wheel\" \"$sdist\" --title \"$tag\" --notes-file \"$out/notes.md\" --verify-tag"
fi
echo
echo "ok: local dry run passed (output in $out)"
