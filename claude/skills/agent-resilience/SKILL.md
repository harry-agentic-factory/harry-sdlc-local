---
name: agent-resilience
description: Discipline de contexte & résilience pour tout agent autonome LONG (recette, deploy, fix, migration…) qui enchaîne beaucoup d'appels d'outils et de gros résultats. Évite les morts sur « Connection closed mid-response » en gardant le contexte maigre, en persistant l'avancement au fil de l'eau, en réutilisant les ressources et en étant resume-safe. À charger au démarrage de toute tâche longue/multi-étapes.
---

# Résilience d'un agent long

Un agent qui accumule beaucoup d'appels d'outils + de **gros résultats** voit son **contexte gonfler** ;
chaque tour ré-embarque tout le contexte → requêtes et réponses volumineuses → **fragilité aux coupures**
de la connexion à l'API du modèle (`Connection closed mid-response`). **Ce n'est pas ta logique, c'est la
taille.** Applique cette discipline **du début à la fin** :

1. **Filtre ce qui entre dans le contexte.** Ne dumpe **jamais** une réponse/log entier. Extrais à la
   source : `jq` pour du JSON, `grep`/`tail` pour des logs, `?tree=…` sur les API qui le supportent. Vise
   des sorties **< ~2 Ko**. N'affiche que ce que tu vas **asserter** ou **décider**.
2. **Persiste au fil de l'eau.** Écris chaque résultat/étape dans **l'artefact de ton étape**
   (`acceptance.md` / `deploy.md` / `implement.md` / …) **dès qu'il est établi**, pas à la fin. Si tu es
   coupé, rien n'est perdu.
3. **Sois resume-safe.** Si tu **reprends** après une coupure : **relis d'abord ton artefact** (ce que tu
   as déjà fait), puis **continue** à l'étape suivante. **Ne recommence jamais de zéro.**
4. **Réutilise les ressources.** Garde vivants token, port-forward, crumb, env local, session — ne les
   recrée pas à chaque itération. Nettoie en **fin** de tâche.
5. **Découpe si ça s'allonge.** Au-delà de ~25-30 appels d'outils (ou plusieurs gros résultats), écris un
   **point d'avancement** (fait / restant) dans ton artefact avant de continuer.
6. **Cible tes re-vérifs.** Rejoue seulement l'**assertion clé** (une commande filtrée), pas tout le
   parcours.
7. **Fichiers temporaires / scripts → dans TON workspace, jamais `/tmp`.** Écris tout script/fichier
   jetable dans le **scratch de ta bulle** (`<workspace>/scratch/`, fourni par `sdlc workspace`) ou, à
   défaut, le dossier du ticket. `/tmp` est **hors de ton périmètre** → **popup de permission** + fichier
   non contenu/non nettoyé. Le scratch, lui, est dans ton périmètre et part avec la bulle.
