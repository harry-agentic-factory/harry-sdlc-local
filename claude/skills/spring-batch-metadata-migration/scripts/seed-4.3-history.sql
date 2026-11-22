-- Reconstitutes the Spring Batch 4.3 layout (as changelog 019 creates it) and seeds an
-- HISTORY in it, so the 5.0 migration can be proven to carry data rather than to run.
--
-- The seeded rows deliberately mirror what back-tenant really writes (taskId String
-- identifying, clientId Long, author String) PLUS a DOUBLE row to exercise the third
-- branch, and keep a known value per row so the assertions can be exact.

CREATE TABLE batch_job_instance (
    job_instance_id BIGINT NOT NULL PRIMARY KEY,
    version BIGINT,
    job_name VARCHAR(100) NOT NULL,
    job_key VARCHAR(32) NOT NULL,
    CONSTRAINT job_inst_un UNIQUE (job_name, job_key)
);

CREATE TABLE batch_job_execution (
    job_execution_id BIGINT NOT NULL PRIMARY KEY,
    version BIGINT,
    job_instance_id BIGINT NOT NULL,
    create_time TIMESTAMP NOT NULL,
    start_time TIMESTAMP DEFAULT NULL,
    end_time TIMESTAMP DEFAULT NULL,
    status VARCHAR(10),
    exit_code VARCHAR(2500),
    exit_message VARCHAR(2500),
    last_updated TIMESTAMP,
    job_configuration_location VARCHAR(2500) NULL,
    CONSTRAINT job_inst_exec_fk FOREIGN KEY (job_instance_id) REFERENCES batch_job_instance(job_instance_id)
);

CREATE TABLE batch_job_execution_params (
    job_execution_id BIGINT NOT NULL,
    type_cd VARCHAR(6) NOT NULL,
    key_name VARCHAR(100) NOT NULL,
    string_val VARCHAR(250),
    date_val TIMESTAMP DEFAULT NULL,
    long_val BIGINT,
    double_val DOUBLE PRECISION,
    identifying CHAR(1) NOT NULL,
    CONSTRAINT job_exec_params_fk FOREIGN KEY (job_execution_id) REFERENCES batch_job_execution(job_execution_id)
);

CREATE TABLE batch_step_execution (
    step_execution_id BIGINT NOT NULL PRIMARY KEY,
    version BIGINT NOT NULL,
    step_name VARCHAR(100) NOT NULL,
    job_execution_id BIGINT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP DEFAULT NULL,
    status VARCHAR(10),
    commit_count BIGINT,
    read_count BIGINT,
    filter_count BIGINT,
    write_count BIGINT,
    read_skip_count BIGINT,
    write_skip_count BIGINT,
    process_skip_count BIGINT,
    rollback_count BIGINT,
    exit_code VARCHAR(2500),
    exit_message VARCHAR(2500),
    last_updated TIMESTAMP,
    CONSTRAINT job_exec_step_fk FOREIGN KEY (job_execution_id) REFERENCES batch_job_execution(job_execution_id)
);

CREATE TABLE batch_step_execution_context (
    step_execution_id BIGINT NOT NULL PRIMARY KEY,
    short_context VARCHAR(2500) NOT NULL,
    serialized_context TEXT,
    CONSTRAINT step_exec_ctx_fk FOREIGN KEY (step_execution_id) REFERENCES batch_step_execution(step_execution_id)
);

CREATE TABLE batch_job_execution_context (
    job_execution_id BIGINT NOT NULL PRIMARY KEY,
    short_context VARCHAR(2500) NOT NULL,
    serialized_context TEXT,
    CONSTRAINT job_exec_ctx_fk FOREIGN KEY (job_execution_id) REFERENCES batch_job_execution(job_execution_id)
);

CREATE SEQUENCE batch_step_execution_seq MAXVALUE 9223372036854775807 NO CYCLE;
CREATE SEQUENCE batch_job_execution_seq MAXVALUE 9223372036854775807 NO CYCLE;
CREATE SEQUENCE batch_job_seq MAXVALUE 9223372036854775807 NO CYCLE;

-- ---------------------------------------------------------------- history

INSERT INTO batch_job_instance VALUES
    (1, 0, 'accountImportJob', 'k-import-0001'),
    (2, 0, 'accountExportJob', 'k-export-0002');

INSERT INTO batch_job_execution
    (job_execution_id, version, job_instance_id, create_time, start_time, end_time, status,
     exit_code, exit_message, last_updated, job_configuration_location)
VALUES
    (10, 2, 1, '2026-10-01 08:00:00', '2026-10-01 08:00:01', '2026-10-01 08:04:12', 'COMPLETED',
     'COMPLETED', '', '2026-10-01 08:04:12', NULL),
    (11, 2, 2, '2026-10-02 09:30:00', '2026-10-02 09:30:02', '2026-10-02 09:31:00', 'FAILED',
     'FAILED', 'boom', '2026-10-02 09:31:00', 'classpath:/x.xml');

INSERT INTO batch_job_execution_params
    (job_execution_id, type_cd, key_name, string_val, date_val, long_val, double_val, identifying)
VALUES
    (10, 'STRING', 'taskId',   'task-aaa',  NULL, NULL, NULL, 'Y'),
    (10, 'LONG',   'clientId', NULL,        NULL, 4242, NULL, 'N'),
    (10, 'STRING', 'author',   'a.bessa',   NULL, NULL, NULL, 'N'),
    (10, 'STRING', 'absent',   NULL,        NULL, NULL, NULL, 'N'),
    (11, 'STRING', 'taskId',   'task-bbb',  NULL, NULL, NULL, 'Y'),
    (11, 'LONG',   'clientId', NULL,        NULL,    7, NULL, 'N'),
    (11, 'DOUBLE', 'ratio',    NULL,        NULL, NULL, 1.5,  'N');

INSERT INTO batch_step_execution
    (step_execution_id, version, step_name, job_execution_id, start_time, end_time, status,
     commit_count, read_count, filter_count, write_count, read_skip_count, write_skip_count,
     process_skip_count, rollback_count, exit_code, exit_message, last_updated)
VALUES
    (100, 3, 'importLines', 10, '2026-10-01 08:00:03', '2026-10-01 08:04:10', 'COMPLETED',
     5, 500, 0, 500, 0, 0, 0, 0, 'COMPLETED', '', '2026-10-01 08:04:10'),
    (101, 3, 'exportRows',  11, '2026-10-02 09:30:05', '2026-10-02 09:30:58', 'FAILED',
     1, 10, 0, 0, 0, 0, 0, 1, 'FAILED', 'boom', '2026-10-02 09:30:58');

INSERT INTO batch_job_execution_context VALUES
    (10, '{"k":1}', NULL), (11, '{"k":2}', NULL);
INSERT INTO batch_step_execution_context VALUES
    (100, '{"s":1}', NULL), (101, '{"s":2}', NULL);
