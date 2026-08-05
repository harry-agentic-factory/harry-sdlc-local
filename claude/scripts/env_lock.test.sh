#!/usr/bin/env bash
# env_lock.test.sh — thorough test suite for env_lock.sh. Uses a throwaway LOCK_ROOT.
# Run: bash env_lock.test.sh   → prints PASS/FAIL per case, exits non-zero if any fails.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LOCK="$HERE/env_lock.sh"
BASE="${TMPDIR:-/tmp}/env_lock_test_$$"; mkdir -p "$BASE"
pass=0; fail=0
ok(){ pass=$((pass+1)); echo "PASS  $1"; }
ko(){ fail=$((fail+1)); echo "FAIL  $1  -- $2"; }
# run <expected_rc> <substr> <desc> -- <lock args...>
run(){ local erc=$1 sub=$2 desc=$3; shift 3; [ "$1" = "--" ] && shift
  local out rc; out=$(bash "$LOCK" "$@" 2>&1); rc=$?
  if [ "$rc" != "$erc" ]; then ko "$desc" "rc=$rc exp=$erc :: $out"; return; fi
  if [ -n "$sub" ] && ! printf '%s' "$out" | grep -q "$sub"; then ko "$desc" "no '$sub' :: $out"; return; fi
  ok "$desc"; }

# ── 1) regression: acquire with a NON-EXISTENT lock root (the parent-mkdir bug) ──
export LOCK_ROOT="$BASE/fresh/deep/root"   # does not exist yet
run 0 ACQUIRED "1 acquire on missing root auto-creates parent" -- acquire e--r ownerA
# ── 2) re-entrant same owner ──
run 0 "re-entrant" "2 re-entrant acquire same owner" -- acquire e--r ownerA
# ── 3) other owner while fresh → BUSY ──
run 3 BUSY "3 other owner fresh → BUSY(3)" -- acquire e--r ownerB
# ── 4) status → HELD ──
run 3 HELD "4 status held → HELD(3)" -- status e--r
# ── 5) refresh by owner resets age ──
run 0 REFRESHED "5 refresh by owner" -- refresh e--r ownerA
# ── 6) refresh by non-owner refused ──
run 3 NOTOWNER "6 refresh non-owner refused(3)" -- refresh e--r ownerB
# ── 7) release by non-owner refused, lock persists ──
run 3 NOTOWNER "7 release non-owner refused(3)" -- release e--r ownerB
run 3 HELD "7b lock still held after refused release" -- status e--r
# ── 8) release by owner → FREE ──
run 0 RELEASED "8 release owner" -- release e--r ownerA
run 0 FREE "8b status FREE after release" -- status e--r
# ── 9) release when already free = no-op ──
run 0 FREE "9 release when free is no-op(0)" -- release e--r ownerA
# ── 10) death: ttl 1s → STALE ──
bash "$LOCK" acquire e--d deadOwner --ttl 1 >/dev/null 2>&1
sleep 2
run 4 STALE "10 dead holder → STALE(4) after ttl" -- status e--d
# ── 11) acquire on STALE does NOT auto-steal (returns 4) ──
run 4 STALE "11 acquire on stale → STALE(4), not stolen" -- acquire e--d otherOwner
# ── 12) steal reclaims stale ──
run 0 STOLEN "12 steal reclaims stale" -- steal e--d newOwner
run 3 HELD "12b held by new owner after steal" -- status e--d
# ── 13) corrupt: OLD bare dir (no meta) → STALE, recoverable ──
mkdir -p "$LOCK_ROOT/e--c"; touch -t 202001010000 "$LOCK_ROOT/e--c"   # bare dir, aged → corrupt
run 4 STALE "13 old corrupt dir (no meta) → STALE(4)" -- status e--c
# ── 13d) FRESH bare dir (winner mid-acquire) → HELD(3), NOT STALE (no steal window) ──
mkdir -p "$LOCK_ROOT/e--fresh"      # just-created bare dir simulates mkdir-before-write_meta
run 3 HELD "13d fresh bare dir (mid-acquire) → HELD(3), not steal-able" -- status e--fresh
run 0 STOLEN "13b steal recovers corrupt dir" -- steal e--c rescueOwner
run 3 HELD "13c held after recovering corrupt" -- status e--c
# ── 14) independent env-repos ──
bash "$LOCK" acquire e--A ownerX >/dev/null 2>&1
run 0 FREE "14 different env-repo is independent (FREE)" -- status e--B
# ── 15) CONCURRENCY: N parallel acquires → exactly ONE ACQUIRED ──
cenv="e--conc"; res="$BASE/conc"; mkdir -p "$res"
for i in $(seq 1 12); do ( bash "$LOCK" acquire "$cenv" "racer$i" > "$res/$i.out" 2>&1 ) & done
wait
won=$(grep -l "^ACQUIRED" "$res"/*.out 2>/dev/null | wc -l | tr -d ' ')
busy=$(grep -l "^BUSY" "$res"/*.out 2>/dev/null | wc -l | tr -d ' ')
stale=$(grep -l "^STALE" "$res"/*.out 2>/dev/null | wc -l | tr -d ' ')
# Mutual exclusion: exactly ONE winner. And NO loser may see STALE (that would open a steal-race window).
if [ "$won" = "1" ] && [ "$stale" = "0" ]; then ok "15 concurrency: 1 ACQUIRED, 0 STALE (busy=$busy) — mutual exclusion holds"; else ko "15 concurrency" "winners=$won (exp 1), stale=$stale (exp 0), busy=$busy"; fi
# ── 16) ledger records acquire/steal/release ──
led="$LOCK_ROOT/ledger.log"
if grep -q " acquire " "$led" && grep -q " steal " "$led" && grep -q " release " "$led"; then ok "16 ledger has acquire/steal/release"; else ko "16 ledger" "$(cat "$led" 2>/dev/null | tr '\n' '|')"; fi
# ── 17) re-entrant updates phase ──
bash "$LOCK" acquire e--p ownerP --phase deploy >/dev/null 2>&1
bash "$LOCK" acquire e--p ownerP --phase recette >/dev/null 2>&1
run 3 "phase=recette" "17 re-entrant updates phase" -- status e--p

echo "──────────────────────────────────────────"
echo "TOTAL: $pass passed, $fail failed"
rm -rf "$BASE" 2>/dev/null
[ "$fail" -eq 0 ]
