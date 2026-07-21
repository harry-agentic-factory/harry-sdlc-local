# harry-sdlc-local — engine SDLC agentique local « Harry »

**Engine réutilisable, project-agnostic.** Opère sur des repos **data** séparés (`<projet>-sdlc-local`)
qui stockent les tickets (`.md` + `status.json`). Un moteur, plusieurs jeux de données (SAMPLE, OtherProject…).

> PRD / modèle conceptuel : [`docs/PRD.md`](docs/PRD.md). Objectif à terme : migration vers
> `harry-sdlc-ai-factory` (gates→HITL, agents→heavy drivers, `run-ticket`→`TicketWorkflow`).

## Quickstart
```bash
git clone <repo-url> harry-sdlc-local && cd harry-sdlc-local
make install     # symlinke l'engine dans ~/.claude + crée la commande globale `sdlc`
make test        # 27 tests (déterministe, offline)

# 1 projet = 1 repo data
sdlc init-project SAMPLE --path ../sample-proj-sdlc-local --repos app-repo,web-repo
sdlc --project SAMPLE list                # data prête (vide)
```
Puis, dans **Claude Code** : `/harry techlead` → `/scope <une idée>` → `/refine` → `/spec-tech` → `/implement`,
puis « **lance run-ticket sur <TICKET>** » (tronçon autonome). Détail : **§ Découverte pas à pas** ci-dessous.
**Raccourci mono-user** : `/full-spec <un besoin>` produit **d'un coup** PRD + refine + stories + spec-func +
spec-tech (une personne portant PO+BA+techlead) — idéal pour un besoin rapide ou une session solo.
Prérequis : Python 3.11+ ; Claude Code pour les slash-commands & workflows.

## Les 4 couches (rappel)
1. **Méthode/lifecycle** · 2. **Mémoire/état** (repo data) · 3. **Chef interactif** (Harry, session) ·
4. **Fleet + orchestration** (agents + Workflow). Agents à contextes **isolés** → mémoire + coordination
**externalisées** (couches 2 & 4), sinon le lifecycle tourne dans le vide.

## Contenu
```
VERSION                    # version d'engine (semver)
install.sh · Makefile      # make install  → symlink dans ~/.claude
claude/
  agents/      reviewer, deployer, recetteur, fixer, e2e-author, nonreg-runner, demo
  commands/    harry, scope, refine, spec-func, spec-tech, full-spec (one-shot upstream), ticket
  workflows/   run-ticket.js (gates) · run-ticket-full-auto.js (env d'intégration)
  skills/      deploy-jenkins · recette · agent-resilience (méthodes + discipline agents longs)
  sdlc/        harry.md (persona)
tooling/
  sdlc/        state-machine, DAG, workspace, board, service, cli, mcp_server, migrations/
  cockpit/     board + Inbox HITL (FastAPI + page)
  tests/       27 tests (déterministe, offline)
docs/PRD.md
```

## Installer / tester
```bash
make install         # symlink claude/* -> ~/.claude ; crée la commande globale `sdlc` (dans un dir du PATH)
make test            # pytest du cœur déterministe
```
`make install` pose une commande **`sdlc`** appelable de partout (dans `/usr/local/bin`, `/opt/homebrew/bin`
ou `~/.local/bin` selon ton PATH). Ensuite :
```bash
sdlc projects                        # projets enregistrés
sdlc --project SAMPLE get SAMPLE-APPS-1     # réhydrate un ticket
sdlc --project SAMPLE config            # manifest RÉSOLU (repos→chemins abs, brain, deploy…)
sdlc --project SAMPLE worktree SAMPLE-1 --branch feat/x   # worktree(s) isolé(s) du ticket (create-or-reuse)
sdlc --project SAMPLE worktree-clean SAMPLE-1            # remove si la branche est mergée sur refBranch
sdlc --project SAMPLE workspace SAMPLE-1 --branch feat/x  # bulle scopée : worktrees + settings.json + skills projet
sdlc init-project OTHER --path … --repos a,b   # nouveau projet
sdlc migrate --project SAMPLE           # migrer la data
```

