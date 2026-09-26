#!/usr/bin/env bash
# changelog-section.sh <X.Y.Z> [<file>] -- print the body of the "## [X.Y.Z] - YYYY-MM-DD" section.
#
# The header must match exactly (Keep a Changelog, ASCII hyphen); the body runs up to the next "## [".
# A missing or empty section fails with changelog_section_missing (exit 1). Usage error: exit 2.
set -u

usage() { echo "usage: changelog-section.sh <X.Y.Z> [<file>]" >&2; exit 2; }
[ $# -ge 1 ] && [ $# -le 2 ] || usage
version=$1
semver_re='^[0-9]+\.[0-9]+\.[0-9]+$'
[[ "$version" =~ $semver_re ]] || usage
file=${2:-"$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/CHANGELOG.md"}
if [ ! -f "$file" ]; then
  echo "changelog_section_missing: $file not found (version $version)" >&2
  exit 1
fi

body="$(awk -v v="$version" '
  found && /^## \[/ { exit }
  found { print }
  !found {
    p = "## [" v "] - "
    if (index($0, p) == 1 && substr($0, length(p) + 1) ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/) found = 1
  }
' "$file")"

if ! printf '%s\n' "$body" | grep -q '[^[:space:]]'; then
  echo "changelog_section_missing: no non-empty '## [$version] - YYYY-MM-DD' section in $file" >&2
  exit 1
fi
printf '%s\n' "$body"
