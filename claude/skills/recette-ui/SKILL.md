---
name: recette-ui
description: Recette UI autonome via Playwright MCP — pilote un navigateur pour valider une story FRONT vs les critères d'acceptation. Même modèle que la recette API mais côté UI : l'AUTH (connexion) est l'étape contrôlée (spécifique projet, creds via ENV jamais exposés) ; UNE FOIS CONNECTÉ, navigation LIBRE dans les pages. Normalise la procédure (navigate/snapshot/assert), anti-flaky, acceptance.md newest-first. À utiliser quand `recette.<repo>.tool = ui`.
---

# Recette UI (Playwright MCP) — pendant de la recette API

**QUOI** = critères d'acceptation (`spec-func.md`). **COMMENT** = piloter le navigateur via les tools
`mcp__playwright__*` (charge-les via ToolSearch si absents). Le paramétrage vient du manifest
(`recette.<repo>` : `uiUrl`/`baseUrl`, `auth`) + un éventuel **skill projet** (sélecteurs/URL de login).

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
