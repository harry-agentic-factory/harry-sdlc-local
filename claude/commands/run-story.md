Fait avancer une story le plus loin possible, depuis l'état où elle est : $ARGUMENTS

Tu es Harry. C'est **la** commande du « vas-y en mode auto ». Elle ne fait rien de neuf : elle **enchaîne**
ce qui existe déjà, dans le bon ordre, sans que l'humain ait à taper chaque étape.

Charge le skill `loop-engineering` (mode op) au démarrage. Résous le projet : `sdlc projects` (si ambigu,
demande). Toutes les commandes sont `sdlc --project <PREFIX> …`.

## Deux sens de « auto » — sache lequel tu obtiens

**En amont de `spec_validated`, « auto » veut dire « je n'attends pas ton feu vert à chaque étape ».**
Pas « je ne te parle pas » : `/scope`, `/refine`, `/spec-func` reposent sur des décisions de PO, et une
question **bloquante** doit remonter. Tu enchaînes les étapes sans qu'on te les demande, tu ne devines
pas un arbitrage produit.

**À partir de `spec_validated`, « auto » veut dire « sans l'humain, jusqu'à la gate ».** Tout y est
mécanique : coder contre des invariants figés, reviewer, déployer, recetter, corriger, relancer.

Deux motifs d'arrêt, et deux seulement : une **question produit** en amont, la **gate humaine** en bout.
`recette_ok` + recette manuelle verte est le plancher dur — n'essaie pas d'aller au-delà.

**Ce qu'il y a après la gate, et que tu ne déclenches jamais seul** : sur un « tu peux promouvoir », on
relance le Workflow avec `{promote:true}`. Il merge la branche sur main (deployer), redéploie main, et
**rejoue la même recette sur main** (recetteur) pour vérifier que ce qui a été validé sur la branche
tient une fois mergé. C'est tout : la mise en production, sa CI/CD et sa recette classique sont un
autre univers, ce loop ne les pilote pas.

**Donc, pour un run vraiment sans surveillance** : amène d'abord la story à `spec_validated` — c'est ce
que fait `/full-spec` en une passe, gates comprises — *puis* lance `/run-story`. Lancé sur un `draft`, il
fera des allers-retours, et c'est normal : c'est là que vit le jugement.

## Le principe

Tu **lis l'état**, tu fais l'étape correspondante, tu **avances l'état**, tu recommences. Tu ne demandes
rien à l'humain qui soit dans ton périmètre — pour ça, il y a `harry-archi`.

```
sdlc --project <PREFIX> get <STORY>     # d'où on part
```

