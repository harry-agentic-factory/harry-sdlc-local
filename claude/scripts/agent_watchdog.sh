#!/usr/bin/env bash
# agent_watchdog.sh — liveness probe for background SDLC agents (mtime-based, history-aware).
#
# Why: a background agent's task-output file (its JSONL transcript) is appended to on every tool call, so its
# mtime is a liveness signal — a stale mtime means no tool call for N seconds. Learned the hard way: a deployer
# hung ~7h without being killed (nothing watched it), while a healthy deployer can legitimately sit ~10 min
# waiting on a CI build. So a flat threshold both misses real hangs and false-kills healthy long waits.
#
# Two modes:
#   1. Fixed (legacy):   agent_watchdog.sh <stale_seconds> <file...> [--dir <tasks_dir>]
#   2. History-aware:    agent_watchdog.sh --role <role> --history <file> [--floor S] [--hard-cap S]
#                                          [--factor F] <output_file...>
#
# History mode derives the staleness threshold from PAST run durations of this role (see agent_record.sh):
#   base   = p90(durations for role)            # learned "normal" length; falls back to floor if no history
#   thr    = clamp(factor * base, floor, hard-cap)
# Defaults: factor=0.5, floor=300, hard-cap=1800 (30 min). The HARD CAP is the backstop against multi-hour
# stale: a gap >= hard-cap is ALWAYS flagged (verdict HARDCAP), even if some external build claims to be
# running — a build "in progress" for 30 min+ is itself stuck. Between thr and hard-cap (verdict STALE), the
# caller MUST cross-check an external progress signal (Jenkins build building? rollout ongoing?) before killing.
#
# Output per file: "<VERDICT> gap=<s>s thr=<s>s base=<s>s <path>"  (base omitted in fixed mode).
#   VERDICT: OK | STALE | HARDCAP | MISSING
# Exit: 0 = all OK · 2 = at least one STALE/HARDCAP/MISSING · 1 = usage error.
set -euo pipefail

mtime() { if stat -f %m "$1" >/dev/null 2>&1; then stat -f %m "$1"; else stat -c %Y "$1"; fi; }

# p90 of durations for a role in the history file (empty if none).
p90_for() {
  local hist=$1 role=$2
  [ -f "$hist" ] || { echo ""; return; }
  awk -v r="$role" '$1==r && $2 ~ /^[0-9]+$/ {print $2}' "$hist" | sort -n | awk '
    {a[NR]=$1}
    END{ if(NR==0){exit} i=int(0.9*NR+0.9999); if(i<1)i=1; if(i>NR)i=NR; print a[i] }'
}
clamp() { local v=$1 lo=$2 hi=$3; [ "$v" -lt "$lo" ] && v=$lo; [ "$v" -gt "$hi" ] && v=$hi; echo "$v"; }

role="" hist="" floor=300 hardcap=1800 factor_num=1 factor_den=1 fixed_stale=""
files=()
# --- parse ---
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then fixed_stale=$1; shift; fi
while [ $# -gt 0 ]; do
  case "$1" in
    --role) role=$2; shift 2;;
    --history) hist=$2; shift 2;;
    --floor) floor=$2; shift 2;;
    --hard-cap) hardcap=$2; shift 2;;
    --factor) # accept an integer (e.g. 2) or a decimal like 0.5 / 1.5 → num/den
      case "$2" in
        *.*) frac=${2#*.}; int=${2%.*}; factor_num=$(( ${int:-0} * (10 ** ${#frac}) + 10#$frac )); factor_den=$(( 10 ** ${#frac} ));;
        *)   factor_num=$2; factor_den=1;;
      esac
      shift 2;;
    --dir) while IFS= read -r f; do files+=("$f"); done < <(find "$2" -name '*.output' 2>/dev/null); shift 2;;
    *) files+=("$1"); shift;;
  esac
done
[ ${#files[@]} -gt 0 ] || { echo "usage: agent_watchdog.sh <stale_s> <file...> | [--role R --history H] <file...>" >&2; exit 1; }

now=$(date +%s)
# resolve threshold
base=""
if [ -n "$fixed_stale" ]; then
  thr=$fixed_stale
else
  [ -n "$role" ] && [ -n "$hist" ] || { echo "history mode needs --role and --history (or use fixed <stale_s>)" >&2; exit 1; }
  base=$(p90_for "$hist" "$role")
  if [ -n "$base" ]; then raw=$(( base * factor_num / factor_den )); else raw=$floor; fi
  thr=$(clamp "$raw" "$floor" "$hardcap")
fi

any=0
for f in "${files[@]}"; do
  if [ ! -f "$f" ]; then echo "MISSING gap=- thr=${thr}s $f"; any=1; continue; fi
  gap=$(( now - $(mtime "$f") ))
  suffix="gap=${gap}s thr=${thr}s${base:+ base=${base}s} $f"
  if   [ "$gap" -ge "$hardcap" ] && [ -z "$fixed_stale" ]; then echo "HARDCAP $suffix"; any=1
  elif [ "$gap" -gt "$thr" ]; then echo "STALE $suffix"; any=1
  else echo "OK $suffix"; fi
done
[ "$any" -eq 0 ] || exit 2
exit 0
