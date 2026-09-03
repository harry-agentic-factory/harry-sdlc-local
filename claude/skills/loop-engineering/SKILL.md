---
name: loop-engineering
description: Mode opératoire ACTIONNABLE du run autonome d'un ticket/épic SDLC — ce que « vas-y en mode loop » / « en auto » doit résoudre. Cœur = boucle serrée recette(manuelle/live) ↔ fixing, répétée JUSQU'AU VERT, la recette faisant foi ; puis le couplage état-par-état le long de la state-machine SDLC (un agent par état, gates humaines, capitalisation). À charger dès qu'un run doit avancer une story/épic en autonomie. La version longue (le POURQUOI) est dans docs/loop-engineering.md.
---

# Loop engineering — l'actionnable du run autonome

> Ce skill est **l'actionnable**. La version longue (contexte, justifications, couplage détaillé) est
> `docs/loop-engineering.md` — lis-la pour le POURQUOI. À combiner avec `docs/branching-strategies.md`
> (stratégie de branches), `docs/prod-faithful-validation.md` (bugs prod-only), les définitions d'agents
> (`claude/agents/*`) et le skill `agent-resilience` (discipline des agents longs).

## Ce que ça déclenche
« **vas-y en mode loop** » / « **en auto** » = fais avancer la/les stories **le long de la state-machine
SDLC en autonomie**, un agent par état, en **t'arrêtant aux gates humaines** et en **traçant tout** dans
les artefacts + `pm` (jamais seulement dans la conversation, éphémère).

## Le cœur = recette ↔ fixing, jusqu'au vert (la recette FAIT FOI)
La boucle serrée, non négociable :

```
                    ┌─────────────── RÉ-ENTRÉE (fixFrom) ───────────────┐
                    ▼                                                   │
  fixer ──▶ deployer ──▶ recetteur ──KO──▶ bundle repro ────────────────┘
                              │
                             OK
                              ▼
                RECETTE MANUELLE en session ──KO──▶ pm + repro ──▶ (ré-entrée ci-dessus)
                              │
                             OK ──▶ gate humaine ──▶ promote : merge main + recette SUR MAIN
```

**Le triplet `fixer → deployer → recetteur` est le cœur, et il tourne depuis deux endroits** : le
workflow l'enchaîne seul sur une recette agent KO (`MAX_FIX = 2`), et la session le **relance depuis le
fixer** — `Workflow({…, fixFrom:'<repro>'})` — quand c'est la recette **manuelle** qui a trouvé des bugs.
On ne recommence jamais par la review ni par le premier déploiement : ils sont déjà faits.

- La **recette fait foi** : tant qu'elle n'est pas verte (assertions **chiffrées**, sur le **DÉPLOYÉ**),
  on **ne sort pas** de la boucle. Un « ça s'affiche » ne vaut rien.
- **Et la recette qui fait foi est la MANUELLE.** Le `recette_ok` d'un agent est un **candidat**, pas une
  conclusion : un recetteur se fait tromper par un mock, une assertion molle, un écran qui s'affiche sans
  rien prouver. Le vert de l'agent **déclenche** donc une recette manuelle en session (UI *et/ou* API,
  en croisant) — KO ⇒ un item `pm` par bug + `reject --to implemented` + relance ; OK ⇒ seulement alors
  la gate humaine. La boucle interne du workflow (`MAX_FIX = 2`) traite l'échec ; celle-ci traite le
  **succès**, et c'est elle qu'on oublie.
- Le **fixer** corrige **en local, iso-prod** (même moteur DB + dialecte réel + boot complet — pas H2/mock),
  **itère sans redéployer** ; on **ne redéploie que pour re-recetter**.
- Un KO produit un **bundle repro** que le fixer rejoue → corrige → re-vérifie.
- La logique **déterministe** se valide en **IT au build** (dataset seed-direct) ; le **live** = UI/endpoints.

## Couplage état par état (résumé — détail dans le doc)
Déroule, pour chaque story actionnable du DAG :

