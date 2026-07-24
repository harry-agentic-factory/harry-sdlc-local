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
- **Casse & folders des jobs** : respecte la **casse exacte** (`ci` ≠ `CI`) et la structure de folders
  (`prod/<app>/ci` → `/job/prod/job/<app>/job/ci`). Mauvais casing/folder = **404**. Valeurs par projet → Brain.
- **Réseau sandboxé** : si l'environnement de l'agent **bloque le réseau** vers Jenkins (curl renvoie vide /
  exit≠0 **sans message**), relance la commande réseau via l'échappatoire sandbox de l'hôte
  (`dangerouslyDisableSandbox`) — c'est du **read-only** authentifié `.netrc`.
- **Front ≠ back** : un module **front** a son propre couple CI/CD Jenkins + deployment k8s (bloc `deploy.<front>`
  distinct dans le manifest). Ne suppose pas qu'un merge sur `main` est déployé : **vérifie l'image déployée vs la
  date des merges** (un front peut être mergé mais pas redéployé).

## Fallback connaissances profondes
Détails d'un pipeline précis (Jenkinsfile, shared-lib, casse des jobs, quirks Replay) : le **Brain**
du projet (`.brain` du manifest, ex. `deployments/*.md`) et le `CLAUDE.md` du repo. Le manifest reste
la **source des paramètres** ; le Brain, la source du **pourquoi/comment fin**.
