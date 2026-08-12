---
name: deploy-jenkins
description: Déploie un module de code via un pipeline Jenkins (CI puis CD/gitops), piloté par les paramètres du manifest SDLC (`sdlc config` → `deploy.<repo>`). Couvre trigger normal ou Replay(CODE_BRANCH), crumb CSRF, polling du build, vérif santé et rollback. Générique et project-agnostic : toutes les valeurs projet viennent du manifest, rien n'est en dur. À utiliser dès qu'un agent (deployer) doit déployer une story dont le repo a un bloc `deploy` de type Jenkins.
---

# Déployer via Jenkins (paramétré par le manifest)

Tu **ne devines pas** l'infra : tu lis les paramètres dans le manifest, puis tu appliques la procédure.
C'est le **savoir-faire** (méthode) ; les **valeurs** (host, jobs, image, ns) viennent du projet.

## 0. Outils NORMALISÉS — appelle ces scripts, n'improvise PAS de `curl`/`python -c`/`/tmp`
Le skill embarque des scripts (`scripts/` à côté de ce SKILL.md). **Utilise-les** : surface fermée,
allowlistable (`Bash(python3 …/deploy-jenkins/scripts/*.py:*)`), auth `curl -s -n` **interne** (jamais de
secret), sorties JSON filtrées. **N'écris pas** de HTML/Groovy dans `/tmp` — les scripts le font en interne.
```bash
D=<chemin du skill>/scripts        # (résous-le : dossier scripts/ à côté de ce SKILL.md)
# 1) déclencher un build en overridant CODE_BRANCH (Replay) :
python3 $D/jk_replay.py --jenkins <host> --job <ci-path> --from <buildRécent> --code-branch <branche>
# 2) suivre le build (poll) :
python3 $D/jk_status.py --jenkins <host> --job <ci-path> --build <N>     # {building,result}
# 3) version déployée (k8s) :
python3 $D/k8s_version.py --ns <ns> --deploy <deployment>                 # {image,tag}
# 4) santé (port-forward + health, refermé automatiquement) :
python3 $D/k8s_health.py --ns <ns> --deploy <deployment> --path /actuator/health   # {http,status}
```
Ton rôle = **enchaîner ces 4 outils + décider** (build → suivre jusqu'à SUCCESS → CD → santé/version →
escalade si ambigu, rollback si KO). Les sections ci-dessous expliquent le **pourquoi** (fallback), mais
la **mécanique passe par les scripts**.

### ⛔ RÈGLE ANTI-HANG (obligatoire — un agent s'est figé 9h sinon)
**Toute op potentiellement bloquante DOIT être bornée.** N'exécute JAMAIS en direct : `kubectl port-forward`
(bloquant par nature), un `while … curl … done` de polling, un `mvn`/`npm` long — sans borne. Utilise les
wrappers :
```bash
# borne N'IMPORTE QUELLE commande (jamais de hang ; rc=124 si dépassé ; tue le GROUPE de procs) :
bash $D/safe_run.sh <timeout_sec> -- <commande...>
# port-forward + curl + kill, entièrement borné (health/API sur un deploy) :
bash $D/pf_curl.sh <ns> <deploy> <containerPort> <path> [curl_opts...]   # sortie: corps + `__HTTP__<code>`
```
⚠️ **Le pipe échappe au bornage** : `safe_run 40 -- kubectl ... | grep | head` ne borne QUE `kubectl` ; si
`kubectl` stalle (ex. token AKS expiré → `kubelogin` orphelin) l'enfant garde le pipe ouvert et `grep|head`
bloquent à l'infini. **Enveloppe TOUTE la pipeline** : `bash $D/safe_run.sh 40 -- bash -c 'kubectl ... | grep ... | head'`
(safe_run tue alors le groupe entier, enfants compris). Incident vécu : deployer figé ~20 min sur un
`get pods | grep` malgré un timeout de 40s.
Et **si tu polls un build**, poll avec un **max d'itérations** (ex. 40×20s=13min) puis **bail** `{ok:false,
note:"timeout poll"}` — ne boucle jamais sans sortie. Émets un **heartbeat** avant chaque attente longue
(CI/CD) et au moins toutes les ~5 min (cf. skill `agent-resilience` règle 9) : l'orchestrateur te **ping**
via le mtime de ta sortie (`claude/scripts/agent_watchdog.sh`, seuil deployer ~600 s) et te **relance en
resume** si tu es figé.

## 1. Récupère les paramètres (source unique = le manifest)
```bash
sdlc --project <PREFIX> config          # JSON résolu
```
Dans `.deploy["<repo>"]` (repo = celui de la story) :

| Param | Rôle |
|---|---|
| `jenkins` | URL de base Jenkins (ex. `https://ci.example.com`) |
| `ci` | chemin du job CI (folders `/`-séparés, ex. `prod/app/ci`) |
| `cd` | chemin du job CD (déploiement) — optionnel si gitops-only |
| `gitops` | `<repo>@<branche>` du repo gitops (ex. `ops-repo@prod`) |
| `image` | nom d'image (ex. `app-image`) |
| `namespace` | namespace k8s cible |

