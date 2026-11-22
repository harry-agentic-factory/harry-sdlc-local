# The in-place migration, as a reversible changelog

The ready-to-adapt file is `assets/changelog-batch-4.3-to-5.0.xml` — 11 changesets, each with
its rollback. This page is why it is shaped the way it is.

## Why a changelog and not a SQL script

The migration has to run identically on every environment, and on the in-memory database of
the test slices — so that **every build replays it** instead of trusting it. A script run by
hand in a maintenance window is a one-off you cannot re-verify; a changelog is a tracked,
ordered, rollback-able unit that the application itself applies at boot.

A side effect worth having: if the test slices create the 4.3 schema and then run this
changelog, the migration is exercised on every `mvn verify`, for free.

## The shape

```
batch50-01  add parameter_name / parameter_type / parameter_value, NULLABLE
            + HALT precondition: no row with an unconvertible type_cd
batch50-02  parameter_name  <- key_name                    (all rows)
batch50-03  parameter_type/value for type_cd = 'STRING'
batch50-04  ... 'LONG'
batch50-05  ... 'DOUBLE'
batch50-06  HALT if any row has a null name or type, then NOT NULL on both
batch50-07  drop the six legacy columns
batch50-08  add batch_step_execution.create_time, NULLABLE
batch50-09  create_time <- start_time
batch50-10  NOT NULL on create_time
batch50-11  drop NOT NULL on start_time
```

Five rules are doing the work:

1. **Add nullable, fill, then constrain.** `ADD COLUMN ... NOT NULL` on a populated table
   either fails or forces a default — and a default is how the official script dates every
   historical step to 1970.
2. **One `UPDATE` per legacy type**, each setting the class name *and* the value together, so
   a row cannot end up typed but valueless. It also keeps the SQL portable: no `CASE`, no
   dialect-specific function.
3. **The halt comes before the first structural change.** Liquibase evaluates a changeset's
   preconditions before executing it, and `onFail="HALT"` stops the whole update, so a
   refusal leaves the database untouched. Put that guard on `batch50-01`, not at the end.
4. **A second halt after filling**, asserting no row came out without a name or a type. The
   first guard checks the input, this one checks the work. Belt and braces, and both cheap.
5. **Backfill from real data, never from a default.** `start_time` was `NOT NULL` in 4.3, so
   it is both available and the closest true instant for a `create_time` that did not exist
   when the row was written.

## Preconditions and idempotency

Liquibase evaluates a changeset's preconditions **only while it is pending**: once recorded in
`DATABASECHANGELOG` it is skipped entirely, preconditions included. So a guard that reads
`type_cd` does not break on later runs after the column is gone — but a *file-level*
precondition would, since those are evaluated on every run. Keep the guards on the changesets.

## Portability, without `<dbms>`

If the same changelog must run on PostgreSQL and on H2 (or HSQLDB) for the test slices, stay
inside Liquibase's own change types and use only SQL that both parse:

- `CAST(x AS VARCHAR(2500))`, not `x::text`;
- `addNotNullConstraint` / `dropNotNullConstraint` with `columnDataType`, not raw `ALTER`;
- lower-case unquoted table names: Spring Batch emits unquoted SQL, which PostgreSQL folds to
  lower case and H2 to upper case, and unquoted lower case matches both;
- `clob` for `serialized_context` (TEXT on PostgreSQL, CLOB on H2).

## The rollback, and the two things it cannot bring back

The migration is reversible **because the conversion is lossless**: `parameter_type` and
`parameter_value` rebuild `type_cd` and the typed columns exactly.

```bash
liquibase rollbackCount 11
```

`batch50-07`'s rollback carries the reverse conversion (re-add the six columns, refill them
from the new ones, restore the two `NOT NULL`s). The `<update>` changesets carry an **empty
`<rollback/>`** — an `<update>` has no automatic inverse, and the empty element is what tells
Liquibase the step is reversible rather than unknown. Without it, `rollbackCount` refuses to
run at all.

Two cases do not come back, and both concern rows written **after** the migration, under 5.x:

| Case | Why | Check before rolling back |
|---|---|---|
| a parameter value longer than 250 characters | `string_val` was `VARCHAR(250)`, `parameter_value` is `VARCHAR(2500)` | `SELECT count(*) FROM batch_job_execution_params WHERE length(parameter_value) > 250` |
| a `java.util.Date` or `java.time.*` parameter | no legacy column holds it, and the DATE trap applies in reverse | `SELECT DISTINCT parameter_type FROM batch_job_execution_params` |
| a step execution with a null `start_time` | 5.x allows it, 4.3's `NOT NULL` does not | `SELECT count(*) FROM batch_step_execution WHERE start_time IS NULL` |

A Liquibase precondition cannot guard a rollback, so these are runbook checks, not changelog
guards. Run them, or accept that the rollback will fail loudly at that changeset — which is
still better than succeeding wrongly.

**Do not drop `job_configuration_location`.** Aligning the schema on the 5.0 reference by
dropping it looks tidy and is the one irreversible step in the whole migration, for a nullable
column 5.x never writes and nothing reads. Spring's own script leaves it too. This was found
by the round-trip proof, not by review: the rollback came back with the column empty.

## Proving it

`scripts/prove-round-trip.sh` does, on a throwaway database:

```
seed 4.3 → fingerprint → update → assert the 5.0 model → rollback
         → fingerprint must MATCH the first → update again → assert again
```

The fingerprint is the whole history in a stable order — every parameter with its value, type
and `identifying` flag, the step times, the execution statuses. Comparing it before and after
is the only thing that distinguishes a rollback that *worked* from one that merely *ran*: the
second kind is the dangerous one, because it looks like success.

Two measurement traps it is worth inheriting:

- **Count changesets in `DATABASECHANGELOG`, not in Liquibase's output.** Grepping
  `ran successfully` reported 0 changesets purely because the log level hid the INFO lines —
  a check whose result depends on verbosity is not a measurement.
- **Assert foreign keys by name, not by count.** An expected count that is wrong reads as a
  migration defect. The key that matters is the one on the parameters table, which has to
  survive six column drops.

Then, before the real run: replay the changelog on a **restored copy of the production
database**, and confirm neutrality on an already-migrated one (re-running must report nothing
to execute, with unchanged checksums).
