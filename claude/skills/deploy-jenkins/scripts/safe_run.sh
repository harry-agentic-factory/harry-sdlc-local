#!/usr/bin/env bash
# safe_run.sh — exécute une commande BORNÉE dans le temps (jamais de hang).
# Usage : safe_run.sh <timeout_sec> -- <commande...>
# Retour : le code de sortie de la commande ; 124 si TIMEOUT (comme GNU timeout).
# Portable macOS/Linux (pas de dépendance à `timeout` GNU) : background + watchdog.
#
# À utiliser pour TOUTE op potentiellement bloquante (kubectl, poll réseau, mvn, npm, curl long)
# → l'agent ne se fige jamais sur un appel bloqué.
#
# ⚠️ Tue le GROUPE DE PROCESSUS, pas seulement le PID direct. Sinon un enfant survivant (ex. le
#    plugin exec `kubelogin` lancé par kubectl quand le token AKS a expiré) garde le pipe ouvert →
#    un `safe_run ... | grep | head` reste bloqué MALGRÉ le timeout (incident vécu : deployer figé
#    ~20 min alors que le timeout valait 40s — kubectl tué mais kubelogin orphelin tenait le pipe).
# ⚠️ Le pipe échappe au bornage : `safe_run 40 -- kubectl ... | grep` ne borne QUE kubectl. Pour
#    borner toute une PIPELINE, enveloppe-la : `safe_run 40 -- bash -c 'kubectl ... | grep | head'`.
set -uo pipefail
TO="${1:?usage: safe_run.sh <timeout_sec> -- <cmd...>}"; shift
[ "${1:-}" = "--" ] && shift

set -m                       # job control → la commande de fond démarre dans SON groupe de procs (PGID=PID)
"$@" &
CMD=$!

# Envoie <sig> au GROUPE (-PID) si possible, sinon au PID seul (fallback).
kill_tree() { kill -"$1" -"$CMD" 2>/dev/null || kill -"$1" "$CMD" 2>/dev/null || true; }

(
  # watchdog : TERM (groupe) à TO, KILL (groupe) à TO+3
  sleep "$TO" 2>/dev/null
  kill_tree TERM
  sleep 3 2>/dev/null
  kill_tree KILL
  echo "[safe_run] TIMEOUT ${TO}s -> groupe de processus tué" >&2
) &
WD=$!

wait "$CMD" 2>/dev/null
rc=$?
# stoppe le watchdog s'il n'a pas encore frappé
kill "$WD" 2>/dev/null
wait "$WD" 2>/dev/null
# balaie un éventuel reliquat du groupe (enfant orphelin qui tiendrait un pipe ouvert)
kill_tree KILL

# 143 = SIGTERM (tué par watchdog) -> normalise en 124 (timeout)
[ "$rc" = "143" ] && rc=124
exit "$rc"
