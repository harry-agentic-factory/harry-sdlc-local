# Loop engineering — mode opératoire du run autonome, couplé à la SDLC

> **Rôle** : c'est **le mode op** que « **vas-y en mode loop** » / « **en auto** » doit résoudre. Il décrit
> comment Harry (l'orchestrateur) pousse une story **en autonomie** le long de la state-machine SDLC, quels
> agents il spawne à chaque état, où il **s'arrête** (gates humaines), et comment il **capitalise**.
> À lire avec `branching-strategies.md` (stratégie de branches), `prod-faithful-validation.md` (bugs
> prod-only), `scheduled-jobs.md` (pattern de job planifié) et les définitions d'agents (`claude/agents/*`).
> **Version actionnable = le skill `loop-engineering`** (ce que « en mode loop » / « en auto » charge) ; ce
> doc en est la version longue (le POURQUOI).

## Le cœur du loop = **recette ↔ fixing, jusqu'au résultat OK**
« Loop » désigne **avant tout la boucle serrée** : **recette (manuelle/live)** → si **KO** → **fixing** → re-déploie →
**re-recette** → … **répété jusqu'à ce que la recette soit verte**. C'est ça, le loop. Tout le reste de la pipeline
(implement, deploy) sert à **amener à la première recette** ; une fois là, **on itère recette↔fix sans relâche** jusqu'au
vert (puis merge trunk). La recette **fait foi** : tant qu'elle n'est pas OK (assertions chiffrées, live + IT), on ne
sort pas de la boucle. Le **fixer** corrige **en local, iso-prod, sans redéployer à chaque essai** ; on ne redéploie que
pour re-recetter. Un KO produit un **bundle repro** que le fixer rejoue → corrige → re-vérifie.

## Principe : SDLC = les rails, le loop = la locomotive
La **SDLC** fournit la **structure** : state-machine par story (`draft → spec_func → spec_tech → spec_validated →
implemented → reviewed → deployed → recette_ok → accepted → done`), les **artefacts** (`prd/refine/spec-*/implement/
review/deploy/acceptance/demo.md`), les **agents** (harry-archi, reviewer, deployer, recetteur, fixer, e2e-author,
demo), le **CLI `sdlc`** (état + transitions + `pm`), le **post-mortem store**, et la **stratégie de branches**.

Le **loop** est le **moteur d'exécution** : il fait avancer la story d'un état au suivant **automatiquement** —
un agent par état, transition via `sdlc set-status`, **itération par le fixer** sur échec — en **s'arrêtant aux
gates humaines** et en **traçant tout** dans les artefacts + le `pm` (jamais seulement dans la conversation, qui est
éphémère).

## Couplage état par état

| Statut SDLC | Ce que fait le loop | Agent | Artefact écrit | Gate |
|---|---|---|---|---|
| `draft` (`/scope`,`/refine`) | cadre l'épic, découpe en stories/lots, choisit la stratégie de branches (**trunk d'épic** si multi-stories) | PO/BA | prd.md, refine.md | — |
| `spec_func` / `spec_tech` | écrit les specs **groundées sur le code réel** (pas de spéculation) | BA / techlead | spec-func.md, spec-tech.md | — |
| **`spec_validated`** | consulte **harry-archi** → décisions « À APPLIQUER » injectées dans le spec ; **escalade à l'humain** si hors périmètre (PII, sécurité, choix produit) | harry-archi | (décisions dans spec) | **harry-archi + humain** |
| `implemented` | spawn **agent(s) implement par tranche/repo** ; **commit-early** (sécurise le code qui compile avant les tests) ; build vert ; **les IT au build = la recette de la logique** (déterministe, seed-direct) | general-purpose / fixer | implement.md + code | invariants |
| `reviewed` | review du diff vs **invariants du spec-tech** | reviewer | review.md | — |
| `deployed` | deployer → **déploie la branche en intégration** + **smokes adversariaux** (boot, migration, login/flow critique, endpoints) qui **attrapent les bugs prod-only invisibles aux tests** | deployer | deploy.md | **rollback si KO** |
| **fix-loop** | sur **KO deploy OU recette** → le fixer **corrige + redéploie**, **itère jusqu'au vert** ; validation **iso-prod** (pas seulement H2/mock) | fixer | maj artefacts + `pm add` | boucle jusqu'au vert |
| `recette_ok` | recetteur **API + UI**, assertions **chiffrées** ; live léger, la vérité fonctionnelle est l'**IT au build** | recetteur | acceptance.md | repro KO → fix-loop |
| merge trunk | merge `feat/<STORY>` → **`epic/<EPIC>`** (stratégie C), **jamais `main`** | — | MR (story→trunk) | — |
| `accepted` / `done` + **promote** | demo + **validation humaine** → promote `epic/<EPIC>` → `main` → prod | demo | demo.md | **HUMAINE** |
| `/post-mortem` (clôture) | capitalise la **dette (`pm`)**, **e2e-author** fige les parcours en non-reg CI, **propale Brain + harnais** | e2e-author | post-mortem.md, brain-update-propale.md | clôture |