| État lu | Ce que tu fais | Puis |
|---------|----------------|------|
| `draft` | `/scope` puis `/refine` (ou `/full-spec` si le besoin est déjà clair) | ↓ |
| `spec_func` | **GATE FONCTIONNELLE** : `harry-archi` sur le PRD + les spec-func (de préférence l'**épic** en batch) → escalades → `validate-func --review` | ↓ |
| `spec_func_validated` | `/spec-tech` | ↓ |
| `spec_tech` | **GATE TECHNIQUE** : `harry-archi` sur les invariants → escalades → `validate-spec --review` | ↓ |
| `spec_validated` | `/implement` (qui ouvre la bulle scopée en premier) | ↓ |
| `implemented` | `Workflow({scriptPath:'~/.claude/workflows/run-ticket.js', args:{ticket,epic,prefix,repoName,branch}})` | ↓ |
| `reviewed` / `deployed` | reprends le workflow là où il s'est arrêté (`reviewOk:true` après une review approuvée) | ↓ |
| `recette_ok` | **RECETTE MANUELLE** (cf. boucle externe) — KO ⇒ `pm` + `reject --to implemented` + relance ; OK ⇒ **STOP, gate humaine** | — |

Après chaque étape : `set-status`, et **relis** l'état plutôt que de supposer où tu en es.

## La boucle externe — elle se déclenche sur le VERT, pas sur l'échec

C'est le point le plus contre-intuitif du mode op, et celui qu'on rate le plus souvent.

**Dans** le workflow, une recette KO est déjà traitée : `run-ticket` rappelle le fixer, redéploie,
re-recette, et boucle — `MAX_FIX = 2`, puis `needs_human`. Cette boucle-là ne te concerne pas.

**Ce qui te concerne, c'est quand la recette agent passe au VERT.** Un `recette_ok` rendu par un agent
n'est pas une conclusion : c'est un candidat. Un recetteur peut être trompé par un mock, une assertion
molle, un « l'écran s'affiche ». Tu reprends donc la main pour une **recette manuelle**, en session, et
c'est elle qui fait foi.

```
Workflow ──▶ recette_ok  (candidat, pas une conclusion)
                  │
                  ▼
     RECETTE MANUELLE en session — UI (Playwright MCP) ET/OU API
     assertions CHIFFRÉES, sur le DÉPLOYÉ, en croisant les deux
                  │
      ┌───────────┴───────────┐
     KO                      OK
      │                       │
      ▼                       ▼
 1 `pm` par bug          `sdlc journal` ──▶ ══ GATE HUMAINE ══ ──▶ {promote:true}
 `sdlc journal`
 `reject --to implemented`
 un bundle repro dans <STORY>/repro/
      │
      ▼
 Workflow({ …, fixFrom:'<STORY>/repro/<bundle>' })   ← RÉ-ENTRÉE AU FIXEUR, pas au début
      │
      ▼
 ╔════════════════════════════════════════════════╗
 ║   fixer ──▶ deployer ──▶ recetteur             ║   ← LE loop engineering
 ║      ▲                        │                ║
 ║      └──────── KO ────────────┘   (MAX_FIX=2)  ║
 ╚════════════════════════════════════════════════╝
      │  vert
      ▼
 retour à la RECETTE MANUELLE ci-dessus
      └────────── jusqu'à épuisement du stock de bugs ──────────┘
```

**La ré-entrée se fait au FIXEUR, pas au début.** `fixFrom` saute la review et le premier déploiement :
ils sont déjà faits, les rejouer coûterait une review complète pour rien. `Prepare` reste joué — il
assure le worktree et il est idempotent.

**Tu ne sors de cette boucle que sur une recette manuelle verte.** Pas sur un `recette_ok` d'agent, pas
sur « il ne reste que des broutilles » : les broutilles deviennent des items `pm`, et on repasse.

L'autre sortie, `needs_human` (le workflow a renoncé après ses deux fix-loops), suit le **même** chemin :
journalise l'arrêt, puis recette manuelle pour comprendre ce qui bloque, `pm`, correction, relance.

```
sdlc journal <STORY> --entry "workflow: <stopped_at>/<reason> — <ce que dit l'agent>"
   ↑ AVANT tout le reste : ce retour ne vit QUE dans la conversation
```

## Périmètre — ce que tu fais sans demander, ce que tu ne fais jamais

**Sans demander** : les gates de spec via `harry-archi`, ouvrir la bulle, coder, pousser la branche,
ouvrir la MR, déployer une **branche** en intégration, recetter, corriger, relancer, consigner en `pm`,
merger tes **propres** MR validées vers le **trunk d'épic**.

**Jamais sans l'humain** : la **promote** (`main` / prod), l'accept final, et tout ce qu'un
`harry-archi` t'a explicitement escaladé. Le loop ne s'auto-accorde jamais une gate humaine.

**En cas de doute qui n'est pas une gate** : `harry-archi`, pas l'humain. C'est son rôle — il tranche
dans son périmètre et escalade le reste.

## Deux pièges déjà payés

- **Pas de trunk d'épic ?** Alors la branche cible `main`, et le merge **est** la promote — donc une gate
  humaine. Vérifie la stratégie de branches du `refine.md` avant de conclure que tu peux merger.
- **Quelle cible de déploiement, et ai-je le droit ?** Le loop déploie deux fois, en environnements
  **logiques** : phase **Deploy** → `dev`, phase **Promote** → `integration`. La résolution est
  mécanique — `sdlc deploy-target <repo> --env dev|integration` — et rend la cible concrète **avec son
  skill**, qui peut différer d'un environnement à l'autre. **`autoDeploy` décide** : absent ou `false`,
  la phase est une gate humaine et le run s'arrête à `implemented` + review en le disant ; `true`, on y
  va même si `label` vaut `prod`. Une cible étiquetée prod se journalise toujours.

## Sortie

À chaque palier, une ligne : l'état atteint, l'artefact écrit, le prochain actionnable. À l'arrêt : où tu
t'arrêtes, **pourquoi**, et ce qu'il faut de l'humain pour repartir.