1. **`draft`** (`/scope`,`/refine`) — cadre l'épic, découpe en stories, **choisis la stratégie de branches**
   (trunk d'épic si multi-stories dépendantes → `docs/branching-strategies.md`).
2. **`spec_func`/`spec_tech`** — specs **groundées sur le code réel**, un Must-validate par AC.
3. **`spec_validated`** — **harry-archi** tranche dans son périmètre ; **escalade humaine** hors périmètre
   (PII, sécurité, choix produit). **Gate.**
4. **`implemented`** — implement par tranche/repo ; **commit-early** (commit le code de prod qui compile
   AVANT d'écrire tous les tests) ; build vert ; IT au build = recette de la logique.
5. **`reviewed`** — reviewer : diff vs invariants du spec-tech **+ checklist pièges prod-only**.
6. **`deployed`** — deployer : **déploie la branche** en intégration + **smokes adversariaux** (boot,
   migration, **login/flux critique**, endpoints) dont le but est d'**attraper** les bugs prod-only ;
   **rollback propre** immédiat si KO.
7. **fix-loop** — sur KO deploy **ou** recette → fixer corrige (iso-prod) → re-deploy → re-recette,
   **jusqu'au vert**.
8. **`recette_ok`** — recetteur API **+** UI, assertions **chiffrées**, croise API↔UI, sur le **DÉPLOYÉ**.
9. **merge trunk** — merge `feat/<STORY>` → **`epic/<EPIC>`** (stratégie C), **jamais `main`**.
10. **`accepted`/`done` + promote** — demo + **validation humaine**. Sur son feu vert, le Workflow relancé
    avec `{promote:true}` merge sur `main`, redéploie main et **rejoue la même recette sur main** : on
    vérifie que ce qui passait sur la branche tient une fois mergé. **Gate.** La mise en production, sa
    CI/CD et sa recette classique sont hors de ce loop — le loop vit dans le monde du développeur.
11. **`/post-mortem`** — capitalise la dette (`pm`), e2e-author fige les parcours en non-reg, **propale
    Brain + harnais** (pour que les futurs runs héritent du mode op amélioré).

## Invariants du loop (non négociables)
- **La recette fait foi** — chiffrée, sur le déployé ; jamais « ça s'affiche » ; un fix non déployé n'est
  **pas** recetté.
- **Validation iso-prod** — un vert H2/mock/slice **ne prouve pas** la prod ; must-run gates = un **IT
  PostgreSQL iso-prod** (vrai changelog + dialecte réel + écriture jsonb) **+** un **smoke context-load**
  (`@SpringBootTest`). Détail des pièges → `docs/prod-faithful-validation.md`.
- **Smokes adversariaux** — leur job est d'**attraper** les bugs prod-only, pas de confirmer ; toujours
  vérifier le **flux critique** (login/auth) après deploy.
- **Commit-early** — dès que le code de prod compile, commit/push (anti-perte si un agent meurt).
- **No gated waits** — aucune attente ne doit ouvrir un prompt de permission : attentes **bornées
  non-interactives** uniquement (jamais `Monitor`/until-loop ni `port-forward` gated). Cf. `agent-resilience`
  règle 8 + `deploy-jenkins`.
- **Rollback propre** — un déploiement KO est rollbacké **immédiatement** ; l'env n'est **jamais** laissé cassé.
- **Traçabilité** — chaque itération écrit son artefact (`implement/deploy/acceptance.md`) + des items `pm` ;
  la conversation est éphémère.
- **Gates** — dans le périmètre → harry-archi ; hors périmètre (irréversible, sécurité, produit, PII) →
  **escalade humaine**. Le loop ne s'auto-accorde **jamais** une gate humaine (spec_validated escaladé,
  promote/accept).
- **Périmètre auto** — avance jusqu'à **feature fonctionnelle + testée + déployée en intégration + recettée** ;
  la **promote `main`/prod reste une gate humaine**. Autorisations durables : deploy branches d'intégration,
  merge de **ses propres** MR validées → **trunk**, non-reg.

## Deux façons de dérouler
- **Manuel** : Harry spawne les agents séquentiellement (plus de latitude d'adaptation).
- **Workflow tool** : `claude/workflows/run-ticket*.js` codifie review→deploy→recette→fix-loop→promote
  (plus déterministe). `run-ticket` = gates ; `run-ticket-full-auto` = env d'intégration, review auto.

Les deux suivent le **même couplage** ci-dessus.

## Références croisées
- `docs/loop-engineering.md` — version longue (POURQUOI + tableau état-par-état complet).
- `docs/branching-strategies.md` — stratégies A/B/**C trunk d'épic** + discipline git.
- `docs/prod-faithful-validation.md` — bugs prod-only vécus, généralisés (dialecte, jsonb, Liquibase, boot).
- `docs/scheduled-jobs.md` — pattern de job planifié maîtrisé (fenêtre déterministe, ShedLock, run-history).
- `claude/skills/agent-resilience/SKILL.md` — discipline des agents longs (commit-early, no gated waits).
