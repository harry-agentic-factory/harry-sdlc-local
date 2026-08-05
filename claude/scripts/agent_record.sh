#!/usr/bin/env bash
# agent_record.sh — append one finished agent-run duration to the watchdog history store.
#
# The orchestrator calls this when an agent COMPLETES, reading duration_ms from the task-notification:
#   agent_record.sh <history_file> <role> <duration_seconds>
# The store is plain "role duration_s" lines (no JSON, no timestamps → no Date dependency). The watchdog
# reads it to derive a per-role baseline (p90) so "abnormally long" is LEARNED from history, not a flat guess.
#
# Default store: ~/.claude/sdlc/agent_runs.log  (runtime data — do NOT commit; it lives outside the repo).
set -euo pipefail
[ $# -eq 3 ] || { echo "usage: agent_record.sh <history_file> <role> <duration_s>" >&2; exit 1; }
hist=$1; role=$2; dur=$3
case "$dur" in ''|*[!0-9]*) echo "duration_s must be a non-negative integer (seconds)" >&2; exit 1;; esac
mkdir -p "$(dirname "$hist")"
printf '%s %s\n' "$role" "$dur" >> "$hist"