## Invariants du loop (non négociables)
- **Traçabilité** : chaque itération écrit son artefact SDLC (`implement/deploy/acceptance.md`) + des items `pm`.
  La conversation est éphémère ; **rien d'important ne vit que là**.
- **Validation iso-prod** : un test vert en H2/mock ne suffit pas — valider **dans les conditions de prod** (même
  DB/dialecte, boot complet du contexte). Les smokes de déploiement sont **adversariaux** : leur job est d'**attraper**
  les bugs prod-only (migration, mapping DB, placeholder, dialecte), pas de confirmer. **Must-run gates** = un
  **IT PostgreSQL iso-prod** (vrai changelog + dialecte réel + écriture jsonb) **+** un **smoke context-load**
  (`@SpringBootTest`). Catalogue des pièges vécus → `prod-faithful-validation.md`.
- **Commit-early** : dès que le code de prod compile, on commit/push — avant d'écrire tous les tests (anti-perte si
  un agent meurt en cours).
- **No gated waits en auto** : aucune attente ne doit ouvrir un prompt de permission (pas de `Monitor`/until-loop ni
  `port-forward` gated) — attentes **bornées non-interactives** uniquement (cf. `deploy-jenkins`, `agent-resilience`).
- **Rollback propre** : un déploiement KO est **rollbacké** immédiatement ; l'environnement n'est **jamais** laissé cassé.
- **Décisions** : dans le périmètre → **harry-archi** ; hors périmètre (irréversible, sécurité, produit, PII) →
  **escalade humaine**. Le loop **ne s'auto-accorde jamais** une gate humaine (spec_validated escaladé, promote/accept).
- **Périmètre auto** : avancer au max jusqu'à **feature fonctionnelle + testée + déployée en intégration + recettée** ;
  la **promote `main`/prod reste une gate humaine**. Autorisations durables d'un run auto : deploy branches
  intégration, merge de **ses propres** MR validées vers le **trunk**, non-reg. (cf. mémoire projet `feedback_en_auto_semantics`.)

## Ce que « vas-y en mode loop » déclenche concrètement
1. Résoudre l'état courant de la/les stories (`sdlc status`).
2. Pour chaque story actionnable (DAG), **dérouler le couplage ci-dessus** : gate spec_validated (harry-archi) →
   implement → (review) → deploy+smoke → **fix-loop jusqu'au vert** → recette → **merge trunk**.
3. Enchaîner les stories **en série sur le trunk d'épic** (chacune branchée du trunk à jour).
4. **S'arrêter** et rendre la main à l'humain aux gates (spec_validated hors périmètre, promote/accept).
5. À la fin de l'épic : `/post-mortem` → capitaliser + **propager les learnings généralisables au harnais** (pour que
   les futures sessions, tous projets, héritent du mode op amélioré).

## Rapport au Workflow tool (run-ticket)
Le loop peut être orchestré **à la main** (Harry spawne les agents séquentiellement, comme ci-dessus) **ou** via le
**Workflow tool** (`claude/workflows/run-ticket*.js`) qui **codifie** review→deploy→recette→fix-loop→promote. Les deux
suivent le **même couplage** ; le manuel donne plus de latitude d'adaptation, le workflow plus de déterminisme.
