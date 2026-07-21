# Démo du CLI `sdlc`

Démo **autonome et rejouable** du harness, à projeter devant une équipe. Elle crée un projet `DEMO`
jetable (+ 2 mini-repos git + un mini brain), déroule un tour guidé, puis **remet tout à zéro**
(désenregistre `DEMO`, supprime le sandbox). **Ne touche ni tes vrais projets ni la prod.**

```bash
make install            # une fois : installe la commande `sdlc`
./demo/demo-cli.sh      # pauses entre sections (tu parles, puis [entrée])
PAUSE=0 ./demo/demo-cli.sh   # d'une traite (répétition)
```

## Le fil (≈ 5 min)
1. **Un projet = un repo DATA** — `init-project` scaffolde le manifest + enregistre le projet (engine agnostique).
2. **State-machine + DAG** — dépendances entre stories, `next` = prochain actionnable, et un **saut de statut illégal est refusé** (le statut n'est pas un champ libre).
3. **Manifest résolu** — `sdlc config` = la carte du projet (chemins absolus) que **lisent les agents** au lieu de deviner l'infra.
4. **Bulle scopée** — `sdlc workspace` génère un **worktree isolé** + un `settings.json` aux **droits minimaux** (worktree + brain + data). Idempotent (réutilise le worktree).
5. **Le travail** — le CLI gère l'**état** ; le **travail** (review/deploy/recette/fix) est fait par des **agents** orchestrés par `run-ticket`, qui matérialisent cette bulle.

## Prérequis
`sdlc` installé (`make install`), `git`, `python3`.
