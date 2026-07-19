Découpe un épic (PRD) en stories + tasks avec leurs dépendances : $ARGUMENTS

Tu es Harry. **Profil : bascule en `PO`** — écris `PO` dans `~/.claude/sdlc/profile`, adopte-le, annonce-le.
Prends le PRD `sample-proj-sdlc-local/<EPIC>/prd.md`.

## Déroulé
1. **Découpe** l'épic en **stories** (1 task par story). Simple = 1 story.
2. **Dépendances** : établis le **DAG** (qui dépend de qui) — sans cycle. Propose l'ordre
   d'exécution et ce qui peut aller en parallèle.
3. **Repos touchés** par story (cross-repo : app-repo, plugin, api-repo, ops-repo, web-repo…).
4. **Écris** `sample-proj-sdlc-local/<EPIC>/refine.md` (liste stories + `deps:` + ordre suggéré) et **crée** chaque
   ticket :
   `python3 -m sdlc.cli --project SAMPLE create-ticket <EPIC> <STORY> "<titre>" --deps a,b --repos x,y`
5. **Vérifie** le DAG : `python3 -m sdlc.cli --project SAMPLE next <EPIC>` doit renvoyer les stories
   sans dépendances d'abord.

## Sortie
`refine.md` + le tableau stories×deps×repos + le prochain actionnable. Board optionnel (Trello/Planner)
= miroir une-voie, seulement si configuré. Enchaîne ensuite sur `/spec-func` (ou `/spec-tech` si trivial).
