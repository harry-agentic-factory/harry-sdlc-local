---
name: recette
description: Recette (test d'acceptation) autonome d'une story sur l'env déployé, piloté par le manifest SDLC (`sdlc config` → `recette.<repo>` + `credentials`). Encode le COMMENT recetter — joindre l'env déployé, s'authentifier, piloter l'API ou Playwright vs les critères d'acceptation, anti-flaky, bundle repro. Le QUOI (critères) vient de `spec-func.md`. Générique et project-agnostic. À utiliser dès que l'agent recetteur doit valider une story déployée.
---

# Recetter une story (paramétré par le manifest)

Tu ne devines pas comment joindre l'env : tu lis les paramètres, puis tu appliques la procédure.
**QUOI tester** = les critères d'acceptation (`spec-func.md`). **COMMENT** = ce skill + le manifest.

## 0. Outils NORMALISÉS — appelle ces scripts, n'improvise PAS de `curl`/token/`python -c`/`/tmp`
**Générique** (ce skill, `scripts/`) :
```bash
D=<chemin du skill>/scripts        # dossier scripts/ à côté de ce SKILL.md
# GET authentifié (token lu d'un FICHIER, jamais en argv ; direct --base ou via --pf) :
python3 $D/api_get.py --pf <ns>/<kind>/<name>:<port> --path <p> --token-file <f> --fields <csv>
```
**Auth = skill PROJET** (2-tiers, dans le repo data `<projet>-sdlc-local/skills/`). Ex. HIA `hia-recette` :
```bash
# mint le token admin (creds du compte de test via ENV, jamais hardcodés) -> fichier 600, jamais affiché :
python3 <data>/skills/hia-recette/scripts/hia_admin_token.py --keycloak <kc> --service-name <tenant> --out <scratch>/token
```
Le token **ne surface jamais** (fichier scratch `600`, lu en interne par `api_get.py`). **Scripts temp dans le
scratch de la bulle, jamais `/tmp`.** Allowlist recetteur = `Bash(python3 …/scripts/*.py:*)`.
> Ton rôle = **appeler ces scripts + asserter** vs les critères. Les sections ci-dessous = le *pourquoi* (fallback).

### ⛔ RÈGLE ANTI-HANG (obligatoire — un recetteur s'est figé 9h sur un port-forward)
`kubectl port-forward` est **bloquant par nature** : lancé en direct, il ne rend **jamais** la main → l'agent se fige.
**N'exécute JAMAIS un port-forward brut.** Borne **toute** op longue (port-forward, mvn, npm, curl) avec les wrappers
partagés (dans le skill `deploy-jenkins/scripts/`) :
```bash
D=<…>/deploy-jenkins/scripts
bash $D/pf_curl.sh <ns> <deploy> <containerPort> <path> [curl_opts…]   # port-forward + curl + kill, borné
bash $D/safe_run.sh <timeout_sec> -- <commande…>                        # borne n'importe quoi (rc=124 si dépassé)
```

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

## 3 bis. Deux oracles EXHAUSTIFS (liste paginée, donnée en double écriture)

Un critère vérifié sur **un** échantillon passe alors que le défaut est à la ligne 313. Ces deux oracles
comptent **tout** ; c'est le seul moyen d'attraper ce qui **manque**. Ils ont trouvé, le 2026-10-24, un
défaut d'intégrité vieux de **deux ans** qu'aucune recette n'avait vu.

### Oracle A — « ce qui est annoncé est servi »
Pour **toute** liste paginée : parcours **toutes** les pages, à **plusieurs** tailles de page, et assère

```
totalElements annoncé  ==  nombre de lignes distinctes effectivement restituées
```

Mesure vécue : une liste annonçait `1006` et n'en rendait que `1005`, **à toutes les tailles de page**, avec
**une page du milieu courte d'une seule ligne**. Un test sur la page 0 — ou sur le total seul — passait. La
cause : le **compteur** venait d'un service et le **contenu** d'un autre, et la ligne absente était jetée
par un `log.warn` sans décrémenter le total.

À assérer aussi, car chacun cache une cause différente : **aucun doublon** entre pages, et **aucun trou**
(la concaténation des pages == l'ensemble attendu, pas seulement le bon cardinal).

### Oracle B — « les deux côtés d'une double écriture coïncident »
Dès qu'une donnée vit à **deux endroits** (base de référence + miroir local, cache, index de recherche,
annuaire…), compare les **ensembles de clés**, jamais deux `count(*)` :

```
clés à gauche  \  clés à droite   -> doit être VIDE
clés à droite  \  clés à gauche   -> doit être VIDE
```

Un écart de **cardinal** se voit ; un écart de **contenu à cardinal égal** ne se voit pas. Et refais-le sur
**plusieurs** tenants/périmètres : le défaut réel était absent de **13 périmètres sur 16**, donc un seul
échantillon propre ne prouve rien.

⚠ **Un `log.warn` sur un état « impossible » est un générateur de défauts silencieux.** Si tu vois du code
qui **jette** une donnée en la journalisant, remonte-le même si le critère passe : ce qui n'est pas compté
n'est pas détectable — ici, 172 lignes perdues et une liste client annonçant 231 pour 66 affichables.

## 4. Sur KO reproductible → bundle repro
Dans `<data>/<EPIC>/stories/<STORY>/repro/` : `steps.md` (séquence rejouable), `env.md` (URL/version),
`fixtures.md` (compte/ids de test, **sans secret**), la réponse/`snapshot`, le critère violé. C'est ce
que le fixer rejouera en local.

## 5. Trace + verdict
- Écris/complète `acceptance.md` : **PREPEND en tête** (journal horodaté, récent en premier, n'écrase pas — cf. skill `agent-resilience`) un bloc `## Recap` (pass/fail + `N/total`, faits
  clés anonymisés, `agent: recetteur`, horodatage), puis le détail par critère (PASS/FAIL + preuve
  **anonymisée**). Puis `link <STORY> acceptance <chemin>`. Le `## Recap` est ce que lit `sdlc status`.
- **Ne change PAS le statut toi-même** : la transition (`recette_ok`) est **dictée par l'orchestration**
  (le workflow, ou Harry) — applique-la seulement si on te l'indique explicitement.
- Dernier message = JSON `{pass, repro, flaky, failed}`.

## Discipline de contexte & résilience (agent long)
Une recette enchaîne beaucoup d'appels (port-forward, token, API, kcadm…) → **charge le skill
`agent-resilience`** et applique-le (contexte maigre via `jq`, `acceptance.md` sauvé au fil de l'eau,
resume-safe, découpe si long). Spécifique recette : **filtre** chaque réponse aux seuls champs assertés
(ex. `curl -s … | jq '[.[] | {clientId, enabled, authFlow, receptionMode, journeyOptions}]'`),
**réutilise** token + port-forward (ne les relance pas par critère), et **nettoie** le port-forward à la fin.

## Pièges & astuces (vécus en prod)
- **Accès backend sans port-forward** : si le repo a un **ingress public**, curl-le **directement** (plus fiable que
  le port-forward). Ex. : `https://<host-public>/<module>/api/…` quand le front proxie le préfixe du module.
  → évite le piège port-forward.
- **Présence d'un endpoint sans token** : un `GET` sans auth qui renvoie **302/401** = endpoint **présent + sécurisé** ;
  **404** = endpoint **absent** (pas déployé). Check rapide avant de sortir l'artillerie d'auth.
- **Auth Keycloak 26** : le token vit sous le **chemin relatif** `KC_HTTP_RELATIVE_PATH` — souvent **`/admin`** (vécu :
  `https://<host>/admin/realms/<realm>/protocol/openid-connect/token`). **Sans `/admin` → 405/404** (piège classique).
  Mint = `client_credentials` (SA de recette) **ou** ROPC (user de recette), **secret lu d'un fichier**, jamais en argv.
- **Erreur générique `{"field":null,"key":"unknown.error"}`** (HTTP 400) = **échec en aval mappé** par le
  gestionnaire d'exception (pas une validation de champ). → **LIS le code de la méthode aval** (relais), n'ASSUME
  jamais la cause. *(Vécu, leçon à la dure : j'ai d'abord assumé que le service aval rejetait une valeur absente de son
  énumération, et qu'il fallait releaser la lib de domaine — **FAUX**. En lisant enfin la méthode aval, la vraie cause
  était qu'elle ne fait qu'un **update des lignes EXISTANTES matchées par ID**, **sans upsert** → un relais qui envoie
  des entités **neuves sans id** ne matche rien / NPE. Aucun rapport avec le domaine. J'ai perdu une release + un build
  à chasser la mauvaise piste.)* **Règle : `curl` la cause hypothétique
  puis `grep`/`Read` la méthode aval AVANT d'ouvrir un chantier release/infra.**
- **Un test unitaire vert ne prouve pas l'intégration** : le relais cross-repo était **mocké** → le PUT passait en
  test. La **recette live attrape** le mismatch de contrat (upsert attendu vs update-by-id réel).

## Fallback connaissances profondes
Spécifiques d'auth/endpoint d'un projet : le **Brain** (`.brain` du manifest) + le `CLAUDE.md` du repo.
Le manifest reste la source des **paramètres d'accès** ; le Brain, le **pourquoi/comment fin**.

## Workspace de run

Si le prompt fournit `IN`, `OUT` et `CODE` (mode run workspace, projet en `runWorkspace: true`), ces règles
remplacent les chemins de story, les worktrees et les transitions décrits plus haut :
- **Lire** : `sdlc doc read <clé> --run <root>` (`spec-tech`, `spec-func`, `prd`, `brain/<chemin>`… ; liste :
  `sdlc doc list --run <root>`) ou les fichiers de `IN`, en lecture seule. Jamais le dépôt data.
- **Écrire** : brouillons (et notes de reprise « au fil de l'eau ») dans `<root>/rw/scratch/`, jamais dans un
  dossier temporaire système ; puis **un seul** `sdlc doc add acceptance <fichier> --run <root>` en fin, avec une
  section `## Recap`.
- **Code** : `git -C CODE …`, commits sur la branche de la story ; **jamais** de push, de `git remote`, de
  `sdlc link` ni de changement de statut : l'orchestration publie (`sdlc run finish`) et transitionne.
- Commandes d'état et de config permises : `sdlc get`, `sdlc config`, `sdlc deploy-target`, `sdlc pm add`.
- **Recette** : vérifie d'abord que la version déployée = `git -C CODE rev-parse HEAD`. Sur KO, le bundle repro va
  dans `OUT/sources/repro/` (`steps.md`, `env.md`, `fixtures.md`, traces) et le verdict porte
  `repro = "run:<RUN_UID>"` ; il sera publié avec le run et remis au fixer dans `IN/repro/`.
Sans `IN`/`OUT` : les instructions ci-dessus s'appliquent inchangées.
