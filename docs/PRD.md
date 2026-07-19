# SDLC local « Harry » — outillage Claude Code, cap sur la factory

> **Version** : 0.1 (cadrage) · **Date** : 2026-07-17 · **Owner** : <owner>
> **Statut** : cadrage co-construit — spec de l'outillage local ET feuille de route de migration vers
> `harry-sdlc-ai-factory`.
> **Fil rouge** : la feature réelle **SAMPLE-APPS** sert d'exemple bout-en-bout.

## But & principe

Industrialiser le SDLC **d'abord en local sur Claude Code** (agents + slash-commands + un MCP local d'état),
avant de brancher un projet sur la plateforme factory. La ligne de partage structurante :

> **Interactif = Harry (session principale)** · **Autonome = agents (sous-agents / Workflow)**

- **Harry** : la session Claude elle-même, *profile-aware* (PO / dev / techlead), accès **Brain (MCP) + code**.
  Il orchestre, présente les livrables `.md`, tient les **gates interactives** (affinage, pas oui/non). Il ne code pas.
- **Agents** : bêtes et spécialisés (reviewer, deployer, recetteur, fixer, e2e-author, nonreg-runner, demo).
  Fire-and-forget, câblés par un **Workflow** déterministe.

Cette découpe rend la migration mécanique : **gates → HITL**, **agents → heavy drivers**, **escalation → tiers de
gouvernance**, **Workflow `run-ticket` → `TicketWorkflow` Temporal**.

## Modèle conceptuel — 4 couches

Le harness n'est **pas** que le lifecycle d'agents. C'est un **OS SDLC local** en 4 couches ; le lifecycle
en est **une** (la couche 4).

| # | Couche | Rôle | Réalisation |
|---|---|---|---|
| 1 | **Méthode / lifecycle** | l'enchaînement des étapes | scope→refine→spec→implement→review→deploy→recette→fix-loop→merge |
| 2 | **Mémoire / état partagé** | ce que les agents se transmettent | repo **data** : `.md` par ticket + `status.json` + state-machine + DAG |
| 3 | **Chef interactif** | tient les gates, arbitre | **Harry** = la session, *profile-aware* (PO/BA/techlead/dev) |
| 4 | **Fleet + orchestration** | exécute l'autonome | agents + Workflow `run-ticket` (déterministe, reprenable) |

**L'insight clé** : les **agents ont des contextes isolés** (chacun sa fenêtre, aucune conversation
partagée). Pour qu'ils collaborent sur un même ticket **dans le temps**, il faut **externaliser** :
- la **mémoire** → les `.md` + `status.json` (couche 2),
- la **coordination** → le Workflow déterministe (couche 4).

Sans ces deux couches, le lifecycle tourne dans le vide. *Preuve* (run 2026-07-18) : un fix-loop autonome
**recette KO → fixer → redeploy** a fonctionné entre **3 contextes séparés** uniquement parce que l'état
vivait dans le repo data + le Workflow, pas dans une conversation.

**Ligne structurante** : *interactif = Harry (couche 3) / autonome = agents (couche 4)*. C'est elle qui rend
la **migration factory mécanique** (gates→HITL, agents→heavy drivers, `run-ticket`→`TicketWorkflow`).

## Architecture repos — engine vs data (le split reflète les couches)

Deux repos distincts :

| Repo | Contenu | Couches | Nature |
|---|---|---|---|
| **`harry-sdlc-local`** (engine) | `tooling/` (state-machine, DAG, CLI, MCP) · workflows · agents · commands · persona · docs/PRD · tests · `VERSION` · `migrations/` · `make install` | 1, 3, 4 | **réutilisable**, project-agnostic |
| **`<projet>-sdlc-local`** (data) | `<PREFIX>-*/` (les `.md` + `status.json`) · `sdlc.config.json` (`prefix`, `repos`, `escalation`, `board`, `schemaVersion`) | 2 | **par projet** |

L'engine **opère sur** la data. Un moteur, plusieurs jeux de données (`sample-proj-sdlc-local`, demain
`other-proj-sdlc-local`). **Install** : agents/commands/workflows/persona doivent être vus par Claude Code
depuis `~/.claude/` → `harry-sdlc-local` est la **source versionnée** + un **`make install`** qui
symlink/copie vers `~/.claude/{agents,commands,workflows,sdlc}`. C'est ce qui rend le harness **transférable**
(factory-ready) à un autre poste/personne.

