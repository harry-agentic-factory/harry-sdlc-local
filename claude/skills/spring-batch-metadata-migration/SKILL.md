---
name: spring-batch-metadata-migration
description: Migrating the Spring Batch BATCH_* metadata tables (4.3 → 5.x) while KEEPING the existing history, and understanding how job parameters are persisted. Load this whenever a Spring Boot 2 → 3 migration touches Spring Batch, whenever someone proposes to drop and recreate the batch tables, or whenever a job parameter is read back wrong, missing or throws after an upgrade. Covers the parameter persistence model (PARAMETER_TYPE is a fully qualified class name), the data loss built into Spring's own migration scripts, the Liquibase in-place migration pattern, and how to prove the migration on a seeded history rather than on an empty table.
---

# Spring Batch metadata: parameter persistence and model migration

## The one thing to know

**Spring ships the new schema. Spring does not migrate your data.** Worse: the migration
scripts bundled in `spring-batch-core` (`org/springframework/batch/core/migration/5.0/`)
convert the **structure** and **destroy the content** — silently, with exit code 0.

Measured on a seeded 4.3 history (7 parameters, 2 executions), applying the official
`migration-postgresql.sql` of `spring-batch-core:5.0.2`:

| Parameter | Before | After the official script |
|---|---|---|
| `taskId` (STRING `task-aaa`) | `task-aaa` | `task-aaa` — survives |
| `clientId` (LONG `4242`) | `4242` | **NULL — lost** |
| `ratio` (DOUBLE `1.5`) | `1.5` | **NULL — lost** |
| `parameter_type` of all rows | `STRING` / `LONG` / `DOUBLE` | **unchanged — and unreadable** |
| `batch_step_execution.create_time` | did not exist | **`1970-01-01` for every historical step** |

Two independent defects, both from reading the script:

1. It runs `DROP COLUMN DATE_VAL / LONG_VAL / DOUBLE_VAL`, then renames `STRING_VAL` to
   `PARAMETER_VALUE`. Every parameter that was not a String had its value in one of the
   dropped columns, so **its value is gone** and `PARAMETER_VALUE` is NULL.
2. It renames `TYPE_CD` to `PARAMETER_TYPE` **without converting the values**. In 5.x that
   column holds a *fully qualified class name*, resolved like this
   (`JdbcJobExecutionDao#getJobParameters`, 5.0.2):

   ```java
   try { parameterType = Class.forName(rs.getString("PARAMETER_TYPE")); }
   catch (ClassNotFoundException e) { throw new RuntimeException(e); }
   ```

   `Class.forName("LONG")` throws. So after the official script, **every read of the
   migrated history fails** — not a degraded value, a `RuntimeException`. The job history
   screen, `JobExplorer`, and any restart that reloads parameters all throw.

So the data migration is yours to write. This skill is how.

## Decide first: keep the history, or start empty?

| | Start empty | Migrate in place |
|---|---|---|
| Cost | drop + recreate | one changelog + its proof |
| Restartability of old executions | lost | preserved |
| Dedup of identifying parameters | lost (an old `JobInstance` can be recreated) | preserved |
| Audit / "what ran when" | lost | preserved |

Starting empty is legitimate **only** when nothing user-facing reads `BATCH_*`, no foreign
key points at it, and no operator relies on the restart history. Verify, do not assume: the
decision belongs to the product owner, and it is irreversible.

**Before deciding, measure the real table** — not the local one, which is usually empty and
therefore proves nothing:

```sql
SELECT type_cd, count(*),
       sum((string_val IS NOT NULL)::int) AS string_set,
       sum((long_val   IS NOT NULL)::int) AS long_set,
       sum((date_val   IS NOT NULL)::int) AS date_set,
       sum((double_val IS NOT NULL)::int) AS double_set
FROM batch_job_execution_params GROUP BY type_cd;
```

`type_cd` tells you which conversions you actually owe. A table with only `STRING` and
`LONG` is a 20-line changelog; one with `DATE` rows needs a decision (see below).

## The model, 4.3 → 5.x

Read `references/parameter-persistence.md` for the full detail. The three structural
differences, taken from a diff of `schema-postgresql.sql` between the two jars:

1. `BATCH_JOB_EXECUTION_PARAMS`: `TYPE_CD` + `KEY_NAME` + `STRING_VAL` + `DATE_VAL` +
   `LONG_VAL` + `DOUBLE_VAL` collapse into `PARAMETER_NAME` + `PARAMETER_TYPE` +
   `PARAMETER_VALUE`.
2. `BATCH_STEP_EXECUTION`: gains `CREATE_TIME NOT NULL`; `START_TIME` becomes nullable.
3. `BATCH_JOB_EXECUTION`: `JOB_CONFIGURATION_LOCATION` leaves the reference schema — and
   **leave it in place anyway**. It is nullable, 5.x never writes it, nothing reads it, and
   dropping it is the one step of the whole migration you cannot undo. Spring's own script
   does not drop it either.

Get them from the jars rather than from a blog post or from memory:

```bash
scripts/reference-schema-diff.sh 4.3.4 5.0.2 postgresql
```

## The conversion table you owe

`PARAMETER_TYPE` must become a class name, `PARAMETER_VALUE` its string form as the
`ConversionService` will parse it back:

| 4.3 `type_cd` | 5.x `parameter_type` | 5.x `parameter_value` |
|---|---|---|
| `STRING` | `java.lang.String` | `string_val` as-is |
| `LONG` | `java.lang.Long` | `CAST(long_val AS VARCHAR)` |
| `DOUBLE` | `java.lang.Double` | `CAST(double_val AS VARCHAR)` |
| `DATE` | `java.util.Date` | **see the trap below** |

### The DATE trap — halt, do not guess

`date_val` is a `TIMESTAMP` **without time zone**. Spring Batch 5 reads a `java.util.Date`
parameter through `StringToDateConverter`, which parses with `DateTimeFormatter.ISO_INSTANT`
— i.e. **UTC**. Converting a naive timestamp to an instant therefore shifts it by whatever
offset the writer's JVM had, and nothing in the data says what that offset was.

A migration that guesses is a migration that silently moves dates. **Stop instead**: make
the first changeset refuse to run when such a row exists, with a message that names the
decision. Nothing has been modified at that point, and the operator can convert those rows
by hand knowing the original time zone. A loud halt before any write beats a quiet shift.

The same applies to any `type_cd` the migration does not recognise.

## Procedure

1. **Drain.** Stop schedulers and triggers; no job may write metadata during the migration.
2. **Settle non-terminal executions while still on 4.3** — 5.x cannot restart a 4.3
   execution:
   ```sql
   SELECT job_execution_id, status FROM batch_job_execution
   WHERE status IN ('STARTING','STARTED','STOPPING');
   ```
   Finish or abandon them deliberately.
3. **Back up the six `BATCH_*` tables and the three sequences.** This backup *is* the
   rollback; there is no other.
4. **Run the migration as a versioned changelog**, not as a one-off script run by hand — it
   has to replay identically on every environment, and on the in-memory database of the test
   slices, so that every build replays it instead of trusting it.
   **`assets/changelog-batch-4.3-to-5.0.xml` is that changelog**, ready to adapt: 11
   changesets, each with its rollback. `references/liquibase-changelog.md` explains each
   decision; the short version:
   - new columns added nullable, then filled, then constrained — never `ADD COLUMN NOT NULL`
     on a populated table;
   - one `UPDATE` per legacy type, so the value and the class name are set together;
   - a `HALT` precondition **before the first structural change** for unmapped types;
   - a second `HALT` after filling, asserting that no row came out without a name or a type;
   - `create_time` **backfilled from `start_time`** (which was `NOT NULL` in 4.3, so it is
     the closest true instant), not from a default epoch;
   - portable changes only if the same changelog must run on PostgreSQL and on H2.
5. **Serializer**: if execution contexts were written by a non-default serializer in 4.x,
   configure the same one in 5.x or old contexts become unreadable. Check which
   `ExecutionContextSerializer` the application wires before assuming the default.
6. **Prove it on a seeded history** (next section), then on a restored copy of the real
   database, then run one real job and one deliberate fail-and-restart cycle.

## Proving it — on data, never on an empty table

A local batch table is almost always empty, and a migration that "ran successfully" on zero
rows has demonstrated nothing but valid SQL. Seed a history first:

```bash
scripts/seed-4.3-history.sql      # 4.3 layout + 7 parameters covering every type, known values
scripts/verify-5.0-migration.py   # named assertions; the exit code is the verdict
```

