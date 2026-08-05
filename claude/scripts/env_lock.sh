#!/usr/bin/env bash
# env_lock.sh — advisory, SELF-HEALING lock for a shared deploy environment (e.g. prod-integration).
#
# Why: several Claude sessions share one prod-integration env per repo ("last deploy wins"). Without
# coordination they clobber each other's runs. This gives a lightweight mutual-exclusion signal so a session
# knows whether it may deploy / take the relay.
#
# NEVER a hard block: the holder refreshes a heartbeat; if it dies, the lock goes STALE after <ttl> and ANY
# session can reclaim it (steal). Worst case on holder death = ~ttl of waiting, never forever. All sessions
# here run on the same host → a local lock dir (atomic mkdir) is real-time and race-free. Git is not used
# (latency/merge conflicts); the ledger is the audit trail.
#
# Layout: $LOCK_ROOT/<env-repo>/meta  (LOCK_ROOT default ~/.claude/sdlc/locks). Ledger: $LOCK_ROOT/ledger.log
#
# Usage:
#   env_lock.sh acquire <env-repo> <owner> [--ttl 900] [--phase deploy|recette] [--note "..."]
#        exit 0 ACQUIRED (free, or re-entrant same owner) · 3 BUSY (held & fresh) · 4 STALE (held & expired,
#        reclaimable via steal — do an external activity cross-check first).
#   env_lock.sh refresh <env-repo> <owner>            # bump heartbeat (owner only); 0 ok · 3 not owner
#   env_lock.sh release <env-repo> <owner>            # release if owner; 0 ok · 3 not owner
#   env_lock.sh status  <env-repo>                    # 0 FREE · 3 HELD · 4 STALE  (+ meta line)
#   env_lock.sh steal   <env-repo> <owner> [--ttl 900] [--phase P] [--note "..."]  # explicit reclaim (logs)
set -uo pipefail

LOCK_ROOT="${LOCK_ROOT:-$HOME/.claude/sdlc/locks}"
now_epoch() { date +%s; }
now_iso()   { date -u +%Y-%m-%dT%H:%M:%SZ; }
mval() { # read a field from a meta file: mval <file> <key>
  grep -m1 "\"$2\":" "$1" 2>/dev/null | sed -E 's/.*"'"$2"'": *"?([^",}]*)"?.*/\1/'
}
ledger() { mkdir -p "$LOCK_ROOT"; printf '%s %s %s owner=%s %s\n' "$(now_iso)" "$1" "$2" "$3" "${4:-}" >> "$LOCK_ROOT/ledger.log"; }
write_meta() { # write_meta <dir> <owner> <ttl> <phase> <note>
  cat > "$1/meta" <<EOF
{ "owner": "$2", "phase": "${4:-}", "since": "$(now_iso)", "heartbeat": "$(now_iso)",
  "heartbeat_epoch": $(now_epoch), "ttl_s": $3, "note": "${5:-}" }
EOF
}

cmd="${1:?usage: env_lock.sh <acquire|refresh|release|status|steal> <env-repo> [owner] [opts]}"; shift
env="${1:?env-repo required (e.g. prod-integration--back-tenant)}"; shift
owner=""; ttl=900; phase=""; note=""
case "$cmd" in acquire|refresh|release|steal) owner="${1:?owner required}"; shift;; esac
while [ $# -gt 0 ]; do case "$1" in
  --ttl) ttl=$2; shift 2;; --phase) phase=$2; shift 2;; --note) note=$2; shift 2;; *) shift;; esac; done

dir="$LOCK_ROOT/$env"; meta="$dir/meta"
age_of() { local hb; hb=$(mval "$meta" heartbeat_epoch); [ -n "$hb" ] && echo $(( $(now_epoch) - hb )) || echo 999999; }

case "$cmd" in
  acquire)
    if mkdir "$dir" 2>/dev/null; then write_meta "$dir" "$owner" "$ttl" "$phase" "$note"; ledger acquire "$env" "$owner" "free"; echo "ACQUIRED $env (owner=$owner)"; exit 0; fi
    cur=$(mval "$meta" owner); age=$(age_of); cttl=$(mval "$meta" ttl_s); [ -n "$cttl" ] || cttl=$ttl
    if [ "$cur" = "$owner" ]; then write_meta "$dir" "$owner" "$ttl" "${phase:-$(mval "$meta" phase)}" "$note"; echo "ACQUIRED $env (re-entrant, owner=$owner)"; exit 0; fi
    if [ "$age" -le "$cttl" ]; then echo "BUSY $env held by '$cur' phase=$(mval "$meta" phase) age=${age}s (ttl=${cttl}s) → attends ou cross-check"; exit 3; fi
    echo "STALE $env held by '$cur' age=${age}s > ttl=${cttl}s → reclaimable ('steal' après cross-check activité)"; exit 4;;
  refresh)
    [ -f "$meta" ] || { echo "FREE $env (rien à rafraîchir)"; exit 3; }
    [ "$(mval "$meta" owner)" = "$owner" ] || { echo "NOTOWNER $env owner=$(mval "$meta" owner)"; exit 3; }
    write_meta "$dir" "$owner" "$(mval "$meta" ttl_s)" "${phase:-$(mval "$meta" phase)}" "${note:-$(mval "$meta" note)}"; echo "REFRESHED $env (owner=$owner)"; exit 0;;
  release)
    [ -f "$meta" ] || { echo "FREE $env (déjà libre)"; exit 0; }
    [ "$(mval "$meta" owner)" = "$owner" ] || { echo "NOTOWNER $env owner=$(mval "$meta" owner) — release refusé"; exit 3; }
    rm -rf "$dir"; ledger release "$env" "$owner" ""; echo "RELEASED $env (owner=$owner)"; exit 0;;
  status)
    [ -f "$meta" ] || { echo "FREE $env"; exit 0; }
    cur=$(mval "$meta" owner); age=$(age_of); cttl=$(mval "$meta" ttl_s)
    if [ "$age" -le "$cttl" ]; then echo "HELD $env owner=$cur phase=$(mval "$meta" phase) age=${age}s ttl=${cttl}s"; exit 3
    else echo "STALE $env owner=$cur age=${age}s > ttl=${cttl}s (reclaimable)"; exit 4; fi;;
  steal)
    prev=""; [ -f "$meta" ] && prev=$(mval "$meta" owner)
    mkdir -p "$dir"; write_meta "$dir" "$owner" "$ttl" "$phase" "$note"; ledger steal "$env" "$owner" "from=${prev:-none}"
    echo "STOLEN $env (owner=$owner, ex='${prev:-none}')"; exit 0;;
  *) echo "commande inconnue: $cmd" >&2; exit 1;;
esac