### Worktrees — code isolé par ticket (autonomie des agents)
`1 ticket = 1 branche = 1 worktree`, réutilisé par **tous** les agents du ticket (fix-loop fluide,
zéro collision avec la session ou un autre agent). Chemin **déterministe** `<parent>/_wt/<repo>/<branche>`.
- `sdlc worktree <STORY> [--repo r] [--branch b] [--base b]` — **create-or-reuse** (git interdit un
  2ᵉ checkout d'une branche → réutilise) pour chaque repo touché du ticket.
- `sdlc worktree-clean <STORY> [--ref origin/main]` — **remove** worktree + `branch -d` **seulement si**
  la branche est mergée sur `refBranch` (du manifest). `remove` ne détruit **pas** les commits.

### Bulle scopée de l'agent (`sdlc workspace`) — droits + isolation + skills
`sdlc workspace <STORY> --branch <b>` **assemble** la bulle d'un agent, session-indépendante :
- **worktrees** (create-or-reuse) pour chaque repo touché ;
- **`.claude/settings.json`** avec `additionalDirectories` = **worktrees + brain + data**, et *rien d'autre*
  (fini le workspace VS Code hérité / le home-grant global) ;
- **skills projet** : symlink de `<data>/skills/*` dans le `.claude/skills` de la bulle (2-tiers :
  générique = engine, spécifique = projet) ;
- **identité** : `credentials.source` héritée du manifest.

Dossier **régénérable** sous `<reposRoot>/_agentws/<PREFIX>/<STORY>/`, prêt pour un lancement **headless**
(préfigure le sandbox factory). C'est la brique **droits scopés** de la pile d'autonomie.

**Intégré à l'orchestration** : `run-ticket*.js` ouvre par une phase **Prepare** (`sdlc workspace` →
worktree isolé, passé comme repo à tous les agents) et le full-auto termine par **Cleanup**
(`sdlc worktree-clean` → remove worktree + bulle **si mergé** sur `refBranch`). Côté logique de
référence, `orchestrator.py` thread la bulle dans le `ctx` des agents et `accept(..., finalize=...)`
déclenche le nettoyage post-`done`.
(Le registre `~/.claude/sdlc/projects.json` mappe `<PREFIX>` → repo data.) Workflows :
`Workflow({scriptPath:'~/.claude/workflows/run-ticket*.js', args:{…}})`.

### Le manifest (`sdlc.config.json`) = la carte du projet
Source de vérité lue par **les agents** via `sdlc config` (au lieu de reverse-engineerer l'infra) :
```jsonc
{ "prefix": "SAMPLE",
  "reposRoot": "/abs/parent",              // base ; les repos ci-dessous se résolvent par <reposRoot>/<nom>
  "repos": { "app-repo": null, "ops-repo": "/opt/ops" },  // name→path (null ⇒ via reposRoot)
  "roles": { "app-repo": "code", "ops-repo": "gitops" },
  "brain": "sample-brain",                 // pointeur connaissance (résolu abs)
  "refBranch": "main",                     // cible de merge ⇒ cleanup worktree
  "deploy": { "app-repo": { "skill": "deploy-jenkins", "ci": "prod/app/ci", "gitops": "ops@prod" } },
  "escalation": { … }, "schemaVersion": "0.2.0" }
```
`sdlc config` renvoie la vue **résolue** (chemins absolus) ; `sdlc config --raw` renvoie le fichier brut.

**Identité (`credentials.source`)** : `host` (défaut) = creds **ambiantes de l'opérateur** —
`curl -s -n`/`~/.netrc`, `~/.kube/config`, keyring `gh`/`glab` — **utilisées sans jamais être lues ni
affichées**. `service` (futur) = creds de service scopées injectées dans la bulle de l'agent (l'étape
qui rendra les agents pleinement session-indépendants).

## Découverte pas à pas