What the assertions must cover — and each of these has caught a real defect:

- the row counts of all six tables are unchanged (nothing dropped);
- **every parameter's value and `identifying` flag, listed explicitly**, not counted;
- `parameter_type` is a class name for every row (`java.lang.%`), never `STRING`/`LONG`;
- `job_configuration_location` is gone, `create_time` is `NOT NULL`, `start_time` is nullable;
- `create_time = start_time` for every historical row — proves it was carried, not invented;
- the foreign keys **by name**, especially the one on the parameters table, which has to
  survive six column drops.

> Assert on names, not on counts. A count passes while the wrong thing is there, and it is
> the count that will mislead you: an expected "4 foreign keys" against a real 5 reads as a
> migration defect when it is the assertion that is wrong.

Then prove **neutrality on an already-migrated database**: re-run the changelog and expect
"no changesets to execute", with the checksums unchanged. A migration you cannot re-run is a
migration you cannot deploy twice.

## The way back

Migrating a live history with no way back is a one-way door, so every changeset carries its
rollback — which is **only possible because the conversion is lossless**: `parameter_type`
and `parameter_value` rebuild `type_cd` and the typed value columns exactly. That is the
structural difference with Spring's script, which cannot be reversed at all, having dropped
the values.

```bash
liquibase rollbackCount 11
```

And prove it by a **round trip**, because a rollback that runs is not a rollback that works:

```bash
scripts/prove-round-trip.sh      # exit code is the verdict
# seed 4.3 -> fingerprint -> update -> assert -> rollback
#          -> fingerprint must MATCH -> update again -> assert again
```

The fingerprint is the whole history in a stable order — every parameter with its value,
type and `identifying` flag, the step times, the execution statuses — compared before and
after. It is what distinguishes a rollback that restored the data from one that merely
completed. On the migration this skill is drawn from, that comparison immediately caught a
column coming back empty, and that is why the changelog no longer drops
`job_configuration_location`.

Three cases cannot be reversed, all concerning rows written **after** the migration, under
5.x: a parameter value longer than the old 250-character limit, a `java.util.Date` or
`java.time.*` parameter, and a step execution with a null `start_time`. A Liquibase
precondition cannot guard a rollback, so those are runbook checks — the three `SELECT`s are
in `references/liquibase-changelog.md`.

The database backup from step 3 remains the rollback of last resort, for anything the
changelog cannot undo.

## Code-level changes that come with the same upgrade

The metadata is only half of it. `references/code-changes-4-to-5.md` covers
`JobBuilderFactory`/`StepBuilderFactory` removal, `@EnableBatchProcessing` versus
`DefaultBatchConfiguration`, the typed `JobParameter<T>` and `JobParameters` API, and the
`JobRepository`/transaction-manager wiring that no longer gets auto-supplied.

## What ships with this skill

**Tooling** — all of it was run against a real PostgreSQL before being written down here:

| File | Does |
|---|---|
| `assets/changelog-batch-4.3-to-5.0.xml` | the migration itself: 11 Liquibase changesets, each with its rollback, data conversion included, halt on the unconvertible case |
| `scripts/reference-schema-diff.sh` | ground truth from the jars: `./reference-schema-diff.sh 4.3.4 5.0.2 postgresql` prints the schema diff **and** the official migration script |
| `scripts/seed-4.3-history.sql` | a 4.3 layout with a seeded history covering every legacy type, with known values — so the migration is proven on data, not on an empty table |
| `scripts/verify-5.0-migration.py` | 14 named assertions on the migrated result; the exit code is the verdict |
| `scripts/prove-round-trip.sh` | the full proof: seed → migrate → assert → roll back → fingerprint comparison → migrate again |

The scripts assume a PostgreSQL in a container and the `liquibase/liquibase` image; the
container name, database, network and changelog are all overridable by environment variable
(`PG`, `DB`, `NET`, `CHANGELOG_DIR`, `CHANGELOG`).

**References**

- `references/parameter-persistence.md` — the persistence model both sides of the upgrade,
  and why `IDENTIFYING` is the thing you most quietly break.
- `references/official-script-damage.md` — the measured damage of Spring's own scripts.
- `references/liquibase-changelog.md` — the migration pattern and its rollback, annotated,
  with the measurement traps worth inheriting.
- `references/code-changes-4-to-5.md` — the API changes that accompany the schema change.
