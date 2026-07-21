---
name: recette
description: Recette (test d'acceptation) autonome d'une story sur l'env déployé, piloté par le manifest SDLC (`sdlc config` → `recette.<repo>` + `credentials`). Encode le COMMENT recetter — joindre l'env déployé, s'authentifier, piloter l'API ou Playwright vs les critères d'acceptation, anti-flaky, bundle repro. Le QUOI (critères) vient de `spec-func.md`. Générique et project-agnostic. À utiliser dès que l'agent recetteur doit valider une story déployée.
---

# Recetter une story (paramétré par le manifest)

Tu ne devines pas comment joindre l'env : tu lis les paramètres, puis tu appliques la procédure.
**QUOI tester** = les critères d'acceptation (`spec-func.md`). **COMMENT** = ce skill + le manifest.

## 1. Récupère le QUOI et le COMMENT
```bash
sdlc --project <PREFIX> get <STORY>          # repos touchés, branche, artefacts
sdlc --project <PREFIX> config               # .recette.<repo>, .credentials, .deploy.<repo>
```
- **Critères d'acceptation** = `<data>/<EPIC>/stories/<STORY>/spec-func.md` (Given/When/Then). Ta checklist.
- **Accès env** = `.recette.<repo>` s'il existe, sinon **dérive** de `.deploy.<repo>` :

| Param (`recette.<repo>`) | Rôle | Fallback |
|---|---|---|
| `tool` | `api` (backend) ou `ui` (Playwright MCP) | déduire du type de story |
| `baseUrl` | URL directe de l'env déployé | — |
| `portForward` | `<ns>/<kind>/<name>:<port>` pour un accès in-cluster | `deploy.<repo>.namespace` |
| `auth` | type de compte requis (ex. `tenant-admin`) | — |
| `health` | endpoint de santé (ex. `/actuator/health`) | — |

Si `baseUrl` absent mais `portForward` présent :
`kubectl -n <ns> port-forward <kind>/<name> <local>:<port>` → `http://localhost:<local>`.

## 2. Identité (jamais de secret exposé)
`.credentials.source` : `host` = creds ambiantes (token via le flux d'auth du projet, `curl -s -n`/kube).
Obtiens le token requis (`auth`) **sans jamais l'afficher** : mets-le dans un fichier/variable, ne
l'`echo` pas. `curl -s -n` pour ce qui lit `.netrc`. **Jamais** `-L`/`%{redirect_url}`.

## 3. Vérifie CHAQUE critère
- **api** : appelle l'endpoint, assert la réponse réelle vs le critère (structure, valeurs, filtrage,
  isolation…). **ui** : pilote `mcp__playwright__*` (navigate/snapshot/click) vs le comportement attendu.
- **Anti-flaky** : un critère qui échoue → rejoue-le **3×**. Incohérent → `flaky=true` (pas de fix-loop).
- **Résilience** : écris le résultat de chaque critère dans `acceptance.md` **au fur et à mesure**
  (append), pour ne rien perdre en cas de coupure.

## 4. Sur KO reproductible → bundle repro
Dans `<data>/<EPIC>/stories/<STORY>/repro/` : `steps.md` (séquence rejouable), `env.md` (URL/version),
`fixtures.md` (compte/ids de test, **sans secret**), la réponse/`snapshot`, le critère violé. C'est ce
que le fixer rejouera en local.

## 5. Trace + verdict
- Écris/complète `acceptance.md` (par critère : PASS/FAIL + preuve **anonymisée**) + `link <STORY>
  acceptance <chemin>`.
- **Ne change PAS le statut toi-même** : la transition (`recette_ok`) est **dictée par l'orchestration**
  (le workflow, ou Harry) — applique-la seulement si on te l'indique explicitement.
- Dernier message = JSON `{pass, repro, flaky, failed}`.

## Discipline de contexte & résilience (agent long — IMPORTANT)
Une recette enchaîne beaucoup d'appels (port-forward, token, API, kcadm…). Un agent **long et lourd en
contexte** devient **fragile aux coupures de connexion** (`Connection closed mid-response`) — la cause
n'est pas ta logique mais la **taille du contexte** ré-embarquée à chaque tour. Discipline obligatoire :

1. **Contexte maigre — ne dumpe JAMAIS une réponse entière.** Filtre à la source avec `jq`/`grep` pour ne
   garder que les champs que tu **assertes**. Ex. au lieu de coller 15 Ko de JSON :
   `curl -s "$BASE/api/..." -H @<(...) | jq '[.[] | {clientId, enabled, authFlow, receptionMode, journeyOptions}]'`.
   Vise des sorties **< ~2 Ko**.
2. **Sauve au fil de l'eau.** Dès qu'un critère est tranché, **append** son verdict + preuve à
   `acceptance.md`. Si tu es coupé, rien n'est perdu et un **resume** reprend proprement.
3. **Sous-passes si ça s'allonge.** Au-delà de ~25-30 appels d'outils, écris un **point d'avancement**
   (critères faits / restants) dans `acceptance.md` avant de continuer — un resume sait où reprendre.
4. **Anti-flaky ciblé.** Rejoue **seulement l'assertion clé** (une requête filtrée), pas tout le parcours.
5. **Réutilise les ressources.** Garde le **token** et le **port-forward** vivants ; ne les relance pas à
   chaque critère. Nettoie le port-forward à la fin.
6. **Si coupé et repris :** relis d'abord `acceptance.md` (tes résultats déjà sauvés) et **continue** au
   critère suivant — ne recommence pas de zéro.

## Fallback connaissances profondes
Spécifiques d'auth/endpoint d'un projet : le **Brain** (`.brain` du manifest) + le `CLAUDE.md` du repo.
Le manifest reste la source des **paramètres d'accès** ; le Brain, le **pourquoi/comment fin**.