8. **⛔ BORNE TOUTE OP BLOQUANTE — JAMAIS DE HANG.** *(règle apprise à la dure : un agent s'est figé **9h** sur
   un `kubectl port-forward` lancé en direct.)* Certaines commandes **ne rendent jamais la main** :
   `kubectl port-forward` (bloquant par nature), un `while … done` de **polling sans max d'itérations**, un
   `mvn`/`npm`/`curl` qui pend sur le réseau. **N'en lance AUCUNE en direct.** Deux réflexes :
   - **Wrappers bornés** (dans `deploy-jenkins/scripts/`) :
     `bash <…>/safe_run.sh <timeout_sec> -- <cmd…>` (borne n'importe quoi ; rc=124 si dépassé) ·
     `bash <…>/pf_curl.sh <ns> <deploy> <port> <path> [curl…]` (port-forward + curl + kill, borné).
   - **Tout poll a un plafond** : `for i in $(seq 1 40); do … ; sleep 20; done` (≤ ~13 min) **puis bail**
     (`{ok:false, note:"timeout"}`), jamais de boucle infinie. Sur `sleep` en foreground bloqué par le harness,
     mets le `sleep` **dans** une commande composée.
   L'orchestrateur te **ping** via le mtime de ta sortie (cf. « Watchdog orchestrateur » plus bas) : au-delà
   du seuil de ton type d'agent (~10 min), tu es considéré **figé** → tué et **relancé** en resume.
9. **Émets un heartbeat (obligatoire pour être ping-able).** Le ping orchestrateur repose sur le **mtime** de
   ta sortie, qui n'avance qu'à chaque appel d'outil. Donc : **AVANT toute op potentiellement longue**
   (build, déploiement, attente CI, gros poll) et **au moins toutes les ~5 min**, écris une **ligne de
   heartbeat** dans ton artefact d'étape — ex. `PREPEND` `- <ISO 8601> ⏳ <ce que je fais / j'attends>`. Sans
   heartbeat, une op longue mais saine peut être prise pour un gel (faux positif) ; avec, un vrai gel est
   détecté vite. Un `safe_run.sh`/poll borné suffit à faire avancer le mtime — mais trace quand même l'étape.

## Watchdog orchestrateur — ping mtime & relance (côté orchestrateur / Harry)
Un agent qui gèle **sans notifier** bloque toute l'orchestration (vécu : un déployeur figé **~7h** sur un
build, jamais tué). Les agents lancés par le **Workflow tool** ont déjà un watchdog mtime intégré ; ceux
lancés **en direct** (Agent tool : deployer, recetteur, fixer…) **n'en ont pas** → c'est à l'orchestrateur
de les surveiller. Protocole **obligatoire** pour tout agent long lancé en direct :

1. **Enregistre** à chaque spawn : `{task-id, fichier .output, rôle, seuil}`. Le `.output` (transcript JSONL)
   est touché à chaque appel d'outil → son mtime = signal de vie.
2. **Ping** périodiquement (à ~½ du seuil) avec le helper :
   `bash claude/scripts/agent_watchdog.sh <seuil_s> <fichier.output>...` (ou `--dir <tasks_dir>`).
   Sortie `OK/STALE/MISSING` + **exit 2** si un agent est figé. Planifie le ping via `ScheduleWakeup`
   (fallback long, ≥ ½ seuil) ou une boucle `Monitor` bornée — **jamais** un `sleep` bloquant en direct.
   ⚠️ **Ne ping QUE les agents encore en cours** (ceux dont tu n'as pas reçu la notif de fin) : le `.output`
   d'un agent **terminé** est lui aussi STALE (il n'écrit plus) — le confondre avec un gel relancerait un
   agent déjà fini. Le mode `--dir` est pratique mais filtre toi-même sur tes task-ids encore vivants.
3. **Seuils par type** (s) : `deployer 600` · `recetteur 600` · `fixer 720` · `reviewer 600` ·
   `nonreg-runner 600` · défaut `720`. (Un agent sain émet un heartbeat ≤ 5 min, cf. règle 9.)
4. **STALE → relance en resume** : `TaskStop <task-id>`, puis **relance un agent frais** avec (a) l'ordre
   *« REPRISE — relis d'abord ton artefact, NE recommence pas de zéro, continue »* et (b) les **faits déjà
   acquis** (ex. « CI #155 SUCCESS, image X poussée → fais UNIQUEMENT le CD + vérif »). Le resume-safety
   (règles 2-3) rend l'agent idempotent.
5. **Plafonne les relances** (≤ 2) : au-delà, **escalade à l'humain** (le gel est probablement systémique :
   creds, réseau, gate). Consigne un `pm add --kind incident`.

> Ne prédis/n'invente **jamais** le résultat d'un agent : le ping ne lit que le mtime, pas le contenu. Tant
> que l'agent tourne (OK) et n'a pas notifié sa fin, son verdict est inconnu.

## Artefacts = journal horodaté, le plus RÉCENT en tête
Ton artefact d'étape (`review.md` / `deploy.md` / `implement.md` / `acceptance.md`) est un **journal**,
pas un fichier écrasable. À chaque run :
- **PREPEND** une section datée en **tête** : `## <ISO 8601> — <résumé 1 ligne>` (newest-first), puis le
  détail. **N'écrase JAMAIS** les entrées précédentes (v1/v2, itérations de fix-loop) — elles descendent.
- Le bloc du **haut** = le run **le plus récent** → un `## Recap` en tête reflète toujours le dernier état,
  et `sdlc status` lit cette tête.
- Même sémantique que `journal.md` (décisions de gate) : historique préservé, lecture immédiate du récent.

> Les skills d'étape (`recette`, `deploy-jenkins`, …) et les agents longs (recetteur, deployer, fixer)
> **chargent ce skill** et n'en dupliquent pas le contenu.

## Consigne la dette/les learnings au fil de l'eau
Dès que tu rencontres une dette, un incident, un learning (process/harness) ou un point sécu, **consigne-le**
sans attendre la fin — un item survit à une coupure et remonte au post-mortem d'épic :
`sdlc --project <PREFIX> pm add --agent <ton-rôle> --kind <debt|learning|incident|security|brain> [--epic E --story S] --text '...'` (**jamais de secret** dans le `text`).
