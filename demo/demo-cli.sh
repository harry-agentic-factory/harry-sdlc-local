#!/usr/bin/env bash
# Démo autonome du CLI `sdlc` (harry-sdlc-local) — à projeter devant des collègues.
# Crée un projet DEMO jetable + 2 mini-repos git, déroule un tour guidé, puis REMET TOUT À ZÉRO.
# Ne touche NI tes vrais projets NI la prod. Rejouable à volonté.
#
#   ./demo/demo-cli.sh            # pauses entre chaque section (parle, puis [entrée])
#   PAUSE=0 ./demo/demo-cli.sh    # d'une traite (répétition / CI)
#
# Prérequis : la commande `sdlc` installée (make install), git, python3.
set -euo pipefail

PAUSE="${PAUSE:-1}"
SANDBOX="$(mktemp -d)/sdlc-demo"
DATA="$SANDBOX/demo-sdlc-local"
REG="$HOME/.claude/sdlc/projects.json"

c_h=$'\033[1;36m'; c_say=$'\033[2m'; c_cmd=$'\033[1;33m'; c_ok=$'\033[1;32m'; c_r=$'\033[0m'
banner(){ printf '\n%s══════ %s ══════%s\n' "$c_h" "$1" "$c_r"; }
say(){ printf '%s» %s%s\n' "$c_say" "$1" "$c_r"; }
run(){ printf '%s$ %s%s\n' "$c_cmd" "$*" "$c_r"; eval "$*"; }
pause(){ [ "$PAUSE" = 1 ] && { printf '%s   [entrée pour continuer]%s ' "$c_say" "$c_r"; read -r _; } || true; }

cleanup(){
  # retire le worktree éventuel, désenregistre DEMO du registre, supprime le sandbox jetable
  git -C "$SANDBOX/app-repo" worktree prune 2>/dev/null || true
  [ -f "$REG" ] && python3 - "$REG" <<'PY' 2>/dev/null || true
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d.get("projects",{}).pop("DEMO",None)
json.dump(d,open(p,"w"),indent=2,ensure_ascii=False); open(p,"a").write("\n")
PY
  rm -rf "$(dirname "$SANDBOX")"
  printf '\n%s✓ démo nettoyée (projet DEMO désenregistré, sandbox supprimé)%s\n' "$c_ok" "$c_r"
}
trap cleanup EXIT

# ── prépare 2 mini-repos de code + un mini "brain" (le décor) ──
mkdir -p "$SANDBOX"/{app-repo,web-repo,demo-brain}
for r in app-repo web-repo; do
  git -C "$SANDBOX/$r" init -q -b main
  git -C "$SANDBOX/$r" -c user.email=demo@demo -c user.name=demo commit -q --allow-empty -m init
done
echo "# Demo brain" > "$SANDBOX/demo-brain/README.md"

clear 2>/dev/null || true
printf '%sDémo — CLI sdlc (harness SDLC local « Harry »)%s\n' "$c_h" "$c_r"
say "Le CLI gère l'ÉTAT du SDLC (tickets, statuts, dépendances) et prépare le terrain des agents."

banner "1) Un projet = un repo DATA (l'engine est agnostique)"
say "init-project crée le repo data + le manifest, et l'enregistre dans le registre."
run sdlc init-project DEMO --path "'$DATA'" --repos app-repo,web-repo
# on pointe reposRoot sur nos repos + un brain (normalement déjà rempli à la main dans le manifest)
python3 - "$DATA/sdlc.config.json" "$SANDBOX" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["reposRoot"]=sys.argv[2]; d["brain"]="demo-brain"
json.dump(d,open(p,"w"),indent=2,ensure_ascii=False); open(p,"a").write("\n")
PY
run sdlc projects
pause

banner "2) La state-machine + le DAG (le garde-fou)"
say "Un épic, 2 stories — dont une qui DÉPEND de l'autre (cross-repo)."
run "sdlc --project DEMO create-epic DEMO-PAY 'Tunnel de paiement'"
run "sdlc --project DEMO create-ticket DEMO-PAY DEMO-PAY-2 'socle paiement' --repos app-repo"
run "sdlc --project DEMO create-ticket DEMO-PAY DEMO-PAY-1 'page paiement' --deps DEMO-PAY-2 --repos web-repo"
say "Le DAG sait quoi faire en premier (la story sans dépendance) :"
run sdlc --project DEMO next DEMO-PAY
pause
say "La state-machine REFUSE un saut d'étape illégal (draft → done) :"
run "sdlc --project DEMO set-status DEMO-PAY-2 done || echo '   ↑ refusé : le statut n'\''est pas un champ libre'"
say "…mais accepte une transition valide :"
run sdlc --project DEMO set-status DEMO-PAY-2 spec_func
pause

banner "3) Le manifest résolu (ce que LISENT les agents)"
say "sdlc config = la carte du projet en chemins absolus. Les agents la lisent au lieu de deviner l'infra."
run sdlc --project DEMO config
pause

banner "4) La bulle scopée d'un agent (isolation + droits)"
say "sdlc workspace génère, pour un ticket : un worktree isolé + un settings.json aux droits minimaux."
run sdlc --project DEMO workspace DEMO-PAY-2 --branch feat/DEMO-PAY-2
say "Le settings.json n'autorise QUE le worktree + le brain + la data (fini le home-grant global) :"
run "cat '$SANDBOX/_agentws/DEMO/DEMO-PAY-2/.claude/settings.json'"
say "Le worktree isolé, côté git (branche du ticket, copie de travail dédiée) :"
run "git -C '$SANDBOX/app-repo' worktree list"
say "Idempotent : relancer réutilise le worktree existant (git interdit un 2e checkout d'une branche) :"
run "sdlc --project DEMO workspace DEMO-PAY-2 --branch feat/DEMO-PAY-2 | python3 -c 'import sys,json; print(\"  worktree réutilisé:\", json.load(sys.stdin)[\"worktrees\"])'"
say "Au merge sur la branche de référence, 'sdlc worktree-clean <STORY>' retire worktree + bulle"
say "(les commits, eux, survivent — c'est une copie de travail, pas du code). On nettoie tout à la fin."
pause

banner "5) Et le travail lui-même ?"
say "Le CLI gère l'ÉTAT. Le TRAVAIL (review, deploy, recette, fix) est fait par des AGENTS,"
say "orchestrés par les workflows run-ticket, qui matérialisent justement cette bulle en phase Prepare."
say "Preuve réelle : le recetteur a validé une story sur une API de prod — 8/8 critères d'acceptation."
echo
printf '%sFin de la démo — tout va être remis à zéro automatiquement.%s\n' "$c_ok" "$c_r"
pause
