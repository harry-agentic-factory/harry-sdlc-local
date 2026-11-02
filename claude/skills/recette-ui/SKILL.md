---
name: recette-ui
description: "Recette UI autonome via Playwright MCP — pilote un navigateur pour valider une story FRONT vs les critères d'acceptation. Même modèle que la recette API mais côté UI : l'AUTH (connexion) est l'étape contrôlée (spécifique projet, creds via ENV jamais exposés) ; UNE FOIS CONNECTÉ, navigation LIBRE dans les pages. Normalise la procédure (navigate/snapshot/assert), anti-flaky, acceptance.md newest-first. À utiliser quand `recette.<repo>.tool = ui`."
---

# Recette UI (Playwright MCP) — pendant de la recette API

**QUOI** = critères d'acceptation (`spec-func.md`). **COMMENT** = piloter le navigateur via les tools
`mcp__playwright__*` (charge-les via ToolSearch si absents). Le paramétrage vient du manifest
(`recette.<repo>` : `uiUrl`/`baseUrl`, `auth`) + un éventuel **skill projet** (sélecteurs/URL de login).

## 0. Ressource partagée : verrou Playwright (multi-agent / multi-session)
Le navigateur Playwright MCP est un **singleton mutable** : cookies + session de login **partagés**, pas de
contexte isolé par appelant (les onglets `browser_tabs` partagent les cookies). Donc **deux usages concurrents
se corrompent** (un login écrase l'autre → assertions faussées).
- **Avant** de piloter le navigateur, prends le **verrou de ressource** — le **seul** verrou qu'une recette
  prend (distinct du verrou de **déploiement**, que la recette ne prend pas) :
  `bash <sdlc>/claude/scripts/env_lock.sh acquire playwright--$(hostname -s) <owner> --phase recette-ui --ttl 2700`
  → `3` BUSY (un autre pilote le navigateur → **attends**) · `0`/`4` → acquiers. `refresh` à chaque tour,
  `release` à la fin (cf. skill `agent-resilience` pour le heartbeat).
- **JAMAIS 2 agents Playwright en parallèle dans la même session** : ils partagent l'unique navigateur.
- **Multi-profils** (plateforme/portfolio/mono) DANS une recette = **re-login séquentiel** dans le même
  navigateur (nettoie la session entre profils). Ce n'est PAS de la concurrence → normal, pas besoin de N
  navigateurs.
- Si chaque session a **son propre** serveur MCP (navigateurs séparés), le verrou est un **no-op inoffensif**.

## 1. Auth = étape CONTRÔLÉE, puis navigation LIBRE
- **Connexion** : `browser_navigate` vers l'appli, effectue le **login** (page Keycloak / form) avec les
  **creds du compte de test via ENV** (jamais hardcodés, jamais affichés ; un **skill projet** fournit
  l'URL/sélecteurs de login si besoin — 2-tiers, comme `hia-recette` côté API).
- **Une fois connecté → tu as le droit de NAVIGUER LIBREMENT** dans les pages (`browser_navigate`,
  `browser_click`, `browser_fill_form`) pour atteindre les écrans concernés. La contrainte porte sur
  **l'accès (auth)**, pas sur la navigation post-login.

## 2. Vérifier chaque critère (asserte sur le SNAPSHOT, pas le screenshot)
- `browser_snapshot` (arbre d'accessibilité) = **ta source d'assertion** : structuré + léger. Locators
  robustes (`getByRole`/`.first()`, strict-mode). `browser_wait_for` l'état attendu (anti-flaky).
- Vérifie chaque critère G/W/T contre ce que l'écran **affiche réellement** (pas ce que l'API renvoie —
  ça c'est la recette API ; ici c'est le **rendu**).

## 2 bis. Comparaison à la maquette (si la spec en référence une)
Dès que `spec-func.md` porte une section `## Fidélité à la maquette`, cette étape est **obligatoire** et vient
**avant** de conclure. Elle a attrapé ce que 99 contrôles d'alignement au pixel avaient laissé passer : un écran
livré sans ses icônes, sans son trait de liaison, et en italique, alors que la maquette validée les montrait.

1. **Servir la maquette en local** et rendre l'écran **aux mêmes largeurs** (celles des critères de géométrie de
   la story).
2. **Captures côte à côte** dans `acceptance.md`.
3. **Élément par élément**, lire la table de la spec et mesurer le réel :
   `sdlc maquette extract <spec-func.md> > <scratch>/checklist.json`, puis, pour chaque ligne, lire la valeur avec
   `browser_evaluate` — `getComputedStyle(el).<propriété>`, `getComputedStyle(el, '::before').<propriété>` pour un
   pseudo-élément, le nom de l'icône rendue pour `icône`, l'existence du nœud pour `présence`. Écrire
   `{"<id>": {"obtenu": "<valeur>"}}` dans `<scratch>/mesures.json`, puis
   `sdlc maquette verdict <scratch>/checklist.json <scratch>/mesures.json` — **code de retour 1 s'il y a un
   écart**, et la sortie va dans `acceptance.md`.
4. **Puis** les mesures d'alignement au pixel, qui closent l'étape.

Une ligne de la table **sans valeur obtenue** rend la passe invalide : tu ne peux pas conclure `pass`. Un écart à
une maquette **validée par un humain** ne se tranche pas — tu le remontes.

## 3. Discipline (charge `agent-resilience`)
- **Contexte maigre** : un snapshot peut être gros → **cible la région** (ref d'élément), n'embarque pas
  toute la page. Filtre.
- `acceptance.md` = **journal, le plus récent en tête** (ajout en tête), écrit **au fil de l'eau**, au format FIXE de
  la skill `recette` (Recap, Environnement et méthode, Verdict par AC, Repro).
- Sur **KO** : bundle repro dans `repro/` — `steps.md`, `browser_snapshot`, `browser_console_messages`,
  `browser_network_requests`. C'est ce que le fixer rejouera.
- **Fichiers temp dans le scratch de la bulle, jamais `/tmp`.** Jamais de secret/creds affiché.

## Sortie
Dernier message = JSON `{pass, repro, flaky, failed}`. **Ne change PAS le statut** (orchestration).

> 2-tiers : ce skill est **générique** ; l'appli/URL/login spécifiques viennent du **manifest** + d'un
> **skill projet** (ex. futur `hia-recette-ui`). Même philosophie que `recette` + `hia-recette` côté API.

## Workspace de run

Si le prompt fournit `IN`, `OUT` et `CODE` (mode run workspace, projet en `runWorkspace: true`), ces règles
remplacent les chemins de story, les worktrees et les transitions décrits plus haut :
- **Lire** : `sdlc doc read <clé> --run <root>` (`spec-tech`, `spec-func`, `prd`, `brain/<chemin>`… ; liste :
  `sdlc doc list --run <root>`) ou les fichiers de `IN`, en lecture seule. Jamais le dépôt data.
- **Écrire** : brouillons (et notes de reprise « au fil de l'eau ») dans `<root>/rw/scratch/`, jamais dans un
  dossier temporaire système ; puis **un seul** `sdlc doc add acceptance <fichier> --run <root>` en fin, avec une
  section `## Recap`.
- **Code** : `git -C CODE …`, commits sur la branche de la story ; **jamais** de push, de `git remote`, de
  `sdlc link` ni de changement de statut : l'orchestration publie (`sdlc run finish`) et transitionne.
- Commandes d'état et de config permises : `sdlc get`, `sdlc config`, `sdlc deploy-target`, `sdlc pm add`.
- **Recette** : vérifie d'abord que la version déployée = `git -C CODE rev-parse HEAD`. Sur KO, le bundle repro va
  dans `OUT/sources/repro/` (`steps.md`, `env.md`, `fixtures.md`, traces) et le verdict porte
  `repro = "run:<RUN_UID>"` ; il sera publié avec le run et remis au fixer dans `IN/repro/`.
Sans `IN`/`OUT` : les instructions ci-dessus s'appliquent inchangées.
