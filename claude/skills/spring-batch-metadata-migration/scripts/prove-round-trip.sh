#!/bin/bash
# Proves the Spring Batch metadata migration is REVERSIBLE, on real rows.
#
#   seed 4.3 -> fingerprint -> update -> verify -> rollback -> fingerprint must MATCH -> update again
#
# The fingerprint comparison is the point: a rollback that runs without error but comes back
# with different data is worse than no rollback at all, because it looks like it worked.
#
# Exit code is the verdict.

set -uo pipefail

PG=${PG:-hia-local-postgres}
DB=${DB:-batchmig_rt}
NET=${NET:-local-stack_default}
SP=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CHANGELOG_DIR=${CHANGELOG_DIR:-$(cd "$SP/../assets" && pwd)}
CHANGELOG=${CHANGELOG:-changelog-batch-4.3-to-5.0.xml}
LB_IMAGE=${LB_IMAGE:-liquibase/liquibase:4.25}

WORK=${WORK:-$(mktemp -d)}
trap '[ -n "${KEEP_WORK:-}" ] || rm -rf "$WORK"' EXIT

fail() { echo "ECHEC: $*" >&2; echo "       traces: $WORK (KEEP_WORK=1 pour les garder)" >&2; exit 1; }

psql_q() { docker exec "$PG" psql -U hia -d "$DB" -tAF'|' -c "$1"; }

# The whole history, in a stable order: parameters with their values and types, and the step
# times. Anything the migration touches has to come back byte for byte.
fingerprint() {
  psql_q "SELECT job_execution_id, type_cd, key_name, coalesce(string_val,'~'),
                 coalesce(long_val::text,'~'), coalesce(double_val::text,'~'),
                 coalesce(date_val::text,'~'), identifying
          FROM batch_job_execution_params ORDER BY job_execution_id, key_name"
  psql_q "SELECT step_execution_id, start_time, coalesce(end_time::text,'~'), status
          FROM batch_step_execution ORDER BY step_execution_id"
  psql_q "SELECT job_execution_id, create_time, status, coalesce(job_configuration_location,'~')
          FROM batch_job_execution ORDER BY job_execution_id"
}

liquibase() {
  docker run --rm --network "$NET" \
    -v "$CHANGELOG_DIR":/liquibase/changelog:ro \
    -v "$WORK/lb-rt.properties":/liquibase/lb.properties:ro \
    "$LB_IMAGE" --defaults-file=/liquibase/lb.properties "$@" > "$WORK/lb-last.log" 2>&1
}

cat > "$WORK/lb-rt.properties" <<EOF
url: jdbc:postgresql://$PG:5432/$DB
username: hia
password: hia
changeLogFile: $CHANGELOG
searchPath: /liquibase/changelog
logLevel: warning
EOF

echo "== 1. base jetable + historique 4.3 seme =="
docker exec "$PG" psql -U hia -d postgres -q -tAc "DROP DATABASE IF EXISTS $DB;" >/dev/null 2>&1
docker exec "$PG" psql -U hia -d postgres -q -tAc "CREATE DATABASE $DB;" >/dev/null 2>&1 \
  || fail "creation de la base"
docker cp "$SP/seed-4.3-history.sql" "$PG:/tmp/seed-rt.sql" >/dev/null
docker exec "$PG" psql -U hia -d "$DB" -q -v ON_ERROR_STOP=1 -f /tmp/seed-rt.sql >/dev/null 2>&1 \
  || fail "semis de l historique 4.3"
echo "   $(psql_q "SELECT count(*) FROM batch_job_execution_params") parametres, $(psql_q "SELECT count(*) FROM batch_step_execution") steps"

echo "== 2. empreinte AVANT =="
fingerprint > "$WORK/fp-before.txt" || fail "empreinte avant"
echo "   $(wc -l < "$WORK/fp-before.txt") lignes d etat capturees"

echo "== 3. migration 4.3 -> 5.0 =="
liquibase update || { tail -5 "$WORK/lb-last.log"; fail "liquibase update"; }
# Counted in databasechangelog, not in the log: the log's INFO lines disappear with the log
# level, and a count that depends on verbosity is not a measurement.
RAN=$(psql_q "SELECT count(*) FROM databasechangelog WHERE filename LIKE '%$CHANGELOG'")
echo "   changesets enregistres: $RAN"
[ "$RAN" -eq 11 ] || fail "11 changesets attendus, $RAN enregistres"

echo "== 4. le modele 5.0 tient, donnees comprises =="
DB="$DB" python3 -I "$SP/verify-5.0-migration.py" > "$WORK/verify-after-update.txt" 2>&1
VERDICT=$(grep -E "^== [0-9]+/[0-9]+ vert ==$" "$WORK/verify-after-update.txt" | tail -1)
echo "   $VERDICT"
grep -q "14/14 vert" "$WORK/verify-after-update.txt" || { cat "$WORK/verify-after-update.txt"; fail "assertions 5.0"; }

echo "== 5. retour arriere des 11 changesets =="
liquibase rollbackCount 11 || { tail -15 "$WORK/lb-last.log"; fail "liquibase rollbackCount"; }
LEFT=$(psql_q "SELECT count(*) FROM databasechangelog WHERE filename LIKE '%$CHANGELOG'")
echo "   changesets restants dans databasechangelog: $LEFT"
[ "$LEFT" -eq 0 ] || fail "le rollback a laisse $LEFT changesets enregistres"

echo "== 6. empreinte APRES retour arriere, comparee a l originale =="
fingerprint > "$WORK/fp-after.txt" || fail "empreinte apres"
if diff -u "$WORK/fp-before.txt" "$WORK/fp-after.txt" > "$WORK/fp-diff.txt"; then
  echo "   IDENTIQUE: l historique 4.3 est revenu a l identique ($(wc -l < "$WORK/fp-after.txt") lignes)"
else
  echo "   --- ecarts ---"; cat "$WORK/fp-diff.txt"
  fail "le retour arriere n a pas restitue les memes donnees"
fi

echo "== 7. on remigre, pour montrer que l aller-retour est rejouable =="
liquibase update || { tail -5 "$WORK/lb-last.log"; fail "second update"; }
DB="$DB" python3 -I "$SP/verify-5.0-migration.py" > "$WORK/verify-after-replay.txt" 2>&1
grep -q "14/14 vert" "$WORK/verify-after-replay.txt" || { tail -5 "$WORK/verify-after-replay.txt"; fail "assertions apres rejeu"; }
echo "   14/14 a nouveau"

echo
echo "== ALLER-RETOUR PROUVE =="
echo "   4.3 seme -> 5.0 (14/14) -> 4.3 restitue a l identique -> 5.0 (14/14)"
