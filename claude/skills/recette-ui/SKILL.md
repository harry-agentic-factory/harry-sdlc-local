---
name: recette-ui
description: Recette UI autonome via Playwright MCP — pilote un navigateur pour valider une story FRONT vs les critères d'acceptation. Même modèle que la recette API mais côté UI : l'AUTH (connexion) est l'étape contrôlée (spécifique projet, creds via ENV jamais exposés) ; UNE FOIS CONNECTÉ, navigation LIBRE dans les pages. Normalise la procédure (navigate/snapshot/assert), anti-flaky, acceptance.md newest-first. À utiliser quand `recette.<repo>.tool = ui`.
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

## 3. Discipline (charge `agent-resilience`)
- **Contexte maigre** : un snapshot peut être gros → **cible la région** (ref d'élément), n'embarque pas
  toute la page. Filtre.
- `acceptance.md` = **journal horodaté, le plus récent en tête** (prepend), écrit **au fil de l'eau**.
- Sur **KO** : bundle repro dans `repro/` — `steps.md`, `browser_snapshot`, `browser_console_messages`,
  `browser_network_requests`. C'est ce que le fixer rejouera.
- **Fichiers temp dans le scratch de la bulle, jamais `/tmp`.** Jamais de secret/creds affiché.

## Sortie
Dernier message = JSON `{pass, repro, flaky, failed}`. **Ne change PAS le statut** (orchestration).

> 2-tiers : ce skill est **générique** ; l'appli/URL/login spécifiques viennent du **manifest** + d'un
> **skill projet** (ex. futur `hia-recette-ui`). Même philosophie que `recette` + `hia-recette` côté API.
