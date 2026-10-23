Ferme la journée du flux bugs : commit, push et MR de la branche du jour du dépôt data : $ARGUMENTS

Tu es le **Scrum Master** du flux bugs. Tout ce que le flux a écrit dans la SDLC aujourd'hui vit sur la branche
`bugs/<YYYY-MM-DD>` du dépôt data (`sdlc config` → `workspace`). Cette commande la ferme.

`$ARGUMENTS` (optionnel) : la date de la branche, sinon celle d'aujourd'hui. Préfixe : `sdlc projects`.

1. Vérifie que le dépôt data est sur `bugs/<date>`. Sinon, arrête-toi et dis sur quoi il est.
2. `git status` : commite ce qui relève du flux bugs du jour (épics `<PREFIX>-BUG-<date>*`, leurs livrables,
   `post-mortem.jsonl` s'il a bougé) — `chore(bugs): close <date>`. `_tracker/` est ignoré, c'est normal. Tout
   autre fichier modifié : montre-le et demande, ne l'embarque pas.
3. Résume la journée en 5 lignes au plus : cartes instruites, revue signée, épic et stories (statuts), cartes
   déplacées sur le tracker (`/bugs-push`), ce qui reste ouvert.
4. **Sur accord** : `git push -u origin bugs/<date>`, puis la MR/PR vers `main` avec ce résumé (outil de la forge
   du dépôt data). Pas de merge automatique : le merge est un geste humain.

## Sortie

Branche, commits, lien de la MR, et ce qui reste ouvert pour demain (cartes `new`/`instructed`, stories en cours).
