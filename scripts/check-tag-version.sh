#!/usr/bin/env bash
# check-tag-version.sh <tag> [<root>] -- the single tag <-> VERSION rule of a release.
#
# Used by .github/workflows/release.yml, install.sh and scripts/ci-local.sh. Read only.
# Checks (all reported, on stderr, as "<code>: tag '<tag>' vs VERSION '<version>'"):
#   tag_invalid     <tag> is not vX.Y.Z
#   version_invalid <root>/VERSION is missing or is not a single X.Y.Z line
#   tag_mismatch    <tag> is not "v" + VERSION
#   static_version  tooling/pyproject.toml declares a static "version =" (VERSION must stay the only source)
# Exit: 0 consistent, 1 refused, 2 usage.
set -u

usage() { echo "usage: check-tag-version.sh <tag> [<root>]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
tag=$1
if [ $# -eq 2 ]; then
  root=$2
else
  root="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
[ -d "$root" ] || { echo "usage: root '$root' is not a directory" >&2; exit 2; }

semver_re='^[0-9]+\.[0-9]+\.[0-9]+$'
tag_re='^v[0-9]+\.[0-9]+\.[0-9]+$'
version=""
version_ok=0
if [ -f "$root/VERSION" ]; then
  version="$(cat "$root/VERSION")"
  if [[ "$version" =~ $semver_re ]]; then version_ok=1; fi
fi

failed=0
report() { echo "$1: tag '$tag' vs VERSION '$version'" >&2; failed=1; }

[[ "$tag" =~ $tag_re ]] || report tag_invalid
[ "$version_ok" -eq 1 ] || report version_invalid
[ "$tag" = "v$version" ] || report tag_mismatch
if [ -f "$root/tooling/pyproject.toml" ] && grep -qE '^[[:space:]]*version[[:space:]]*=' "$root/tooling/pyproject.toml"; then
  report static_version
fi

[ "$failed" -eq 0 ] || exit 1
echo "ok: tag '$tag' matches VERSION '$version'"
