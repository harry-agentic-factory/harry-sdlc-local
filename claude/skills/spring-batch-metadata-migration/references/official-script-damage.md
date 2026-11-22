# What Spring's own 5.0 migration script does to your data

`spring-batch-core:5.0.2` ships `org/springframework/batch/core/migration/5.0/migration-<platform>.sql`.
It is tempting to treat it as *the* migration. It is not: it migrates the **structure** and
leaves the **content** wrong, and it exits 0 while doing so.

## The script, in full (PostgreSQL)

```sql
ALTER TABLE BATCH_STEP_EXECUTION ADD CREATE_TIME TIMESTAMP NOT NULL DEFAULT '1970-01-01 00:00:00';
ALTER TABLE BATCH_STEP_EXECUTION ALTER COLUMN START_TIME DROP NOT NULL;

ALTER TABLE BATCH_JOB_EXECUTION_PARAMS DROP COLUMN DATE_VAL;
ALTER TABLE BATCH_JOB_EXECUTION_PARAMS DROP COLUMN LONG_VAL;
ALTER TABLE BATCH_JOB_EXECUTION_PARAMS DROP COLUMN DOUBLE_VAL;

ALTER TABLE BATCH_JOB_EXECUTION_PARAMS ALTER COLUMN TYPE_CD TYPE VARCHAR(100);
ALTER TABLE BATCH_JOB_EXECUTION_PARAMS RENAME TYPE_CD TO PARAMETER_TYPE;
ALTER TABLE BATCH_JOB_EXECUTION_PARAMS ALTER COLUMN KEY_NAME TYPE VARCHAR(100);
ALTER TABLE BATCH_JOB_EXECUTION_PARAMS RENAME KEY_NAME TO PARAMETER_NAME;
ALTER TABLE BATCH_JOB_EXECUTION_PARAMS ALTER COLUMN STRING_VAL TYPE VARCHAR(2500);
ALTER TABLE BATCH_JOB_EXECUTION_PARAMS RENAME STRING_VAL TO PARAMETER_VALUE;
```

Read it as a data migration and the two defects are plain: nothing moves the values out of
`DATE_VAL` / `LONG_VAL` / `DOUBLE_VAL` before they are dropped, and nothing rewrites
`TYPE_CD`'s values before it becomes `PARAMETER_TYPE`.

## Measured, not inferred

Seeded with `scripts/seed-4.3-history.sql` (7 parameters over 2 executions, covering every
legacy type, every value known), then the script above applied verbatim on PostgreSQL 14:

| `parameter_name` | before | `parameter_type` after | `parameter_value` after |
|---|---|---|---|
| `taskId` | STRING `task-aaa` | `STRING` | `task-aaa` |
| `author` | STRING `a.bessa` | `STRING` | `a.bessa` |
| `clientId` | LONG `4242` | `LONG` | **NULL** |
| `clientId` | LONG `7` | `LONG` | **NULL** |
| `ratio` | DOUBLE `1.5` | `DOUBLE` | **NULL** |

And on the step table:

| `step_execution_id` | `create_time` after | real `start_time` |
|---|---|---|
| 100 | **1970-01-01 00:00:00** | 2026-10-01 08:00:03 |
| 101 | **1970-01-01 00:00:00** | 2026-10-02 09:30:05 |

So, after the official script:

1. **Every non-String parameter value is gone.** The row survives, the name survives, the
   value is NULL.
2. **Every row carries an unresolvable type.** `PARAMETER_TYPE` holds `STRING`, `LONG`,
   `DOUBLE` — and 5.x does `Class.forName` on it, so the *next read of any execution throws
   a RuntimeException*. Not the migration: the read, later, in production.
3. **Every historical step is dated to the epoch**, because `CREATE_TIME` is filled by a
   column default rather than from `START_TIME`, which was `NOT NULL` and sitting right
   there.

Point 2 is the one that misleads: the migration succeeds, the application boots, the schema
matches the reference — and the history is unreadable. Nothing tells you until someone opens
a job's parameters or restarts something.

## What it is actually good for

The structural half is correct and worth reading: it is the authoritative list of what the
schema change *is*, per platform, including the platform-specific parts a hand-written
migration gets wrong (MSSQL's table-sequences becoming native sequences, Oracle's ordered
sequences, the H2 `TIMESTAMP(9)` widening).

Use it as a **specification of the DDL**, and write the data migration yourself. That is what
`assets/changelog-batch-4.3-to-5.0.xml` does: same structural result, plus the conversion the
script omits, plus a halt on the one case that cannot be converted without a decision, plus a
rollback — which is only possible *because* nothing was thrown away.

## Why it does not cover the data

Plausibly because there is no single right answer for `DATE_VAL` (no time zone recorded) and
no obligation on Spring to guess for you. That is a defensible position for a framework. It
is not a defensible position for your migration, and "the official script ran fine" is not a
verification. Prove it on rows: `scripts/prove-round-trip.sh`.
