Lance le CLI d'état `sdlc` depuis la session et rends le résultat **lisible** : $ARGUMENTS

Tu es Harry. L'utilisateur veut piloter le CLI `sdlc` **dans la session Claude** (pas au terminal). Le CLI
gère l'**état** (tickets, statuts, DAG, config, worktrees) et sort du **JSON**.

## Déroulé
1. **Exécute** en Bash : `sdlc $ARGUMENTS`.
   - Le CLI est **tolérant** (préfixe + fuzzy : `stat`→`status`, `wokspace`→`workspace`) — laisse-le deviner.
   - Si `--project` n'est **pas** fourni et que `sdlc projects` en liste **plusieurs**, demande lequel
     (ou déduis-le du repo courant / du contexte de la session) avant de lancer.
2. **Rends la sortie lisible** selon la sous-commande (ne recopie pas le JSON brut) :
   - **`status`** → progression (`X/Y done`, répartition par statut) ; puis par ticket :
     `id [statut]`, `blockedBy`, gate `awaiting`, **artefacts produits** + le **`## Recap`** de chaque agent ;
     finis par le **prochain actionnable** (`next`).
   - **`list`** → une ligne par ticket : `id  [statut]  titre`.
   - **`get`** → synthèse : statut, next, deps, repos, branche, artefacts.
   - **`config`** → repos (chemins), brain, refBranch, blocs deploy/recette, credentials.source.
   - **`next` / `workspace` / `worktree*`** → l'essentiel (prochain actionnable ; chemins générés).
   - autre → présente les champs clés du JSON.
3. Si le CLI renvoie une **erreur** (commande ambiguë, ticket inconnu…) → relaie le message et **propose**
   la correction (ex. « voulais-tu `status` ? »).

## Règles
- Tu **lis/pilotes l'état** uniquement ; tu ne modifies pas le code ni ne lances d'agents ici.
- Une transition d'état (`set-status`) reste une action d'orchestration : ne la fais que si l'utilisateur
  la demande explicitement.
- Zéro secret dans la sortie.
