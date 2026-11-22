#!/bin/bash
# Ground truth for a Spring Batch schema change: the SQL inside the jars, not a blog post.
#
#   ./reference-schema-diff.sh 4.3.4 5.0.2 postgresql
#   ./reference-schema-diff.sh 4.3.4 5.0.2 h2
#
# Prints the diff of schema-<platform>.sql between the two versions, and the official
# migration script the target version ships -- which is the part worth reading closely,
# because it migrates the structure and can leave the data wrong.
#
# Requires maven and a JDK on the PATH; downloads only into the local repository.

set -euo pipefail

FROM=${1:?usage: reference-schema-diff.sh <from-version> <to-version> <platform>}
TO=${2:?usage: reference-schema-diff.sh <from-version> <to-version> <platform>}
PLATFORM=${3:-postgresql}

MVN=${MVN:-mvn}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

fetch() {
  local version=$1 dest=$2
  local jar="$HOME/.m2/repository/org/springframework/batch/spring-batch-core/$version/spring-batch-core-$version.jar"
  if [ ! -f "$jar" ]; then
    echo "-- fetching spring-batch-core:$version" >&2
    "$MVN" -q -B dependency:get -Dartifact="org.springframework.batch:spring-batch-core:$version" >&2
  fi
  [ -f "$jar" ] || { echo "spring-batch-core:$version not available" >&2; exit 1; }
  unzip -o -q "$jar" "org/springframework/batch/core/schema-$PLATFORM.sql" \
      "org/springframework/batch/core/migration/*" -d "$dest" 2>/dev/null || true
}

fetch "$FROM" "$WORK/from"
fetch "$TO" "$WORK/to"

FROM_SQL="$WORK/from/org/springframework/batch/core/schema-$PLATFORM.sql"
TO_SQL="$WORK/to/org/springframework/batch/core/schema-$PLATFORM.sql"

for f in "$FROM_SQL" "$TO_SQL"; do
  [ -f "$f" ] || { echo "no schema-$PLATFORM.sql in one of the jars -- check the platform name" >&2; exit 1; }
done

echo "=== schema-$PLATFORM.sql : $FROM -> $TO ==="
diff -u "$FROM_SQL" "$TO_SQL" || true

MINOR=${TO%.*}          # 5.0.2 -> 5.0
OFFICIAL="$WORK/to/org/springframework/batch/core/migration/$MINOR/migration-$PLATFORM.sql"
echo
if [ -f "$OFFICIAL" ]; then
  echo "=== migration/$MINOR/migration-$PLATFORM.sql, as shipped ==="
  cat "$OFFICIAL"
  echo
  echo "--- read this before running it ---"
  echo "A DROP COLUMN on a typed value column loses that column's data."
  echo "A RENAME of TYPE_CD to PARAMETER_TYPE does NOT convert its values, and 5.x resolves"
  echo "that column with Class.forName, so 'LONG' throws on the next read of the history."
else
  echo "=== no migration/$MINOR/migration-$PLATFORM.sql in the jar ==="
  echo "The structural change is yours to write, and so is the data migration either way."
fi
