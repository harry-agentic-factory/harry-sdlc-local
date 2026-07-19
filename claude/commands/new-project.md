Initialise un projet SDLC dans le harness : $ARGUMENTS

Tu es Harry. Un « projet » = un repo **data** `<projet>-sdlc-local` (couche 2) opéré par l'engine.

## Déroulé
1. **Clarifie** avec l'humain (si pas fourni) : le **PREFIX** (ex. `OTHER`), le **chemin** du repo data
   (`<parent>/<projet>-sdlc-local`), et la **liste des repos** de code du projet.
2. **Crée + enregistre** en une commande (depuis `harry-sdlc-local/tooling`) :
   ```
   python3 -m sdlc.cli init-project <PREFIX> --path <chemin> --repos repo1,repo2
   ```
   → scaffolde `sdlc.config.json` (prefix, repos, escalation, `schemaVersion`), README, `git init`, et
   **enregistre** `<PREFIX>` dans `~/.claude/sdlc/projects.json`. **L'engine ne change pas.**
3. **Vérifie** : `python3 -m sdlc.cli projects` (le nouveau projet apparaît) et
   `python3 -m sdlc.cli --project <PREFIX> list` (data vide, prête).

## Sortie
Le chemin du repo data + confirmation d'enregistrement + rappel : premier `/scope` pour créer un épic.
Onboarding possible ensuite (découverte repos/stacks) — cf. vision plateforme.
