#!/usr/bin/env bash
# agent_watchdog.sh — liveness probe for background SDLC agents (mtime-based).
#
# Why: a background agent's task-output file (its JSONL transcript) is appended to on every tool call,
# so its mtime is a reliable liveness signal — a stale mtime means the agent made NO tool call for N
# seconds, i.e. it is frozen (learned the hard way: a deployer hung ~7h without being killed because
# nothing actually watched its mtime). This script lets the orchestrator PING agents deterministically
# instead of eyeballing, and decide whether to TaskStop + relaunch.
#
# Usage:
#   agent_watchdog.sh <stale_seconds> <output_file> [<output_file> ...]
#   agent_watchdog.sh <stale_seconds> --dir <tasks_dir>     # scans every *.output in a tasks dir
#
# Output: one line per file — "OK <age>s <path>", "STALE <age>s <path>", or "MISSING - <path>".
# Exit code: 0 = all fresh · 2 = at least one STALE/MISSING (so a caller can branch) · 1 = usage error.
#
# Per-agent-type staleness thresholds (seconds) recommended by the agent-resilience skill:
#   deployer 600 · recetteur 600 · fixer 720 · reviewer 600 · nonreg-runner 600 · default 720
set -euo pipefail

mtime() { # portable epoch mtime (macOS BSD stat vs GNU stat)
  if stat -f %m "$1" >/dev/null 2>&1; then stat -f %m "$1"; else stat -c %Y "$1"; fi
}

[ $# -ge 2 ] || { echo "usage: agent_watchdog.sh <stale_seconds> <file...> | --dir <tasks_dir>" >&2; exit 1; }
stale=$1; shift

files=()
if [ "${1:-}" = "--dir" ]; then
  [ -n "${2:-}" ] || { echo "--dir needs a path" >&2; exit 1; }
  while IFS= read -r f; do files+=("$f"); done < <(find "$2" -name '*.output' 2>/dev/null)
  [ ${#files[@]} -gt 0 ] || { echo "no *.output files under $2" >&2; exit 1; }
else
  files=("$@")
fi

now=$(date +%s)
any_stale=0
for f in "${files[@]}"; do
  if [ ! -f "$f" ]; then echo "MISSING - $f"; any_stale=1; continue; fi
  age=$(( now - $(mtime "$f") ))
  if [ "$age" -gt "$stale" ]; then echo "STALE ${age}s $f"; any_stale=1; else echo "OK ${age}s $f"; fi
done

[ "$any_stale" -eq 0 ] || exit 2
exit 0