Complète avec `sdlc get <STORY>` : **branche** de la story, **MR**, et `refBranch` du manifest
(branche de code de référence = build normal ; sinon Replay sur la branche de la story).

## 2. Identité (d'où viennent les creds)
`sdlc config` → `.credentials.source` :
- **`host`** (défaut) : creds **ambiantes de l'opérateur** — `curl -s -n` lit `~/.netrc`, `kubectl`
  lit `~/.kube/config`, git via keyring `gh`/`glab`. Tu les **utilises sans jamais les lire/afficher**.
- `service` (futur) : creds de service scopées injectées dans la bulle de l'agent.

## Règles de sécurité (ABSOLUES)
- Auth Jenkins : **`curl -s -n`** (lit `.netrc` **lui-même** — ne lis/affiche **jamais** le contenu de
  `~/.netrc`). **Jamais** `-L` ni `%{redirect_url}` (la `Location` Jenkins embarque le mot de passe → fuite).
- **Jamais** afficher de secret/token/credential dans une sortie de commande.
- Ajoute `/api/json` à toute URL Jenkins pour des données structurées.
- Un chemin de job à folders se traduit en URL : `prod/app/ci` → `/job/prod/job/app/job/ci`.

## 3. Choisis la stratégie
- **Build normal** : la branche à déployer **est** `refBranch` (déjà mergée) → lance le job CI tel quel.
- **Replay (override CODE_BRANCH)** : tu déploies une **branche non mergée** (celle de la story) →
  rejoue un build récent en surchargeant `CODE_BRANCH=<branche story>`. (Rejoue depuis un build
  **récent** : un vieux build ré-exécute son ancien Jenkinsfile → creds/étapes périmés.)

### ⛔ RÈGLE — jamais déployer une version EN RETARD sur `main` (rebase-first + cible trunk)
**Objectif : l'image déployée ne doit JAMAIS être en retard sur `main`.** À l'arrivée sur le repo, AVANT de
déclencher quoi que ce soit :
1. **Une branche est déjà déployée / en cours de déploiement dans l'env cible ?** → **NE déploie PAS par-dessus**.
   **Reste en attente** tant que `main` n'est pas repassée en déploiement (on ne double pas un deploy de branche
   en vol, on ne laisse pas deux branches se marcher dessus). L'env d'intégration = **une file, pas un empilement**.
2. **`main` a été (re)déployée** (ou a simplement avancé) ? → **rebase SYSTÉMATIQUEMENT** ta branche/trunk sur
   `origin/main` **avant** de builder/déployer (`git fetch origin` puis rebase). Une branche coupée d'un vieux
   `main` = build périmé = régressions silencieuses (tu réintroduis ce que `main` a corrigé).
