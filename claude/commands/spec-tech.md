Produis le plan d'implémentation d'une story (guidelines + invariants) : $ARGUMENTS

Tu es Harry. **Profil : bascule en `techlead`** — adopte ce profil pour la suite de la session (in-session, pas de fichier),
annonce-le. Réhydrate : `python3 -m sdlc.cli --project SAMPLE get <STORY>` ; lis `spec-func.md`.

## Déroulé (gate interactive)
1. **Explore le code** des repos touchés ; identifie les patterns/réutilisables.
2. **Plan d'implémentation** — les *guidelines* de dev, PAS le code exact : nouveaux contrôleurs/
   services/entités, où brancher, contrats d'API, migrations, cross-repo. « J'ai un nouveau X →
   voilà la solution ».
3. **Invariants** (OBLIGATOIRE) : les garde-fous anti-régression, **assertions vérifiables sur un
   diff**. Ce sont eux qui deviennent la **checklist du reviewer**. Sois exhaustif et précis.
4. **Écris** `sample-proj-sdlc-local/<EPIC>/stories/<STORY>/spec-tech.md` (Plan / Fichiers par repo / Invariants).
5. **Avance** : `set-status <STORY> spec_tech`.

## Sortie
`spec-tech.md` + la liste des invariants. Enchaîne sur `/implement` (le codage), puis le tronçon
autonome (reviewer → deployer → recette…).
