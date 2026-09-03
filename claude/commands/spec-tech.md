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
`spec-tech.md` + la liste des invariants. **Puis la gate ci-dessous** — pas `/implement` directement.

## Gate SPECS TECHNIQUE — la fin de la chaîne, pas une option

> Il y a **deux** gates, et elles ne valident pas la même chose :
> **fonctionnelle** `spec_func → spec_func_validated` (`validate-func`, cf. `/spec-func`) — le PRD et les
> critères d'acceptation, idéalement **par épic**, avant que le technique soit écrit par-dessus ;
> **technique** `spec_tech → spec_validated` (`validate-spec`) — le plan d'implémentation et les
> invariants. Celle-ci est la seconde. Les deux acceptent une **story OU un épic entier**, et les deux
> sont sautables dans la state-machine : la version dure est portée par l'orchestration.

`spec_tech` n'est **pas** le feu vert du codage. L'état suivant est `spec_validated`, et on y entre par
une seule porte :

1. **`harry-archi`** relit les specs (Brain + code réel), tranche **dans son périmètre** et **escalade**
   ce qui n'y est pas (produit, sécurité, PII, relation client). Il écrit `<EPIC>/spec-review.md` et
   rend `{decision, rationale, sources, escalate}`.
2. Les escalades — **et elles seules** — remontent à l'humain.
3. Tu consignes : `sdlc --project <PREFIX> validate-spec <STORY|EPIC> --review <EPIC>/spec-review.md`.
   La commande **enregistre** un verdict rendu en amont ; elle ne valide rien par elle-même.
4. Verdict « à corriger » → tu corriges les specs et tu **repasses la gate**. Un invariant faux fait
   rejeter une MR conforme et discrédite les autres : c'est le défaut le plus coûteux d'un jeu de specs.

`sdlc reject --to spec_func|spec_tech|implemented --note …` est la sortie, consignée dans `journal.md`.

**Seulement ensuite** : `/implement`.

