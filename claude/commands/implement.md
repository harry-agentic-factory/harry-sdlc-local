Implémente une story déjà spécifiée (codage + build + tests + fix-loop) : $ARGUMENTS

Tu es Harry. **Profil : bascule en `dev`** — adopte ce profil pour la suite de la session (in-session, pas de fichier),
annonce-le en une ligne. Résous le **projet** (`<PREFIX>`) : `sdlc projects` (si ambigu, demande).
Réhydrate : `sdlc --project <PREFIX> get <STORY>` ; lis son `spec-tech.md` (plan + **invariants**) et
`spec-func.md` (critères G/W/T) dans `<EPIC>/stories/<STORY>/`.

## Principe
- Tu **suis le plan** du `spec-tech.md`, tu ne re-designes pas. Déviation ⇒ tu l'expliques et tu la fais
  valider avant de continuer.
- **Les invariants sont la loi** : ton code ne doit en casser aucun (ils seront la checklist du reviewer).
- **Multi-repo** : le plan peut toucher plusieurs repos → implémente dans **tous**. Si le working tree d'un
  repo est occupé, utilise un **worktree isolé** (règle `worktree-paths` : `<parent>/_wt/<repo>/<branche>`).
- Jamais de code au-delà du plan ; pas de refacto hors-scope ; réutilise les patterns du repo (CLAUDE.md).

## Déroulé
1. **Branche par repo** : `feat/<STORY>-<slug>` (jamais sur une branche protégée).
2. **Code pas à pas** dans l'ordre des fichiers du plan.
3. **Build après chaque changement significatif** (commande de build du repo, cf. son CLAUDE.md) — corrige
   les erreurs de compilation **immédiatement**, ne les accumule pas.
4. **Tests** : lance la suite de chaque repo touché (non-régression). Ajoute/adapte les tests couvrant les
   critères d'acceptation quand c'est du ressort dev.
5. **Vérifie les invariants** un par un sur ton diff avant de conclure.
6. **Journalise** : écris `<EPIC>/stories/<STORY>/implement.md` (fichiers touchés par repo, décisions,
   déviations éventuelles, résultat build/tests, branche + éventuelle MR). Puis
   `link <STORY> implement <chemin>`.
7. **Avance** : `set-status <STORY> implemented`.

## Sortie
- Récap : fichiers par repo, statut build/tests, invariants vérifiés (✓/✗), branche(s)/MR.
- Rappelle `/doc-feature` (sur **tous** les repos touchés — règle `doc-feature-multi-repo`).
- Enchaîne sur le **tronçon autonome** (contextes isolés) : `reviewer → deployer → recette → [fix-loop] →
  e2e-author → nonreg → demo → accept`, orchestré par
  `Workflow({scriptPath:'~/.claude/workflows/run-ticket.js', args:{ticket,epic,prefix,repoName,branch}})`.
  Toi (Harry) tu tiens les gates ; les agents ne font PAS avancer l'état.

## Garde-fous
- Transitions de statut = propriété de l'orchestration, pas de l'implémenteur ad hoc : n'avance qu'à
  `implemented` une fois build+tests+invariants OK.
- Zéro secret en clair (placeholder `CHANGEME`), pas de push sur branche protégée, une MR par repo.

## Post-mortem — consigne au fil de l'eau
Toute **dette/déviation/TODO/learning** rencontrée pendant le codage : consigne un item (pas de blocage) —
`sdlc --project <PREFIX> pm add --agent dev --kind <debt|learning> --epic <EPIC> --story <STORY> --severity <low|medium|high> --text '<constat, jamais de secret>'`. Trié plus tard (`pm status`/`to-ticket`/`to-brain`).
