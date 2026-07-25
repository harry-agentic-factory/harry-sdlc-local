#!/usr/bin/env bash
# safe_run.sh — exécute une commande BORNÉE dans le temps (jamais de hang).
# Usage : safe_run.sh <timeout_sec> -- <commande...>
# Retour : le code de sortie de la commande ; 124 si TIMEOUT (comme GNU timeout).
# Portable macOS/Linux (pas de dépendance à `timeout` GNU) : background + watchdog.
#
# À utiliser pour TOUTE op potentiellement bloquante (kubectl port-forward, poll réseau,
# mvn, npm, curl long) → l'agent ne se fige jamais 9h sur un appel bloqué.
set -uo pipefail
TO="${1:?usage: safe_run.sh <timeout_sec> -- <cmd...>}"; shift
[ "${1:-}" = "--" ] && shift

"$@" &
CMD=$!
(
  # watchdog : TERM à TO, KILL à TO+3
  sleep "$TO" 2>/dev/null
  kill -TERM "$CMD" 2>/dev/null
  sleep 3 2>/dev/null
  kill -KILL "$CMD" 2>/dev/null
  echo "[safe_run] TIMEOUT ${TO}s -> commande tuée" >&2
) &
WD=$!

wait "$CMD" 2>/dev/null
rc=$?
# stoppe le watchdog s'il n'a pas encore frappé
kill "$WD" 2>/dev/null
wait "$WD" 2>/dev/null

# 143 = SIGTERM (tué par watchdog) -> normalise en 124 (timeout)
[ "$rc" = "143" ] && rc=124
exit "$rc"
