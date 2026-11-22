# How Spring Batch persists job parameters

Everything below was read in `spring-batch-core` 4.3.4 and 5.0.2 (classes and the bundled
`schema-*.sql`), not from documentation. Reproduce with
`scripts/reference-schema-diff.sh 4.3.4 5.0.2 postgresql`.

## 4.3 — one row, one typed column

```sql
CREATE TABLE BATCH_JOB_EXECUTION_PARAMS (
    JOB_EXECUTION_ID BIGINT NOT NULL,
    TYPE_CD     VARCHAR(6)   NOT NULL,   -- STRING | DATE | LONG | DOUBLE
    KEY_NAME    VARCHAR(100) NOT NULL,
    STRING_VAL  VARCHAR(250),
    DATE_VAL    TIMESTAMP,
    LONG_VAL    BIGINT,
    DOUBLE_VAL  DOUBLE PRECISION,
    IDENTIFYING CHAR(1)      NOT NULL
);
```

The type is a **four-value enum**, and the value lives in whichever of the four columns
matches it. The other three are NULL. `TYPE_CD` being `VARCHAR(6)` is itself the proof that
it was never meant to hold anything but those words.

## 5.x — one row, one string, and a class name

```sql
CREATE TABLE BATCH_JOB_EXECUTION_PARAMS (
    JOB_EXECUTION_ID BIGINT NOT NULL,
    PARAMETER_NAME  VARCHAR(100)  NOT NULL,
    PARAMETER_TYPE  VARCHAR(100)  NOT NULL,
    PARAMETER_VALUE VARCHAR(2500),
    IDENTIFYING     CHAR(1)       NOT NULL
);
```

`PARAMETER_TYPE` is **a fully qualified class name**, and the read path leaves no doubt
(`JdbcJobExecutionDao#getJobParameters`, 5.0.2):

```java
String parameterName = rs.getString("PARAMETER_NAME");
Class<?> parameterType = null;
try { parameterType = Class.forName(rs.getString("PARAMETER_TYPE")); }
catch (ClassNotFoundException e) { throw new RuntimeException(e); }
String stringValue = rs.getString("PARAMETER_VALUE");
Object typedValue = conversionService.convert(stringValue, parameterType);
```

Three consequences that decide how a migration must behave:

1. **A wrong `PARAMETER_TYPE` is not a degraded value, it is an exception.**
   `ClassNotFoundException` is rethrown as a `RuntimeException`, so a single bad row makes
   every read of that execution throw — the history screen, `JobExplorer`, a restart that
   reloads parameters.
2. **The value is whatever the `ConversionService` can parse back.** The write side is the
   mirror image (`conversionService.convert(value, String.class)`), so the invariant is
   round-tripping, not a fixed format.
3. The model is now **open**: any class the conversion service knows can be a parameter
   type. 5.0 already ships more of them than 4.3 had — `JobParametersBuilder` gained
   `addLocalDate`, `addLocalTime` and `addLocalDateTime`, which persist as
   `java.time.LocalDate` and friends. A migration written against the four legacy words
   stays correct, but a *validator* that whitelists four types will not.

## The date formats, and why DATE is the dangerous one

`DefaultConversionService` in the DAO is pre-loaded with these (5.0.2,
`AbstractDateTimeConverter`):

| Type | Formatter |
|---|---|
| `java.util.Date` | `DateTimeFormatter.ISO_INSTANT` |
| `java.time.LocalDate` | `ISO_LOCAL_DATE` |
| `java.time.LocalTime` | `ISO_LOCAL_TIME` |
| `java.time.LocalDateTime` | `ISO_LOCAL_DATE_TIME` |

`ISO_INSTANT` is **UTC with an offset in the text** (`2026-10-01T08:00:00Z`). The legacy
`DATE_VAL` is a `TIMESTAMP` **without** zone: it was written from a `java.util.Date` through
JDBC, in whatever zone the writing JVM had, and that zone is **not recorded anywhere**.

So converting a legacy DATE row to an instant requires knowing something the data does not
contain. Any formula picks a zone, and picking wrong moves the date silently. This is why
the changelog in `assets/` **halts** on such a row rather than converting it: the operator
knows which zone the application ran in, the migration does not.

## `IDENTIFYING`, and what you break by losing it

`IDENTIFYING` marks the parameters that take part in the `JobInstance` identity:
`BATCH_JOB_INSTANCE.JOB_KEY` is a hash of the identifying parameters, under
`UNIQUE (JOB_NAME, JOB_KEY)`. That is the mechanism that refuses to run the same job twice
with the same meaningful input, and the one that lets a failed execution be restarted
against its instance.

Drop the parameter rows, or lose `IDENTIFYING`, and the `JOB_KEY` values left in
`BATCH_JOB_INSTANCE` no longer correspond to anything readable. The uniqueness constraint
still holds, so the duplicate guard appears to work — it is only the *reason* for each
refusal that has become unexplainable. This is the failure mode that makes "drop and
recreate" look harmless in testing and bite in production.

## The rest of the model, in one table

| Table | 4.3 → 5.x |
|---|---|
| `BATCH_JOB_INSTANCE` | unchanged |
| `BATCH_JOB_EXECUTION` | `JOB_CONFIGURATION_LOCATION` leaves the reference schema (nullable, never written by 5.x) |
| `BATCH_JOB_EXECUTION_PARAMS` | restructured, see above |
| `BATCH_STEP_EXECUTION` | gains `CREATE_TIME NOT NULL`; `START_TIME` becomes nullable |
| `BATCH_STEP_EXECUTION_CONTEXT` | unchanged |
| `BATCH_JOB_EXECUTION_CONTEXT` | unchanged |
| the three sequences | unchanged on PostgreSQL |

`START_TIME` becoming nullable is the counterpart of `CREATE_TIME`: 5.x records when an
execution was *created* and leaves `START_TIME` empty until it actually starts. For rows that
ran under 4.3 there is no such distinction, so `CREATE_TIME` has to be backfilled from
`START_TIME` — the closest instant that is actually true, and non-null by the old constraint.

## Execution contexts

`BATCH_*_EXECUTION_CONTEXT` is untouched structurally, but its content is opaque: whatever
the configured `ExecutionContextSerializer` wrote. 5.0's `JdbcExecutionContextDao` defaults
to `DefaultExecutionContextSerializer`. **Check what the application actually wires** before
assuming the default on either side: a context written by one serializer and read by another
is unreadable, and that only surfaces when something tries to restart.
