# Workflow Implement & modes d'engagement du coding

> Design du harness SDLC « Harry » — la **phase implement** (transition `spec_tech → reviewed`) et les
> **modes d'engagement du coding**. Cross-projet (agnostique). Les exemples viennent du projet **HIA**
> (repo open-source → référence assumée). Validé 2026-07-27.

## Principe
On n'alourdit **pas** le `spec-tech` pour qu'il « fasse » l'implém : il reste un **plan léger + invariants**.
Le **détail émerge DANS l'implement**, en **boucle**. L'interactif de valeur vit dans l'**affinage du plan**
(scope → refine → spec-func → spec-tech, gates humaines) ; une fois le plan verrouillé, le coding est de
l'**exécution** pilotée en boucle.

## La phase Implement = une boucle 2-étages
Entrée : **spec-tech** (plan léger + invariants) + **spec-func** (critères d'acceptation = **oracle « done »**).
Deux rôles **distincts** : l'**implement-agent** (orchestrateur de la phase) ≠ le **coding-agent** (écrit le code).

- **Boucle interne** (par itération) : sous-plan → le *coding-agent* code → **checks machine** (build/lint/test)
  → l'implement-agent **observe + réajuste**. L'implement-agent **découpe le ticket en sous-plans** (todo) et
  checkpointe. → **le coding-agent est un OUTIL de la boucle, pas la boucle.**
- **Acceptation par boucle** = **checks machine + jugement de l'implement-agent** (rapide). ⚠️ le jugement LLM
  seul est faible (auto-biais) → l'objectivité **par boucle** vient des **checks machine**, rejoués à chaque tour.
- **Gate de sortie** (une seule fois, quand « done » selon l'acceptation) = **reviewer indépendant** (contexte
  séparé) sur **tout le diff** vs invariants → conforme ⇒ `reviewed` ; rejet ⇒ **retour boucle interne**
  (fix-loop). C'est l'**oracle anti-biais**.
- Le reviewer externe n'intervient **pas** à chaque boucle (trop lourd/cher) — **en sortie** seulement.

## Les 3 modes (même machinerie ; le curseur = QUI tient la boucle interne)

| Mode | Qui tient la boucle interne | Humain | Quand |
|---|---|---|---|
| **A · Full-auto** | un **agent ORCHESTRATEUR (session auto)** qui **possède la boucle ET pilote les gates** : spawn coding-agent → checks → observe → réajuste → re-spawn ; puis lance le reviewer, sur rejet reboucle, enchaîne deployer → recetteur | absent / async | acceptation **machine-vérifiable**, faible risque produit |
| **B · Interactif + agents** | l'**humain** observe/affine à chaque boucle ; le(s) coding-agent(s) codent | présent, pilote | décisions produit/UX, changement sensible |
| **C · Session libre** | l'**humain (+assistant)** code **en direct**, sans coding-agent | code lui-même | petit / critique, ou pas d'agent dispo |

> ⚠️ **Mode A = orchestrateur, PAS un coding-agent one-shot.** Piège classique : lancer un agent généraliste
> « implémentateur plat » qui fusionne implement + coding, code **en one-shot sans boucle** et **sans orchestrer
> les gates** = **version dégénérée** de A (≈ un coding-agent invoqué une fois). Le vrai mode A = ce que fait
> l'orchestrateur humain-en-session pour une story, **rendu autonome**.

## L'invariant qui rend les modes interchangeables
**Quel que soit le mode → mêmes artefacts normalisés.** La suite (reviewer → deployer → recetteur) ne voit
**aucune** différence. Le **mode C = livrable identique à un coding-agent**. Contrat de sortie de l'implement :

- `implement.md` : **sous-plans** · **diff résumé** · **décisions / déviations** · **dettes trouvées**
- branche `feat/<TICKET>` + **MR/PR**
- transition d'état `set-status implemented`
- **tests + résultat des checks machine**

## Dispatch — quel mode ? (décidé **en sortie de spec-tech**)
Heuristique sur 4 axes (fournis par le spec-tech : fichiers, invariants, cross-repo, tests) :
- **Taille** : petit → C · gros → A
- **Criticité** : haut risque → C (contrôle) · bas → A
- **Itération-live** (besoin de tourner contre un env pour finir) → A
- **Parallélisable** (N stories indépendantes) → **fan-out** : 1 agent / story + **worktree** d'isolation

**Règle** : *par défaut C ; on délègue (A) dès qu'un axe « agent » domine ET que le risque est faible.*
**Curseur adaptatif** : A peut **redescendre en B** sur blocage / ambiguïté produit (ne pas figer le mode au
lancement ; persister la surface d'observation pour permettre la reprise humaine à tout moment).

## Garde-fous (surtout pour A/full-auto)
1. **Oracle « done » machine-vérifiable** obligatoire (tests, asserts API, build) — sinon la boucle **dérive ou
   sur-conçoit**. Le budget d'ingénierie va **là**, pas dans les modes.
2. **Vérification indépendante** en sortie : le reviewer ≠ le codeur (contexte/prompt distinct) — ne jamais
   laisser le coding-agent s'auto-noter comme acceptation finale.
3. **Bornes** : max d'itérations + budget tokens + review gate.
4. **Escalade** : full-auto ne remonte que sur **blocage** ou **décision produit** (route vers l'humain ou un
   agent « architecte/décideur »).

## Validation empirique (projet HIA, session 2026-07-27)
- **HIA-SETTINGS-1/2/3 = mode C** (l'orchestrateur code en session, artefacts normalisés) → reviewer / deployer /
  recetteur ont **enchaîné sans friction**. Les checks machine par boucle (build, e2e 8/8) + la **recette live**
  (indépendante) ont rattrapé les bugs — dont **CA4**, invisible en mock, capté **en live**. Preuve : l'objectivité
  vit dans les **checks machine + la vérif indépendante en sortie**, pas dans l'auto-review de l'orchestrateur.
- **HIA-E2E-1 = tentative mode A dégénéré** (implémentateur plat, sans boucle ni orchestration des gates) : le
  corpus a été construit + testé live, mais la **gate reviewer restait à faire** → confirme que **A doit être un
  orchestrateur**, pas un coding-agent one-shot.

## Statut d'implémentation dans le harness
- **À faire** : matérialiser `dispatch` comme step explicite en sortie de spec-tech (champ porté par
  l'artefact spec-tech) ; l'agent orchestrateur du mode A (au-delà de l'actuel `run-ticket` review→deploy→recette,
  qui **suppose déjà implémenté**) ; le contrat `implement.md` normalisé commun aux 3 modes.
