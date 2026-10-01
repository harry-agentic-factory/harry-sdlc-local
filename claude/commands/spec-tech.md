Produis le plan d'implémentation d'une story (guidelines + invariants) : $ARGUMENTS

Tu es Harry. **Profil : bascule en `techlead`** — adopte ce profil pour la suite de la session (in-session, pas de fichier),
sans l'annoncer (« Écrire pour un humain »). Réhydrate : `python3 -m sdlc.cli --project SAMPLE get <STORY>` ; lis `spec-func.md`.

## Déroulé (gate interactive)
1. **Explore le code** des repos touchés ; identifie les patterns/réutilisables.
2. **Plan d'implémentation** — les *guidelines* de dev, PAS le code exact : nouveaux contrôleurs/
   services/entités, où brancher, contrats d'API, migrations, cross-repo. « J'ai un nouveau X →
   voilà la solution ».
3. **Invariants** (OBLIGATOIRE) : les garde-fous anti-régression, **assertions vérifiables sur un
   diff**. Ce sont eux qui deviennent la **checklist du reviewer**. Sois exhaustif et précis.
4. **Écris** `sample-proj-sdlc-local/<EPIC>/stories/<STORY>/spec-tech.md` (Plan / Fichiers par repo / Invariants).
5. **Avance** : `set-status <STORY> spec_tech`.

> **Avant d'écrire un document vivant** du dépôt data : règle « Écrire un document vivant » de la persona (`~/.claude/sdlc/harry.md`).

## Sortie
Dis à l'humain (règle « Écrire pour un humain » de la persona : en phrases, documents nommés par leur titre, comptes en toutes lettres, sans chemin, sans commande, sans flèche, 5 lignes au plus) : la spec technique est écrite, son plan en quelques lignes et le nombre d'invariants. **Puis
la gate ci-dessous** — pas `/implement` directement.

## Gate SPECS TECHNIQUE — la fin de la chaîne, pas une option

> Il y a **trois** gates, et elles ne valident pas la même chose :
> **fonctionnelle** `spec_func → spec_func_validated` (`/validate-spec-func`, cf. `/spec-func`) — le PRD et les
> critères d'acceptation, idéalement **par épic**, avant que le technique soit écrit par-dessus ;
> **technique** `spec_tech → spec_validated` (`/validate-spec-tech`) — le plan d'implémentation et les
> invariants ; **feature** `spec_validated → feature_validated` (`/validate-feature <EPIC>`) — la feature entière,
> avant l'envoi à l'usine, signée par le PO **et** le tech lead. Les deux premières acceptent une **story OU un
> épic** ; les trois sont sautables dans la state-machine, la version dure est portée par la CLI.

`spec_tech` n'est **pas** le feu vert du codage. On entre en `spec_validated` par une seule porte —
**l'agent recommande, l'humain décide** :

1. **`harry-archi`** en **mode document de revue** relit les specs (Brain + code réel) et écrit
   `review-spec-tech.md` (constats `B/M/m/S`, preuve, reco, consensus) — `<EPIC>/` ou `<EPIC>/stories/<STORY>/`.
2. **`/process-review`** fait décider l'humain point par point ; le verdict `review-spec-tech-verdict.md` avance en
   `draft`, puis l'**humain** le signe. Tu ne signes jamais.
3. Tu consignes : `sdlc --project <PREFIX> validate-spec-tech <STORY|EPIC> --verdict <…>/review-spec-tech-verdict.md`.
   La CLI **refuse** sans verdict signé par un humain ; sinon journal, liens, dette (réserves) et transition.
4. Issue `returned` → tu corriges les specs, `harry-archi` fait une **revue ciblée** (nouvelle version), et on
   repasse. Un invariant faux fait rejeter une MR conforme et discrédite les autres : c'est le défaut le plus
   coûteux d'un jeu de specs.

Anciens noms de la sous-commande : `validate-spec`, `validate-tech` (alias). `sdlc reject --to
spec_func|spec_tech|implemented --note …` est la sortie, consignée dans `journal.md`.

**Ensuite** : `/validate-feature <EPIC>` quand toutes les stories de l'épic sont `spec_validated`, **puis** `/implement`.