## Versioning & migration de la data

L'engine est **versionné** (`harry-sdlc-local/VERSION`, semver). La data porte son **`schemaVersion`**
(dans `sdlc.config.json`). **Un upgrade d'engine peut migrer la data** (nouveau champ `status.json`, nouvel
état de la machine, nouveau layout…). Mécanisme (type alembic, aligné factory) :

- `harry-sdlc-local/tooling/sdlc/migrations/` — migrations numérotées (`m_0002_*.py`) transformant la data.
- **`sdlc migrate --workspace <data-repo>`** : lit `schemaVersion`, applique les migrations en attente
  (idempotentes), bumpe `schemaVersion`. Data git-trackée → un mauvais upgrade se `revert`.
- Règle : **jamais** de breaking change data sans migration ; la baseline actuelle = `schemaVersion 0.1.0`.

## Extension multi-projets (other-proj)

Cibler un nouveau projet = **créer un repo data** (`other-proj-sdlc-local` : `sdlc.config.json` avec
`prefix: OTHER`, ses repos, son escalation) + l'enregistrer dans `~/.claude/sdlc/projects.json`. **L'engine ne
change pas.** Les agents/workflows sont paramétrés par `--project`/args. Un upgrade d'engine migre **chaque**
repo data via `sdlc migrate`.

## Le pipeline

```
idée ──/scope──▶ PRD (épic)
        /refine ──▶ stories + tasks (1 task/story) ──▶ [board optionnel]
   /spec-func ──▶ affinage fonctionnel + critères d'acceptation (skippable si trivial)
   /spec-tech ──▶ plan d'implémentation : guidelines dev + invariants (sans coder)
   /implement ──▶ codage
        │
        ▼  (Workflow run-ticket — débrayage humain configurable à chaque étape)
   reviewer ─▶ deployer ─▶ recetteur(API|MCP) ─▶ [KO → fixer(l’env local) → boucle]
        │                                             │ OK "validé"
        ▼                                             ▼
   e2e-author ─▶ nonreg-runner ─▶ DEMO AGENT ─▶ [toi: accept] ─▶ done ✅
```

Hiérarchie : **idée = épic (PRD)** → **stories** → **task** (une par story). Simple = déroulé en 1 story.

## Identité & traçabilité — l'ID qui colle tout

`<PREFIX>-<n>` (épic) / `<PREFIX>-<n>-<k>` (story). Le **même** identifiant sur : dossier workspace, branche git
(`feat/SAMPLE-42-1-…`), task Planner, MR, et en-tête de chaque `.md`. C'est le **fil de traçabilité** — l'équivalent
local du *lineage* de la factory. Un agent réhydrate tout son contexte depuis l'ID.

## Le workspace d'artefacts (`sample-proj-sdlc-local/`)

Les `.md` ne vivent **ni dans le code produit, ni dans le Brain** : dans un **repo de missions dédié**
(cross-repo, car un ticket touche souvent plusieurs modules). Git-tracké aujourd'hui, **bucket MinIO** demain.

```
sample-proj-sdlc-local/
  SAMPLE-42-<slug>/                 # épic
    prd.md                       # /scope
    refine.md                    # index stories/tasks + DAG dépendances
    _index.md                    # dashboard live (stories × statut × MR × déploiement)
    stories/
      SAMPLE-42-1-<slug>/
        spec-func.md             # /spec-func — critères d'acceptation Given/When/Then
        spec-tech.md             # /spec-tech — guidelines + INVARIANTS (= checklist reviewer)
        implement.md             # log /implement (fichiers, décisions)
        review.md                # note générée par le reviewer
        deploy.md                # image, version, ns déployés
        repro/                   # bundle repro si recette KO (voir §Fix-loop)
        acceptance.md            # critère × vert/rouge
        demo.md                  # note de démo (sprint review)
        status.json              # état-machine du ticket
```

Chaque story déclare ses **repos touchés** (ex. SAMPLE-APPS : `app-repo + plugin-repo + api-repo + ops-repo +
web-repo`).

