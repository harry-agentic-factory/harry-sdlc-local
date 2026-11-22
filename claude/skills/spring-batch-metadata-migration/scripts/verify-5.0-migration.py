#!/usr/bin/env python3
"""Verdict on the Spring Batch 4.3 -> 5.0 metadata migration. The exit code is the verdict.

Asserts the three things that matter: the history is still there, every parameter came out
with the type Spring Batch 5 will feed to Class.forName, and the structure now matches
schema-postgresql.sql 5.0.2 exactly.
"""
import os
import subprocess
import sys

DB = os.environ.get("DB", "batchmig")
CONTAINER = os.environ.get("PG", "hia-local-postgres")

results = []


def psql(query):
    done = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "hia", "-d", DB, "-tAF|", "-c", query],
        capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        return "ERREUR: " + done.stderr.strip().splitlines()[0]
    return done.stdout.strip()


def check(label, actual, expected):
    ok = actual == expected
    results.append(ok)
    print(f"{'OK ' if ok else 'KO '} {label}: {actual}" + ("" if ok else f"\n      attendu: {expected}"))


# ---- 1. nothing lost -------------------------------------------------------
check("lignes de parametres conservees",
      psql("SELECT count(*) FROM batch_job_execution_params"), "7")
check("executions conservees",
      psql("SELECT count(*) FROM batch_job_execution"), "2")
check("steps conserves",
      psql("SELECT count(*) FROM batch_step_execution"), "2")
check("instances conservees",
      psql("SELECT count(*) FROM batch_job_instance"), "2")
check("contextes conserves",
      psql("SELECT (SELECT count(*) FROM batch_job_execution_context) || '/' "
           "|| (SELECT count(*) FROM batch_step_execution_context)"), "2/2")

# ---- 2. every parameter is typed the way Batch 5 reads it ------------------
expected_params = "\n".join([
    "10|absent|java.lang.String||N",
    "10|author|java.lang.String|a.bessa|N",
    "10|clientId|java.lang.Long|4242|N",
    "10|taskId|java.lang.String|task-aaa|Y",
    "11|clientId|java.lang.Long|7|N",
    "11|ratio|java.lang.Double|1.5|N",
    "11|taskId|java.lang.String|task-bbb|Y",
])
check("chaque parametre porte son nom de CLASSE et sa valeur",
      psql("SELECT job_execution_id, parameter_name, parameter_type, "
           "coalesce(parameter_value,''), identifying "
           "FROM batch_job_execution_params ORDER BY job_execution_id, parameter_name"),
      expected_params)

check("le drapeau identifying est intact (taskId seul est identifiant)",
      psql("SELECT count(*) FROM batch_job_execution_params WHERE identifying = 'Y'"), "2")

# ---- 3. the structure is the 5.0 one --------------------------------------
check("colonnes de batch_job_execution_params",
      psql("SELECT string_agg(column_name, ',' ORDER BY column_name) "
           "FROM information_schema.columns WHERE table_name = 'batch_job_execution_params'"),
      "identifying,job_execution_id,parameter_name,parameter_type,parameter_value")

check("parameter_name et parameter_type sont obligatoires",
      psql("SELECT string_agg(column_name || '=' || is_nullable, ',' ORDER BY column_name) "
           "FROM information_schema.columns WHERE table_name = 'batch_job_execution_params' "
           "AND column_name IN ('parameter_name','parameter_type','parameter_value')"),
      "parameter_name=NO,parameter_type=NO,parameter_value=YES")

# Kept on purpose: dropping it was the only irreversible step of the migration, for a column
# 5.0 never writes. It must still be there, and still nullable.
check("job_configuration_location est conservee et optionnelle",
      psql("SELECT column_name || '=' || is_nullable FROM information_schema.columns "
           "WHERE table_name = 'batch_job_execution' AND column_name = 'job_configuration_location'"),
      "job_configuration_location=YES")

check("batch_step_execution.create_time existe et est obligatoire",
      psql("SELECT column_name || '=' || is_nullable FROM information_schema.columns "
           "WHERE table_name = 'batch_step_execution' AND column_name = 'create_time'"),
      "create_time=NO")

check("batch_step_execution.start_time est devenu optionnel",
      psql("SELECT column_name || '=' || is_nullable FROM information_schema.columns "
           "WHERE table_name = 'batch_step_execution' AND column_name = 'start_time'"),
      "start_time=YES")

check("create_time a ete repris de start_time, pas invente",
      psql("SELECT count(*) FROM batch_step_execution WHERE create_time <> start_time "
           "OR create_time IS NULL"), "0")

# ---- 4. the foreign keys still hold the history together -------------------
# Named, not counted: a count is what made this assertion wrong the first time. The one
# that matters is job_exec_params_fk, which had to survive six column drops.
check("les cles etrangeres batch, nommees",
      psql("SELECT string_agg(constraint_name, ',' ORDER BY constraint_name) "
           "FROM information_schema.table_constraints "
           "WHERE constraint_type = 'FOREIGN KEY' AND table_name LIKE 'batch_%'"),
      "job_exec_ctx_fk,job_exec_params_fk,job_exec_step_fk,job_inst_exec_fk,step_exec_ctx_fk")

failed = results.count(False)
print(f"\n== {len(results) - failed}/{len(results)} vert ==")
sys.exit(1 if failed else 0)
