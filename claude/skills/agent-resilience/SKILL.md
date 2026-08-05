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
2. **Ping** périodiquement (à ~½ du seuil) avec le helper. Deux modes :
   - **Historique (préféré)** : `bash claude/scripts/agent_watchdog.sh --role <rôle> --history <store> <fichier.output>...`
     → le seuil est **appris** des runs passés : `seuil = clamp(facteur × p90(durées du rôle), floor=300, hard-cap=1800)`
     (`--factor` défaut 1.0). Verdicts `OK` / `STALE` (gap > seuil, < hard-cap) / **`HARDCAP`** (gap ≥ hard-cap) / `MISSING`.
   - **Fixe (fallback si pas d'historique)** : `agent_watchdog.sh <seuil_s> <fichier.output>...`.
   Planifie le ping via `ScheduleWakeup` (fallback long) ou une boucle `Monitor` bornée — **jamais** un
   `sleep` bloquant en direct. ⚠️ **Ne ping QUE les agents encore en cours** (sans notif de fin) : le `.output`
   d'un agent **terminé** est aussi STALE — le confondre relancerait un agent fini.
3. **Alimente l'historique** : à **chaque** fin d'agent, enregistre sa durée (lue dans la `task-notification`,
   `duration_ms`) : `bash claude/scripts/agent_record.sh <store> <rôle> <durée_s>`. Store hors repo (défaut
   `~/.claude/sdlc/agent_runs.log`, données runtime). Plus l'historique grossit, plus le seuil « anormal »
   colle à la réalité de CHAQUE type d'agent — au lieu d'un chiffre en dur qui sur- ou sous-réagit. Un agent
   sain émet un heartbeat ≤ 5 min (règle 9) → gap petit → jamais STALE : c'est LA prévention n°1 des faux positifs.
4. **STALE ≠ gel — NE TUE JAMAIS SUR UN SEUL PING.** `STALE` = « pas d'écriture depuis N s », **pas** « figé » :
   un agent peut attendre légitimement une **op longue qu'il a lancée** (build Jenkins, rollout, `mvn`). Avant
   tout `TaskStop`, **3 garde-fous cumulatifs** :
   - **(a) Grâce** : exige **≥ 2 lectures `STALE` consécutives** espacées d'au moins ~½ seuil (un seul STALE
     ne tue pas). Le harnais surveille aussi le mtime — laisse-lui sa chance.
   - **(b) Cross-check d'un signal externe de progression** hors du `.output` : deployer → **build Jenkins
     `building:true` ?** (`curl -s -n -g ".../job/.../api/json?tree=builds[number,building,result]{0,2}"`) ou
     rollout k8s en cours ; recetteur/fixer → build/`mvn`/job en cours. **Si ça progresse → l'agent attend, PAS
     figé → NE TUE PAS**, ré-arme le ping et attends la fin.
   - **(c) Heartbeat absent confirmé** : conclus au gel seulement si l'agent n'a **rien** écrit ET **aucune**
     progression externe visible.
   Après (a)+(b)+(c) → `TaskStop <task-id>` puis **relance en resume** : (i) *« REPRISE — relis d'abord ton
   artefact, NE recommence pas de zéro, continue »* + (ii) les **faits déjà acquis** (ex. « CI #157 SUCCESS,
   image poussée → fais UNIQUEMENT le CD ») pour éviter un double build. Resume-safe (règles 2-3) = idempotent.
5. **`HARDCAP` prime sur le cross-check — c'est l'anti-« plusieurs heures de stale ».** Un gap ≥ hard-cap
   (~30 min) est **toujours** anormal : même un build qui se dit encore `building` depuis 30 min+ est
   lui-même **coincé** (pas juste l'agent). Donc sur `HARDCAP` : ne te contente pas d'attendre — **agit**
   (tuer/relancer l'agent ET, si le build externe est lui aussi bloqué, l'abandonner/relancer). C'est ce qui
   empêche de re-vivre le gel de 7h. La grâce (a) et le cross-check (b) ne s'appliquent qu'entre `seuil` et
   `hard-cap` ; au-delà, on ne laisse plus vivre.
6. **Plafonne les relances** (≤ 2) : au-delà, **escalade à l'humain** (gel systémique : creds, réseau, gate).
   `pm add --kind incident`.

> **Coût d'un faux kill** : tuer un agent qui buildait relance tout (double build, temps perdu, double effet
> de bord). Entre `seuil` et `hard-cap`, le défaut est **« laisser vivre »** (attendre + re-ping + cross-check).
> Au-delà du `hard-cap`, le défaut s'inverse : **on n'attend plus des heures**.

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
