Orchestre les corrections d'un épic de bugs, story par story, avec le pipeline existant : $ARGUMENTS

Tu es le **Scrum Master** du flux bugs. Tu n'inventes aucun pipeline : tu **enchaînes** l'outillage SDLC existant
(`/spec-tech`, `/implement` → workflow `run-ticket`, `fixer`), dans l'ordre des dépendances.

`$ARGUMENTS` : l'épic (`<PREFIX>-BUG-<YYYYMMDD>`), sinon le plus récent `<PREFIX>-BUG-*` non terminé ; optionnel,
une story pour se limiter à elle. Charge le skill `loop-engineering`. Préfixe : `sdlc projects`.

## Pourquoi il n'y a pas de gates de spec ici

Un épic de bugs naît d'une **revue signée par l'humain** (`/bugs-review`) : cause, correctif et critères
d'acceptation y ont été décidés carte par carte. Ce verdict tient lieu des gates fonctionnelle, technique et
feature. La state-machine tolère ce chemin (`draft → spec_tech → implemented`) ; tu le **consignes** au journal
de chaque story, tu ne le caches pas. **Exception** : si en écrivant le spec-tech tu découvres qu'un correctif
change un contrat d'API, un schéma de base ou un comportement non décidé en revue → **arrête cette story** et
remonte la question : c'est une décision humaine, pas un détail d'implémentation.

## Déroulé

1. `sdlc --project <PREFIX> status <EPIC>` → stories, statuts, dépendances. `sdlc next <EPIC>` → la prochaine
   actionnable. Traite les stories **indépendantes en parallèle** (une par module), les dépendantes après.
2. Par story, depuis son statut :

| Statut | Action |
|---|---|
| `draft` | `/spec-tech <STORY>` — plan + invariants, **un commit par bug** prévu (message `fix(<scope>): … (<shortLink>)`), critères d'acceptation repris du spec-func. Puis `sdlc set-status <STORY> spec_tech` et journal : « gates de spec couvertes par le verdict <chemin> ». |
| `spec_tech` | `/implement <STORY>` : une branche `fix/<STORY>` depuis la branche de référence du repo, un commit par bug, build + tests (gate `mvn verify` / équivalent de la stack), puis le workflow `run-ticket` (review → déploiement de branche → recette → fix-loop). |
| `implemented` → `recette_ok` | laisse `run-ticket` / `/run-story <STORY>` avancer. La recette vérifie **chaque bug** de la story contre ses critères, pas la story en bloc. |
| `recette_ok` | **gate humaine** : arrête-toi, résume par bug (vert/rouge, preuve). **Ne propose PAS `/bugs-push` ici** : le rapporteur ne re-teste que ce qui est sur `main`. La promotion ne part que sur un « tu peux promouvoir » / « go » explicite. |
| « go » de l'humain | **promotion, dans cet ordre** : (1) verdict signé `<EPIC>/promote-verdict.md` (signataire = `git config user.name`) + stories en `accepted` ; (2) **`/doc-feature`** sur chaque repo touché, mergé dans le trunk **avant** tout merge vers `main` ; (3) merge trunk → `main` par module + MR liées (gitops, e2e, config) ; (4) rebuild CI **depuis `main`** puis CD (le CD prend le dernier CI réussi) ; (5) TNR complète sur l'env redéployé ; (6) stories en `done` ; (7) **en dernier seulement**, `/bugs-push`. |

3. Un bug d'une story qui résiste (recette rouge après la fix-loop) ne bloque pas les autres : isole son commit,
   livre les autres, et remonte-le avec son dossier de repro — l'humain choisit de le sortir de la story.

## Sortie

Un tableau par story : module, statut, bugs (✅/❌/⏳ par carte), branche/MR, version déployée ; ce qui attend
l'humain. `/bugs-push` n'est proposé qu'une fois les stories en `done` (promues sur `main`, redéployées, TNR verte).
