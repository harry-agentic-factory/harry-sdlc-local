# Stratégies de branching SDLC (Harry)

Le harnais supporte plusieurs stratégies de branches. La **stratégie se choisit au scope de l'épic**
(cf. `/scope`, `/refine`) selon la nature du travail. Toutes respectent les règles d'or : **1 branche par story +
sa MR**, **jamais de push direct** sur une branche protégée, **worktree dédié** par story
(`<parent>/_wt/<repo>/<branche-slug>`), et l'auto-promote éventuel ne concerne **que ses propres MR validées**.

## A. Per-story off `main` (défaut pour stories isolées)

Chaque story branche off `main`, se recette sur sa branche, puis merge `main` sur validation.
- ✅ Simple, MR petites, isolation maximale.
- ⚠️ Ne convient pas quand des stories **dépendent** l'une de l'autre (la 2ᵉ ne voit pas le schéma/API de la 1ʳᵉ).
- Cible de merge = `refBranch` (`main`).

## B. Série + rebase sur la dernière validée (dépendances légères)

Stories faites **en série** ; chaque story branche off la **dernière branche validée** (ou `main` re-mis à jour
après merge de la précédente).
- ✅ Gère les dépendances sans stacking permanent.
- ⚠️ Impose la **séquentialité** (pas de parallélisme entre stories) et une discipline `fetch`/vérif du merge distant
  avant de brancher la suivante.

## C. Trunk d'épic ⭐ (**À PRIVILÉGIER POUR LES ÉPICS** multi-stories)

Un **trunk d'épic** `epic/<EPIC>` est créé off `main` (par repo touché). Chaque story branche **off le trunk**,
se recette, puis **merge dans le trunk** (MR story→trunk, **jamais** main). À la **fin de l'épic**, sur
**validation humaine**, le trunk est promu **en une seule fois** vers `main`.

```
main
 └─ epic/HIA-OBSERV                (trunk, off main)
      ├─ feat/HIA-OBSERV-0  ──merge──▶ trunk     (story 0 validée)
      ├─ feat/HIA-OBSERV-1  ──merge──▶ trunk     (branchée off trunk : voit le schéma de 0)
      └─ feat/HIA-OBSERV-4  ──merge──▶ trunk
   … puis, sur validation humaine : epic/HIA-OBSERV ──▶ main  (promote unique)
```

**Pourquoi c'est la stratégie préférée des épics :**
- Les stories **dépendantes** (schéma/API/UI d'une story consommés par la suivante) partent d'un trunk qui
  **accumule le validé** → pas de stacking fragile, pas de « tout sur une seule branche ».
- `main` **reste propre** jusqu'à une **promote unique** en fin d'épic (une seule intégration à valider/déployer).
- Chaque story garde **sa** branche + **sa** MR (revue indépendante) → traçabilité par story préservée.
- Compatible **auto/loop** : implement → run-ticket (review→deploy branche→recette→fix-loop) → **merge story→trunk** ;
  la story suivante branche off le trunk **à jour**.

**Discipline git (éviter les incidents classiques) :**
1. `git fetch` puis brancher off le **trunk à jour** (jamais un `main`/trunk local périmé).
2. **Vérifier sur le remote** que le merge story→trunk a bien atterri **avant** de brancher la story suivante.
3. Un **worktree dédié** par story ; commits sur la branche de la story uniquement (vérifier `branch --show-current`).
4. Promote finale `trunk→main` = **gate humaine** (`escalation.promote = human`).
5. Stories **hors épic** (ex. lot parqué) restent hors du trunk.

**Multi-repo** : un épic touchant plusieurs repos a **un trunk `epic/<EPIC>` par repo** ; la tranche de chaque repo
merge dans le trunk de ce repo ; la promote finale se fait repo par repo.

## Choisir la stratégie

| Situation | Stratégie |
|---|---|
| Story unique / indépendante | **A** (per-story off main) |
| Quelques stories, dépendances légères, séquentiel | **B** (rebase sur la dernière validée) |
| **Épic multi-stories (dépendances schéma/API/UI)** | **C — trunk d'épic (préféré)** |

La stratégie retenue est notée dans le `refine.md` de l'épic (section « Protocole de branches »). Le `deployer`
lit cette cible de merge : en stratégie C, une story merge vers `epic/<EPIC>` (pas `main`) ; la promote `main` est
une étape d'épic distincte, humaine.

## Checklist discipline git (toutes stratégies — non négociable)

À appliquer à **chaque** transition de story, quelle que soit la stratégie (renforcé pour C — trunk d'épic) :

- [ ] **1 branche par story + sa MR** — `feat/<STORY>` ; jamais deux stories sur la même branche.
- [ ] **Worktree dédié par story** — `<parent>/_wt/<repo>/<branche-slug>` (jamais `/tmp`), pour bosser
      plusieurs stories sans se marcher dessus. Vérifie `git -C <repo> branch --show-current` **avant tout
      commit**.
- [ ] **Jamais de push direct** sur une branche protégée (`main`, ni le **trunk `epic/<EPIC>`**) : tout passe
      par une **MR** (story→trunk, ou trunk→main pour la promote).
- [ ] **`git fetch` puis brancher off la cible À JOUR** — jamais un `main`/trunk **local périmé** (le `main`
      local peut retarder ; cible `origin/main` / `origin/epic/<EPIC>`).
- [ ] **Vérifier le merge distant AVANT la story suivante** — en série (B) ou trunk (C), confirme sur le
      **remote** que la MR précédente a bien atterri (`git ls-remote` / MR `merged`) **avant** de brancher la
      suivante off la cible à jour. Sinon la story N+1 ne voit pas le schéma/API de la story N.
- [ ] **Auto-promote = seulement ses PROPRES MR validées** — un run auto ne merge jamais une MR préexistante
      ou d'autrui ; « merge tout » = uniquement les MR de la session.
- [ ] **Promote `trunk→main` = gate humaine** (stratégie C) — `escalation.promote = human` ; une seule
      intégration à valider/déployer en fin d'épic.