### Persistance en 3 couches (et pourquoi elle migre seule)

| Couche locale | Rôle | Devient dans la factory |
|---|---|---|
| **MD git-trackés** (`sample-proj-sdlc-local/`) | source de vérité | ArtifactStore (bucket MinIO) |
| **Index SQLite** (rebuild depuis les MD) | requêtes, état-machine | projections Postgres |
| **MCP `sdlc_*`** (local) | API que Harry **et les agents** appellent | mission-control REST |

Le MCP est **stateless-reconstructible** (l'index n'est qu'un cache ; git reste la vérité). Migration = repointer
les mêmes noms d'outils vers l'API remote → **les agents ne changent pas une ligne**.

### Pourquoi un MCP local (pas juste des slash-commands)

Un **slash-command** est une expansion de prompt en session → OK pour **Harry**. Mais un **sous-agent ne peut pas
appeler un slash-command** ; il peut appeler un **outil MCP**. Le MCP est donc **le bus d'état partagé** entre tous
les agents autonomes. Surface d'outils :

```
sdlc_get_ticket(id)         → bundle d'hydratation complet (métadonnées + statut + next +
                              repos + branch + MR + planner_task + carte des artefacts)
sdlc_list_backlog(project?, status?)
sdlc_next(project)          → prochain ticket actionnable (deps + statut)
sdlc_create_ticket(...)     → alloue l'ID, pas de collision
sdlc_set_status(id, s)      → avance l'état-machine
sdlc_link_artifact(id, kind, path)  → enregistre un .md produit
```

`sdlc_get_ticket` = **un seul appel réhydrate tout** ce dont un agent a besoin pour reprendre → antidote à la perte
de contexte en sessions autonomes.

### Global vs per-project (config Claude au niveau global)

Même modèle que les règles globales existantes (`worktree-paths`, `historize-deletions`) :

- **Global** `~/.claude/rules/sdlc.md` : la *convention* (schéma d'ID, layout, statuts, protocole `/ticket`).
- **Global** `~/.claude/sdlc/projects.json` : le **registre** des projets connus (le MCP le lit).
- **Per-project** `sdlc.config.json` : `{ prefix, workspace, repos[], planner_plan_id, escalation{} }`.

« Si pas de référence » → le MCP possède le registre : projet non déclaré = **scaffoldé** au premier `/scope`.

## Le board (gratuit, déjà là)

Pas de Jira. Le MCP **`company-mcp`** (M365) expose **Microsoft Planner** :
- **Plan** = l'épic · **Buckets** = les stories · **Tasks** = les tasks.
`/refine` pousse le miroir ; chaque `status.json` qui avance **coche** la task → suivi depuis le tel.
Source de vérité = les `.md` ; Planner = miroir léger.

## Roster & responsabilités

| Rôle | Type | Compétence propre | Produit |
|---|---|---|---|
| **Harry** | session (interactif) | Brain + code, profile-aware ; orchestre ; gates amont + accept démo | — |
| reviewer | agent | diff **vs invariants du spec-tech** ; approuve la MR si conforme | `review.md` |
| deployer | agent | Jenkins / ops-repo(prod) / kubectl / Replay ; sait **quoi** déployer ; **rollback** | `deploy.md` |
| recetteur | agent | pilote **API** ou **Playwright via MCP** vs critères d'acceptation | `acceptance.md` (+`repro/` si KO) |
| fixer | agent | monte **l’env local**, rejoue le repro, corrige, itère sans redéployer | commit + `implement.md` |
| e2e-author | agent | fige le flow **validé** en `.spec.ts` programmatique (CI) | `.spec.ts` (non-reg) |
| nonreg-runner | agent | lance la suite non-reg (`la suite e2e du projet`) | `nonreg.md` |
| demo | agent | rejoue le scénario validé en **narrant** vs stories (sprint review) | `demo.md` |

## Orchestrateur = Workflow `run-ticket` (pas un agent)

L'orchestrateur simple est le **Workflow built-in** (déterministe, **reprenable** via `resumeFromRunId`, background
+ notification). Un « agent orchestrateur » model-driven est proscrit (non déterministe, non reprenable, nesting
sous-agents fragile). Le Workflow **est** le `TicketWorkflow` Temporal en miniature.

Il tourne **en 2 tronçons** autour de la recette :
1. **Auto amont** : `reviewer → deployer → recetteur` (+ fix-loop). STOP à la validation.
2. **Auto aval** (après ton OK) : `e2e-author → nonreg-runner → demo`. STOP à ton *accept*.

Chaque stage : lit via `sdlc_get_ticket`, écrit son `.md`, avance `sdlc_set_status`.

## Fix-loop & bundle repro (le point qui casse les loops UI)

Un agent qui échoue **ne renvoie jamais « KO »** : il renvoie un **bundle repro exécutable**. Le fix-loop tourne
**en `l’env local`, pas sur le déployé** (boucle rapide : édite → rebuild → re-run, zéro redeploy).

```
repro/
  scenario.spec.ts | steps.md   # scénario rejouable (script, ou log d'actions MCP si recette manuelle)
  trace.zip / snapshot.md       # DOM/screenshots/console/réseau par étape
  failure.md                    # étape KO, attendu vs observé
  fixtures.md                   # id de test, compte, options, seed  ← clé sur UI app-repo
  env.md                        # URL, version déployée
```

Boucle : `recette KO → bundle → fixer (l’env local, mêmes fixtures) → corrige → re-review → re-deploy → re-recette`.
**Garde-fous** : détection *flaky* (rejoue 3× avant de crier KO → sinon ping humain, pas de loop) ; **bail-out
humain borné** (N tentatives, ou repro nécessitant captcha/mail externe → STOP + livre le bundle).
Le `.spec.ts` vert est **promu dans la non-reg** : la recette d'aujourd'hui = le test de non-reg de demain.

## Recette : auto par défaut, manuel = exception

La 1ʳᵉ recette est **un agent autonome** (API ou Playwright via MCP). Le **manuel** (Harry pilote le MCP en
interactif avec toi) n'est que le **chemin de débrayage** quand l'agent échoue ou doute. **L'automatisation
durable (`e2e-author`) n'arrive qu'APRÈS la validation** — on ne fige que ce qui est validé.

## Débrayage humain = policy transverse = tier de gouvernance

Pas de « STOP humain » en dur par étape : un **contrat uniforme** — tout agent qui échoue/doute/est bloqué renvoie
`needs_human` + son bundle → le Workflow STOP + ping **là où ça a buté**. Configurable **par étape** (per-project) :

```yaml
escalation:
  review:  auto            # approuve seul si conforme
  deploy:  human-confirm   # demande avant de pousser (prod / cluster)
  recette: auto→human      # tente seul, débraye si KO
  nonreg:  human-on-fail
```

👉 Cette config **est** le *governance tier* local (≡ `rapid / standard / regulated` de la factory). `rapid` = tout
auto jusqu'à la démo ; `regulated` = plus de gates humaines. À la migration, la config se transpose telle quelle.

## Mapping factory (migration mécanique)

| Local (Harry) | Factory |
|---|---|
| `sample-proj-sdlc-local/` (MD git) | ArtifactStore (MinIO) + `artifact_graph` |
| Index SQLite | projections Postgres |
| MCP `sdlc_*` | mission-control REST |
| Workflow `run-ticket` | `TicketWorkflow` (Temporal) |
| Gates interactives (Harry) | HITL (approve/inbox) |
| Agents (reviewer/deployer/…) | heavy drivers (`HEAVY_DRIVER`) |
| `escalation{}` per-project | `governance_tier` (rapid/standard/regulated) |
| `/spec-func` + `/spec-tech` | providers méthodologie (Spec-Kit / BMAD / Agent OS) |

## Contrats à figer (les briques amont dont tout dépend)

1. **Critères d'acceptation** (`spec-func.md`, Given/When/Then) — clé de voûte : ce que Harry/recetteur vérifient.
2. **Bundle repro** (recette → fixer) — le format qui garantit la reproductibilité (API et MCP).
3. **Schéma du MCP `sdlc`** + format `status.json` (état-machine).
4. **`sdlc.config.json`** per-project (dont `escalation{}`).

## Exemple fil-rouge (générique) — `SAMPLE-APPS`

Une feature cross-repo type (afficher/gérer une entité côté back + front) pour illustrer le pipeline.

- **`/scope`** → PRD de l'épic `SAMPLE-APPS`.
- **`/refine`** → stories + DAG, ex. `SAMPLE-APPS-1` (back : exposer les données) et `SAMPLE-APPS-2`
  (front : liste + détail), avec `2 ← 1` (le front consomme le contrat du back).
- **`/spec-func`** → critères d'acceptation (Given/When/Then). **`/spec-tech`** → plan + **invariants**
  (assertions vérifiables sur un diff) qui deviennent la **checklist du reviewer**.
- **`/implement`** → code + tests unitaires.
- **Tronçon autonome** : `reviewer` (diff vs invariants) → `deployer` → `recetteur` → **fix-loop** si KO
  (`recette KO → repro → fixer → re-deploy → re-recette`) → `e2e-author` fige le scénario validé →
  `nonreg-runner` → `demo` → accept.

**Gain démontré (run réel)** : le `reviewer` autonome a rattrapé une **fuite de secret** avant la PR, et le
**fix-loop** a corrigé un critère manquant puis redéployé — entre **contextes d'agents isolés**, uniquement
grâce à l'état partagé (`.md` + `status.json`) et au Workflow. Chaque écart → un `repro/` rejouable + un commit
lié + un invariant né : **traçable, non-régressable**.

## Plan de construction (par étapes, sans sur-construire)

1. **Sans MCP** : convention `sample-proj-sdlc-local/` + `status.json` + skill `/ticket` (résout un ID en lisant les fichiers).
   Prouve la valeur, zéro infra. Coder d'abord `/scope` + `/refine`.
2. **Les deux vrais manques d'aujourd'hui** : agents `reviewer` + `deployer`.
3. **Le MCP `sdlc`** (~200 lignes FastMCP Python) quand les agents autonomes en ont besoin (bus d'état partagé).
4. **Recette + fix-loop** (`recetteur`, `fixer`, bundle repro, l’env local) puis `e2e-author` + `nonreg-runner`.
5. **`demo` + escalation tiers** ; **SQLite + registre multi-projets** quand on étend au-delà d’un projet (other-proj).

## Reste à décider

- Diplômer ce doc vers un dossier **`sdlc/`** (contrats séparés) quand §Contrats se remplit.

## Addendum — clarifications 2026-07-17

Décisions/précisions actées après le cadrage initial (voir aussi le tracker
[`sdlc-local-harry-progress.md`](./sdlc-local-harry-progress.md)) :

- **`sample-proj-sdlc-local/` = repo dédié** (tranché) : sibling des repos le produit, héberge les `.md` (vérité) + le
  `tooling/` (cœur Python). Cf. `../../sample-proj-sdlc-local/README.md`.
- **Board = adaptateur enfichable** (port `Board`). La vérité reste `.md` + state-machine ; Trello /
  Planner / cockpit = **miroirs une-voie**. Testable offline via `FakeBoard`. `TrelloBoard` = stub prêt
  (MCP Trello à connecter via `claude mcp`). **Planner rétrogradé** : simple miroir optionnel, plus jamais
  « store ».
- **Cockpit local** = couche présentation (jetable) : `_index.md` (v0) → **cockpit web local** (v1, REST+SSE
  au-dessus du MCP, vues Board + **Inbox HITL**) → cockpit factory. Ne stocke rien, lit le read-model.
- **Cycle de vie de l'orchestrateur** : `run-ticket` est **éphémère — un run par ticket**, lancé depuis la
  session Harry, en background, il **meurt** à la fin/gate. Rien ne boucle en permanence. Seuls le MCP et le
  cockpit peuvent être long-running. Le « toujours vivant sur signal » = Temporal, côté factory.
- **Orchestrateur ≠ agents** : un run = **1 orchestrateur + N contextes d'agents isolés** (pas une session
  partagée). Les agents communiquent via `sample-proj-sdlc-local/` + MCP, jamais par conversation. Ils **retournent** un
  verdict — ils ne « réveillent » pas l'orchestrateur (orchestration, pas choréographie).
- **Cœur déterministe livré** (`tooling/sdlc/`) : `status` (state-machine), `graph` (DAG), `workspace`,
  `board` (port), `service` (façade `Sdlc` = future surface MCP). **Golden test pytest** vert.