3. **Le rebase est impactant** (conflits non triviaux, fichiers partagés modifiés des 2 côtés) ? → **re-vérifie
   de zéro** que **ça compile** ET que le **minimum de tests passe** (build + tests ciblés) **avant** de déployer.
   Un rebase silencieusement cassé qui part en prod-intégration est pire que l'attente.
4. **Cible du deploy en stratégie C (trunk d'épic)** : quand plusieurs stories vivent dans le **même repo**, ne
   déploie pas une **branche de story isolée** (elle ne contient pas les stories déjà mergées au trunk) → déploie
   le **trunk `epic/<EPIC>`** (qui accumule les stories, **rebasé sur `main`**), ou à défaut la story **rebasée sur
   le trunk**. Mono-story/repo : la branche = le trunk, pas de sujet. Au **promote**, c'est le **trunk rebasé sur
   `main`** qui part sur `main` (ff propre, jamais en retard).

> Court-circuite ces 4 points uniquement si le manifest/Brain du projet documente explicitement un autre modèle
> (ex. env d'intégration multi-branches isolées). Par défaut : **file d'attente + rebase-first + cible trunk.**

### Dépendance à une lib partagée (AVANT de builder l'image)
Si la story touche une **lib partagée** (un artefact versionné consommé par plusieurs services), **release-la
d'abord depuis `main`** puis **pin** les services sur cette version, **avant** de builder/déployer. Un service
qui dépend d'un **`-SNAPSHOT`** de lib **n'est pas reproductible** : son contenu = le dernier build ayant publié
le snapshot (souvent une **branche**, pas `main`) → l'image déployée embarque du code de provenance opaque.
Ordre sûr : **merge lib→`main` → release lib (depuis `main`) → pin services → build/deploy**. Gate simple :
un `grep -R "SNAPSHOT" <service>/pom.xml` (ou l'équivalent gestionnaire de deps) sur les artefacts de la lib
doit être **vide** ; sinon **escalade « lib à release d'abord »**. Les **specifics** (nom de la lib, job de
release, properties de version) viennent du **manifest** / du **Brain** du projet — rien en dur ici.

## 4. Respecte l'escalation
`sdlc config` → `.escalation.deploy` : si `human-confirm`, **demande validation** avant de déclencher.

## 5. Déclenche (crumb CSRF puis POST)
```bash
J="<jenkins>"; JOB="/job/prod/job/app/job/ci"        # dérivé de .deploy.<repo>.ci
CRUMB=$(curl -s -n "$J/crumbIssuer/api/json" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["crumbRequestField"]+":"+d["crumb"])')
# build normal :
curl -s -n -H "$CRUMB" -X POST "$J$JOB/build"
# Replay override CODE_BRANCH (params via replay/run selon le pipeline) :
# curl -s -n -H "$CRUMB" -X POST "$J$JOB/<buildN>/replay/run" --data-urlencode 'json={"mainScript":"...","parameters":[{"name":"CODE_BRANCH","value":"<branche>"}]}'
```

## 6. Suis le build jusqu'au bout
Récupère l'URL du build (queue → `executable.url`), puis **poll** `"$BUILD/api/json"` jusqu'à
`result` (`SUCCESS`/`FAILURE`). Enchaîne **CI → CD** (ou mise à jour gitops `.deploy.<repo>.gitops`)
et poll de même. **Ne lis jamais** le résultat via `-L`/redirect.

## 7. Vérifie la santé
- App : `curl -s <url>/actuator/health` (ou readiness équivalent).
- k8s : `kubectl -n <namespace> rollout status deploy/<...>` → `image:tag` attendu déployé.

## 8. Rollback (si KO ou demandé)
- **Replay** de la **version précédente**, ou `kubectl -n <namespace> rollout undo deploy/<...>`.
- Note la version cible et la raison.

## 9. Trace (le contrat SDLC)
Écris `deploy.md` — **PREPEND en tête** (journal horodaté, récent en premier, n'écrase pas — cf. skill `agent-resilience`) un bloc `## Recap` (ok/ko + `version/tag`, ns, `agent: deployer`,
horodatage), puis le détail (image, ns, job, build#, stratégie). Le `## Recap` est ce que lit `sdlc status`.
Enregistre l'artefact :
```bash
sdlc --project <PREFIX> link <STORY> deploy <EPIC>/stories/<STORY>/deploy.md
```
**Ne change PAS le statut toi-même** : la transition (`deployed`) est **propriété de l'orchestration**
(le workflow la dicte, ou Harry en interactif). Tu renvoies un verdict, tu n'avances pas l'état.

## Discipline de contexte & résilience (agent long)
Le polling CI/CD + les logs Jenkins/kubectl gonflent vite le contexte → **charge le skill
`agent-resilience`** et applique-le. Spécifique deploy : interroge les endpoints en **`?tree=…`**
(`/api/json?tree=result,number,url` plutôt que le build entier), `| tail`/`jq` sur les logs (jamais un
dump complet), **écris `deploy.md` au fil de l'eau** (build#, statut), et si tu es **coupé** relis
`deploy.md` et **reprends le suivi du build en cours** au lieu de re-déclencher. Réutilise le crumb.

## Pièges & astuces (durcis en prod)
- **`curl -g` (globoff) OBLIGATOIRE** dès qu'une URL Jenkins contient `[...]` ou `{...}` — typiquement
  `?tree=builds[number,result,timestamp]{0,10}`. Sans `-g`, curl interprète `[]`/`{}` comme des **globs** →
  `bad range in URL` ou **réponse vide** (piège **silencieux**). Les scripts `jk_*` le gèrent ; à la main, ajoute `-g`.
- **Version réellement déployée = l'IMAGE du conteneur** (le script `k8s_version.py` lit ça), **pas** un timestamp :
  `kubectl -n <ns> get deploy <d> -o jsonpath='{.spec.template.spec.containers[0].image}'` (+ `rollout status`).
  ⚠️ **N'utilise JAMAIS** `.status.conditions[].lastUpdateTime` pour dater un déploiement — c'est la date d'une
  *condition* (souvent bien plus ancienne que le dernier rollout) → conclusion fausse (« déployé il y a 2 mois »
  alors que c'était hier). En cas de doute, **recoupe avec le dernier build CD Jenkins** (date + n°) = la vérité.
- **Déclenchement de build → 403** : un `POST …/job/…/build` **nu** peut renvoyer **403** si le job est
  **paramétré** → utilise **`…/buildWithParameters`** (avec les params) ou le script `jk_replay.py`. Toujours
  **crumb** (`crumbRequestField:crumb`) + `-X POST`.
  - **Replay durci (vécu, PM-020)** : sur certaines instances, le Replay exige, **en plus du crumb**, le **cookie
    de session** — récupère le crumb **et le cookie** dans une même requête (`curl -s -n -c cookiejar …/crumbIssuer/api/json`)
    puis rejoue avec `-b cookiejar -H "<crumbField>:<crumb>"` en POST sur `…/<buildN>/replay/run` avec le corps
    `--data-urlencode 'json={"mainScript":"…","parameters":[{"name":"CODE_BRANCH","value":"<branche>"}]}'`. Un
    `/build` ou un replay sans cookie → **403**. (Si `jk_replay.py` ne le fait pas encore, adapte-le : cookie jar partagé.)
  - **`CODE_BRANCH` en `envVar` du podTemplate (vécu, PM-023)** : quand le job **n'est pas paramétré** et fixe la
    branche via `envVar(key:'CODE_BRANCH', value:'main')` dans le podTemplate, `jk_replay.py` (qui cherche `name:`)
    **ne swappe pas** la branche. Le `"Checking out (main)"` du log est le checkout de la **définition pipeline**,
    pas du code (`checkoutCode` lit l'envVar). → passe par le **replay durci** (`json=`+crumb+cookie) qui réinjecte
    `CODE_BRANCH` dans les 3 conteneurs du podTemplate. **Piège classique : le CI SUCCESS mais l'agent reste coincé à
    la transition CI→CD** — enchaîne bien le trigger CD (crumb+cookie) après le SUCCESS, ne boucle pas.
- **Casse & folders des jobs** : respecte la **casse exacte** (`ci` ≠ `CI`) et la structure de folders
  (`prod/<app>/ci` → `/job/prod/job/<app>/job/ci`). Mauvais casing/folder = **404**. Valeurs par projet → Brain.
- **Réseau sandboxé** : si l'environnement de l'agent **bloque le réseau** vers Jenkins (curl renvoie vide /
  exit≠0 **sans message**), relance la commande réseau via l'échappatoire sandbox de l'hôte
  (`dangerouslyDisableSandbox`) — c'est du **read-only** authentifié `.netrc`.
- **Front ≠ back** : un module **front** a son propre couple CI/CD Jenkins + deployment k8s (bloc `deploy.<front>`
  distinct dans le manifest). Ne suppose pas qu'un merge sur `main` est déployé : **vérifie l'image déployée vs la
  date des merges** (un front peut être mergé mais pas redéployé).

## Verrou d'environnement partagé (multi-session) — obligatoire
Plusieurs sessions partagent **un seul env de prod-intégration par repo** (« dernier deploy gagne ») → sans
coordination elles s'écrasent (vécu : une session ENROL a écrasé un deploy `main`).

> **Le verrou = DÉPLOIEMENT uniquement.** Il protège l'acte de **redéployer** l'env. Une **recette** (ou tout
> consommateur read-only) **ne prend PAS le verrou** — elle ne redéploie pas ; au plus elle consulte
> `env_lock.sh status <env-repo>` pour savoir si un deploy est en cours (et éventuellement attendre qu'il finisse
> pour ne pas recetter un env qui bouge sous elle). Verrouiller pour une recette bloquerait inutilement les
> déployeurs.

Avant tout déploiement sur un env partagé, **l'orchestrateur** (pas le sous-agent) pose un verrou
**auto-cicatrisant** :
`bash claude/scripts/env_lock.sh <action> <env-repo> <owner>` (env-repo ex. `prod-integration--back-tenant`,
owner = ta story/session).
- **`acquire`** avant de spawner un deployer : `0` ACQUIRED (libre ou re-entrant) · `3` BUSY (tenu & frais →
  **attends**, l'owner est affiché) · `4` STALE (tenu mais heartbeat > `ttl`, défaut 900 s → récupérable).
- **`refresh`** à **chaque tour + chaque ping watchdog** tant que ton run (deploy+recette) tourne — une session
  Claude n'a pas de démon, donc le heartbeat avance par tour ; le `ttl` couvre les trous.
- **`release`** en fin de run (après validation). `release`/`refresh` = **owner-only**.
- **Mort du porteur = JAMAIS un blocage** : plus de refresh → `STALE` en ≤ `ttl` → n'importe qui peut
  **`steal`** (journalisé au ledger). **Avant `steal`**, cross-check l'activité réelle (build Jenkins
  `building` ? rollout en cours ?) — on ne vole pas un porteur *vivant mais silencieux entre deux tours*, on
  reprend un porteur *mort* (STALE **et** aucun build en vol). Même philosophie que le watchdog.
- **« Prendre le relais »** = `env_lock.sh status <env-repo>` → `FREE`(0)/`STALE`(4) = acquérir ; `HELD`(3) =
  attendre. Les signaux Jenkins (branche déployée = `main` ? build calme ?) restent un **cross-check** secondaire.

## Fallback connaissances profondes
Détails d'un pipeline précis (Jenkinsfile, shared-lib, casse des jobs, quirks Replay) : le **Brain**
du projet (`.brain` du manifest, ex. `deployments/*.md`) et le `CLAUDE.md` du repo. Le manifest reste
la **source des paramètres** ; le Brain, la source du **pourquoi/comment fin**.
