# Batch metadata migrator — BATCH_* tables from 4.3 to 5.0

The `BATCH_*` tables of a live system carry the restart history: they must be **migrated in
place**, never dropped/recreated, or you lose restartability and dedup of identifying
parameters. This runbook + SQL turns a v4 schema into a v5 schema with data preserved.

## Runbook (order matters)

1. **Drain**: stop all schedulers/triggers. No job may write metadata during migration.
2. **Settle v4 state**: list non-terminal executions and deal with them **while still on v4** —
   v5 cannot restart a v4 execution:
   ```sql
   SELECT JOB_EXECUTION_ID, STATUS FROM BATCH_JOB_EXECUTION
   WHERE STATUS IN ('STARTING','STARTED','STOPPING','STOPPED','FAILED');
   ```
   Restart-and-finish them, or accept they become cold history (mark ABANDONED).
3. **Backup** the six `BATCH_*` tables (+ sequences).
4. **Apply the official core script** for your platform (shipped inside spring-batch-core):
   `org/springframework/batch/core/migration/5.0/migration-<platform>.sql`
   (oracle, mssql, mysql, postgresql, …). It covers: dropping
   `BATCH_JOB_EXECUTION.JOB_CONFIGURATION_LOCATION`, adding
   `BATCH_STEP_EXECUTION.CREATE_TIME`, relaxing `START_TIME` to nullable, and the
   platform-specific sequence changes (Oracle `ORDER`ed sequences, MSSQL table-sequences →
   native sequences).
5. **Migrate the parameters table data** (the official scripts handle DDL; the data transform
   below is yours). Template (ANSI SQL, adapt types/quoting to your platform):

   ```sql
   -- 5.1 new structure alongside the old one
   CREATE TABLE BATCH_JOB_EXECUTION_PARAMS_V5 (
       JOB_EXECUTION_ID BIGINT        NOT NULL,
       PARAMETER_NAME   VARCHAR(100)  NOT NULL,
       PARAMETER_TYPE   VARCHAR(100)  NOT NULL,
       PARAMETER_VALUE  VARCHAR(2500),
       IDENTIFYING      CHAR(1)       NOT NULL,
       CONSTRAINT JOB_EXEC_PARAMS_FK5 FOREIGN KEY (JOB_EXECUTION_ID)
           REFERENCES BATCH_JOB_EXECUTION(JOB_EXECUTION_ID)
   );

   -- 5.2 one INSERT per legacy type: typed column -> (name, FQCN, string value)
   INSERT INTO BATCH_JOB_EXECUTION_PARAMS_V5
   SELECT JOB_EXECUTION_ID, KEY_NAME, 'java.lang.String', STRING_VAL, IDENTIFYING
     FROM BATCH_JOB_EXECUTION_PARAMS WHERE TYPE_CD = 'STRING';

   INSERT INTO BATCH_JOB_EXECUTION_PARAMS_V5
   SELECT JOB_EXECUTION_ID, KEY_NAME, 'java.lang.Long', CAST(LONG_VAL AS VARCHAR(2500)), IDENTIFYING
     FROM BATCH_JOB_EXECUTION_PARAMS WHERE TYPE_CD = 'LONG';

   INSERT INTO BATCH_JOB_EXECUTION_PARAMS_V5
   SELECT JOB_EXECUTION_ID, KEY_NAME, 'java.lang.Double', CAST(DOUBLE_VAL AS VARCHAR(2500)), IDENTIFYING
     FROM BATCH_JOB_EXECUTION_PARAMS WHERE TYPE_CD = 'DOUBLE';

   -- DATE: serialize to ISO-8601; v5 default converter expects a parseable representation.
   INSERT INTO BATCH_JOB_EXECUTION_PARAMS_V5
   SELECT JOB_EXECUTION_ID, KEY_NAME, 'java.util.Date',
          TO_CHAR(DATE_VAL, 'YYYY-MM-DD"T"HH24:MI:SS.FF3TZH:TZM'),  -- platform-specific
          IDENTIFYING
     FROM BATCH_JOB_EXECUTION_PARAMS WHERE TYPE_CD = 'DATE';

   -- 5.3 swap
   DROP TABLE BATCH_JOB_EXECUTION_PARAMS;
   ALTER TABLE BATCH_JOB_EXECUTION_PARAMS_V5 RENAME TO BATCH_JOB_EXECUTION_PARAMS;
   ```

   Notes:
   - verify the date format your `ConversionService` will parse back (test one row end-to-end
     before migrating millions);
   - rows with NULL values in the legacy typed column become NULL `PARAMETER_VALUE` — v5
     accepts it only for non-identifying parameters; audit
     `WHERE IDENTIFYING='Y' AND <typed column> IS NULL` first.
6. **Serializer**: if execution contexts were written with Jackson (v4 default), configure
   `JacksonExecutionContextStringSerializer` in v5 or old contexts are unreadable (new v5
   default is Base64).
7. **Validate on a copy first**: run the whole script on a dump, boot the migrated app,
   `SELECT` the params of one historical execution via `JobExplorer`, then run one real job and
   one deliberate fail-restart cycle.
8. Do **not** query v4 historical instances through `JobExplorer#getJobInstances/getJobExecution`
   expecting v4 semantics — treat pre-migration history as read-only archaeology.

## Rollback

The backup of step 3 is the rollback. The migration is a single maintenance window: restore the
six tables + sequences, repoint the old binary, restart schedulers.
