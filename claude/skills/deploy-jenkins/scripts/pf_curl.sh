#!/usr/bin/env bash
# pf_curl.sh — port-forward BORNÉ + curl + kill. Ne bloque JAMAIS (le port-forward est
# une commande bloquante par nature → ici il est backgroundé, sondé, puis tué).
# Usage : pf_curl.sh <ns> <deploy> <containerPort> <path> [curl_opts...]
#   ex : pf_curl.sh hia-tenant hia-back-tenant-ht 8088 /actuator/health
#   ex : pf_curl.sh hia-tenant hia-back-tenant-ht 8088 /api/v1/enrollment-settings -H "Authorization: Bearer $TOK"
# Sortie : le corps de la réponse + une dernière ligne `__HTTP__<code>`. Toujours nettoyé.
set -uo pipefail
NS="${1:?ns}"; DEP="${2:?deploy}"; PORT="${3:?containerPort}"; PATHQ="${4:?path}"; shift 4
LP=$(( (RANDOM % 2000) + 18000 ))   # port local aléatoire

# port-forward en tâche de fond
kubectl -n "$NS" port-forward "deploy/$DEP" "$LP:$PORT" >/dev/null 2>&1 &
PF=$!
cleanup(){ kill "$PF" 2>/dev/null; wait "$PF" 2>/dev/null; }
trap cleanup EXIT

# attente BORNÉE que le port réponde (max ~10s)
up=0
for _ in $(seq 1 20); do
  if curl -s -o /dev/null -m 2 "http://127.0.0.1:$LP/actuator/health" 2>/dev/null \
     || curl -s -o /dev/null -m 2 "http://127.0.0.1:$LP$PATHQ" 2>/dev/null; then up=1; break; fi
  sleep 0.5
done
if [ "$up" != "1" ]; then echo "__HTTP__000"; echo "[pf_curl] port-forward KO (deploy/$DEP:$PORT)" >&2; exit 1; fi

# requête bornée (-m 15)
curl -s -m 15 -w $'\n__HTTP__%{http_code}' "$@" "http://127.0.0.1:$LP$PATHQ" 2>/dev/null
echo
