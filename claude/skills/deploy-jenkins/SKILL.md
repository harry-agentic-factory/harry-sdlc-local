---
name: deploy-jenkins
description: Déploie un module de code via un pipeline Jenkins (CI puis CD/gitops), piloté par les paramètres du manifest SDLC (`sdlc config` → `deploy.<repo>`). Couvre trigger normal ou Replay(CODE_BRANCH), crumb CSRF, polling du build, vérif santé et rollback. Générique et project-agnostic : toutes les valeurs projet viennent du manifest, rien n'est en dur. À utiliser dès qu'un agent (deployer) doit déployer une story dont le repo a un bloc `deploy` de type Jenkins.
---

# Déployer via Jenkins (paramétré par le manifest)

Tu **ne devines pas** l'infra : tu lis les paramètres dans le manifest, puis tu appliques la procédure.
C'est le **savoir-faire** (méthode) ; les **valeurs** (host, jobs, image, ns) viennent du projet.

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
Écris `deploy.md` (image, **version/tag**, ns, job, build#, timestamp, stratégie) + enregistre l'artefact :
```bash
sdlc --project <PREFIX> link <STORY> deploy <EPIC>/stories/<STORY>/deploy.md
```
**Ne change PAS le statut toi-même** : la transition (`deployed`) est **propriété de l'orchestration**
(le workflow la dicte, ou Harry en interactif). Tu renvoies un verdict, tu n'avances pas l'état.

## Fallback connaissances profondes
Détails d'un pipeline précis (Jenkinsfile, shared-lib, casse des jobs, quirks Replay) : le **Brain**
du projet (`.brain` du manifest, ex. `deployments/*.md`) et le `CLAUDE.md` du repo. Le manifest reste
la **source des paramètres** ; le Brain, la source du **pourquoi/comment fin**.