Tour guidé pour comprendre **3 choses** : (a) **qui fait quoi** (responsabilités), (b) **où ça persiste**,
(c) **le lien symlink `~/.claude` ↔ plateforme**. Commandes `sdlc` = de partout ; les `ls`/chemins relatifs
= **depuis la racine de l'engine** (`harry-sdlc-local/`). Rien n'est destructif sauf les `rm` que tu tapes.

### 0. Installer, et comprendre ce que ça pose
```bash
make install
```
- **Symlinke** `claude/{agents,commands,workflows,sdlc}/*` → `~/.claude/…` (l'endroit que **Claude Code lit**).
  Ce sont des **liens, pas des copies** : éditer un fichier de l'engine change *immédiatement* ce que Claude
  utilise.
- Crée la **commande globale `sdlc`** (dans un dossier de ton PATH).
- **Ne touche pas** à `~/.claude/sdlc/{profile,projects.json}` (ton **état perso** : profil courant + registre).

### 1. Voir le lien symlink ↔ plateforme (le point clé)
```bash
readlink ~/.claude/agents/reviewer.md      # -> .../harry-sdlc-local/claude/agents/reviewer.md
readlink ~/.claude/workflows/run-ticket.js # -> .../harry-sdlc-local/claude/workflows/run-ticket.js
```
→ chaque fichier de `~/.claude` est une **flèche** vers l'engine. **La source de vérité du comportement =
l'engine** ; `~/.claude` n'est que le *point de montage* regardé par Claude Code. Tu modifies l'engine →
Claude voit le changement au prochain chargement. C'est ça qui rend le harness **versionnable et transférable**.

### 2. Qui fait quoi (responsabilités)
```bash
ls  claude/agents/          # WORKERS autonomes (1 rôle chacun : reviewer, deployer, recetteur, fixer…)
ls  claude/commands/        # GESTES interactifs de Harry (les slash : scope, refine, spec-*)
ls  claude/workflows/       # ORCHESTRATION (enchaîne les agents : run-ticket)
sed -n '1,6p' claude/sdlc/harry.md   # la PERSONA (le chef qui arbitre)
ls  tooling/sdlc/           # le CŒUR déterministe (état, DAG, CLI) — zéro LLM
```
Répartition : **persona + commands = interactif** (couche 3) · **agents + workflows = autonome** (couche 4)
· **tooling = manipulation de l'état** (écrit la couche 2).

### 3. La commande `sdlc` = lire/écrire l'ÉTAT (pas faire le travail)
```bash
sdlc projects                      # le REGISTRE : quels projets, où est leur data
sdlc --project SAMPLE list            # les tickets du projet SAMPLE
sdlc --project SAMPLE get SAMPLE-APPS-1  # réhydrate 1 ticket (statut + carte des artefacts)
```
`sdlc` ne *fait* pas le SDLC : il **lit/écrit l'état**. Ce sont les **agents** (couche 4) qui font le travail.

### 4. Où ça PERSISTE (la vérité vit dans la data)
```bash
sdlc projects                                        # SAMPLE -> .../sample-proj-sdlc-local
ls  ../sample-proj-sdlc-local/SAMPLE-APPS/stories/SAMPLE-APPS-1/    # les .md du ticket
cat ../sample-proj-sdlc-local/SAMPLE-APPS/stories/SAMPLE-APPS-1/status.json
```
La **vérité vit dans le repo DATA** (`.md` + `status.json`), **pas** dans l'engine ni dans `~/.claude`.
L'engine est **sans état** ; la data est **git-trackée** (persistante, versionnée, `git revert`-able).
`get` ne fait que **lire ces fichiers**.

### 5. La state-machine (le garde-fou) — chaque écriture modifie un fichier
```bash
sdlc --project SAMPLE create-epic  SAMPLE-TOUR "Découverte"
sdlc --project SAMPLE create-ticket SAMPLE-TOUR SAMPLE-TOUR-1 "socle"
cat  ../sample-proj-sdlc-local/SAMPLE-TOUR/stories/SAMPLE-TOUR-1/status.json   # le fichier vient d'être créé (persistance)
sdlc --project SAMPLE link SAMPLE-TOUR-1 spec_tech SAMPLE-TOUR/stories/SAMPLE-TOUR-1/spec-tech.md  # attache un artefact (enregistré dans status.json)
sdlc --project SAMPLE set-status SAMPLE-TOUR-1 spec_func              # OK — transition valide
sdlc --project SAMPLE set-status SAMPLE-TOUR-1 done                   # ❌ REFUSÉ — saut interdit (le garde-fou)
rm -rf ../sample-proj-sdlc-local/SAMPLE-TOUR                               # data jetable
```
Chaque commande **écrit sur disque** (persistance) **et** la state-machine **valide** (responsabilité :
cohérence). L'erreur prouve que le statut n'est pas un champ libre.

### 6. Le DAG (dépendances entre tickets)
```bash
sdlc --project SAMPLE create-epic  SAMPLE-DAG "Demo"
sdlc --project SAMPLE create-ticket SAMPLE-DAG SAMPLE-DAG-2 "socle"
sdlc --project SAMPLE create-ticket SAMPLE-DAG SAMPLE-DAG-1 "api" --deps SAMPLE-DAG-2
sdlc --project SAMPLE next SAMPLE-DAG     # -> [SAMPLE-DAG-2]  (SAMPLE-DAG-1 attend son socle)
rm -rf ../sample-proj-sdlc-local/SAMPLE-DAG
```

### 7. Multi-projet : 1 engine, N data
```bash
sdlc --project OTHER list            # OtherProject : AUTRE repo data, MÊME engine
sdlc init-project DEMO --path /tmp/demo-sdlc-local --repos a,b   # crée le repo data + l'enregistre
sdlc register OLD /tmp/demo-sdlc-local                          # (variante) enregistre un repo data EXISTANT sans le créer
sdlc projects                      # DEMO + OLD enregistrés (dans le registre ~/.claude/sdlc/projects.json)
rm -rf /tmp/demo-sdlc-local        # (+ retire "DEMO"/"OLD" du registre si tu veux)
```
Ajouter un projet ne change **pas** l'engine : juste un **repo data** + une entrée dans le **registre**
(ton état perso).

### 8. Côté Claude Code — les symlinks en action
Dans une session (tu me parles, pas le shell) :
- `/harry techlead` → charge la **persona** (`~/.claude/sdlc/harry.md` → symlink engine).
- `/scope <idée>` → la **commande** (symlink) guide Harry ; il écrit un `prd.md` **dans le repo DATA**.
- « lance run-ticket sur SAMPLE-APPS-1 » → le **Workflow** (symlink) orchestre les **agents** (symlinks).

La boucle : **Claude lit les symlinks → agit → persiste dans la data**. Pour changer un comportement, tu
édites `claude/agents/*.md` (ou `commands/`, `workflows/`) **dans l'engine** — le symlink propage.

### 9. Voir l'état visuellement (cockpit, optionnel)
```bash
pip install fastapi uvicorn
SDLC_WORKSPACE=$(cd ../sample-proj-sdlc-local && pwd) python3 -m cockpit.server   # depuis tooling/ → http://localhost:8787
```

---

## Versioning & migration de la data
L'engine est versionné (`VERSION`). Chaque repo data porte `schemaVersion` (dans `sdlc.config.json`).
Un upgrade peut migrer la data : `make migrate PROJECT=SAMPLE` (applique `tooling/sdlc/migrations/`, bumpe
`schemaVersion`). Data git-trackée → un mauvais upgrade se `git revert`. Baseline = `0.1.0` (0 migration).

## Nouveau projet (ex. OtherProject)
1. Créer `other-proj-sdlc-local/` (repo data) avec `sdlc.config.json` (`prefix: OTHER`, ses repos, escalation).
2. L'enregistrer dans `~/.claude/sdlc/projects.json`. **L'engine ne change pas.**
