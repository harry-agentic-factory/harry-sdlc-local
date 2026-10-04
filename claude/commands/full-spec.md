Cadre un besoin de **bout en bout en un seul passage** — PRD + refine + stories + spec-func + spec-tech : $ARGUMENTS

**Profil : bascule en `solo`** — adopte ce profil pour la suite de la session (in-session, pas de fichier), sans l'annoncer (« Écrire pour un humain »). `solo` = **mono-user qui porte toutes les casquettes** (PO+BA+techlead ; mode fondateur/CTO qui
tranche). Tu produis **tous les docs d'un coup** et tu avances l'état, au lieu de dérouler
`/scope → /refine → /spec-func → /spec-tech` séparément.

Résous d'abord le **projet** (`<PREFIX>`) : `sdlc projects` (si ambigu, demande). Les docs vont dans le
**repo data** du projet ; toutes les commandes sont `sdlc --project <PREFIX> …`.

## Principe
- **One-shot, pas ping-pong** : ne pose QUE les questions **bloquantes** (un PRD ou un critère
  d'acceptation qu'on ne peut pas trancher sans l'humain). Sinon, tu décides et tu annonces tes choix.
- **Factuel** : lis le **Brain du projet** s'il existe (pointé par `sdlc config` → `.brain`) + le code des
  repos concernés. N'invente rien (chiffre/nom/contrat non trouvé ⇒ demande).
- **Adaptatif** : besoin trivial → PRD léger, 1 story, **spec-func skippée** (direct spec-tech) ;
  besoin riche → PRD complet, N stories avec DAG, spec-func (G/W/T) + spec-tech (invariants) par story.

## Déroulé (une passe, dans l'ordre)

### 1. PO — PRD (le besoin)
Écris `<EPIC>/prd.md` au **format FIXE** de `/scope` (`## Contexte`, `## Besoin`, `## Périmètre`,
`## Hors périmètre`, `## Critères de succès`, `## Sources`). Alloue l'ID épic (`<PREFIX>-<n>`). Puis `sdlc --project <PREFIX> create-epic <EPIC> "<titre>"`.

### 2. PO — Refine (les stories + le DAG)
Découpe en **stories** (1 task/story ; simple = 1 story). Établis les **dépendances** (DAG **sans cycle**),
l'ordre, ce qui va en parallèle, et les **repos touchés** par story. Écris `<EPIC>/refine.md`
au **format FIXE** de `/refine` (`## Stories` avec le tableau puis un `### <STORY> — <titre> · deps: … · repos: …`
par story, `## Ordre suggéré`, `## Protocole de branches`, `## Sources`). Crée chaque ticket :
`sdlc --project <PREFIX> create-ticket <EPIC> <STORY> "<titre>" --deps a,b --repos x,y`.
Vérifie : `sdlc --project <PREFIX> next <EPIC>` renvoie bien les stories sans dépendances d'abord.

### 3. Pour CHAQUE story, dans l'ordre du DAG
**a. BA — spec-func** (sauf si triviale → skip en le **notant**) : comportement, cas limites, messages,
droits, puis **critères d'acceptation en Given/When/Then** machine-checkables (ce que le recetteur
vérifiera). Écris `<EPIC>/stories/<STORY>/spec-func.md` au **format FIXE** de `/spec-func` (`## Comportement`,
`## Critères d'acceptation` avec un « 🔬 Must-validate » par critère, `## Tests obligatoires au build`, `## Sources`), puis `set-status <STORY> spec_func`.

**b. techlead — spec-tech** : explore le code (patterns réutilisables), **plan d'implémentation**
(guidelines, PAS le code : contrôleurs/services/entités, où brancher, contrats d'API, migrations,
cross-repo) + **Invariants OBLIGATOIRES** (garde-fous anti-régression, **assertions vérifiables sur un
diff** = la checklist du reviewer). Écris `<EPIC>/stories/<STORY>/spec-tech.md` au **format FIXE** de `/spec-tech` (`## Invariants` en
tableau, `## Plan par repo` avec un `###` par dépôt, `## Tests`, `## Sources`), `link <STORY> spec_tech
<chemin>`, puis `set-status <STORY> spec_tech`.

### 4. Gates, puis suite
Tu restes en `solo` (mono-user). **Passe les gates avant de coder** — l'agent recommande, l'humain décide, et
chacune accepte l'épic entier en batch :
`/validate-spec-func <EPIC>` (après les spec-func), `/validate-spec-tech <EPIC>` (après les spec-tech), puis
`/validate-feature <EPIC>` (PO + tech lead). Chaque gate = revue `harry-archi` en mode document →
`/process-review` → verdict **signé par l'humain** → `sdlc validate-… --verdict …` (la CLI refuse sans signature).
**Tu ne signes jamais** : ici, « one-shot » s'arrête à la signature — présente les revues, fais décider, et
reprends après. Voir `claude/commands/spec-tech.md` § Gate SPECS pour le détail. **Ensuite** `/implement` (ou
`/run-story`, qui enchaîne tout seul). Un `/harry dev` explicite est possible si tu veux repasser en profil dev pur.

> **Avant d'écrire un document vivant** du dépôt data : règle « Écrire un document vivant » de la persona (`~/.claude/sdlc/harry.md`).

## Sortie
- **Arbre des docs produits** (prd, refine, et par story : spec-func éventuel + spec-tech).
- **Tableau** stories × statut × deps × repos, + le **prochain actionnable** (`sdlc --project <PREFIX>
  next <EPIC>`).
- Propose la suite : `/implement <STORY>` (mono) ou le tronçon autonome
  `Workflow({scriptPath:'~/.claude/workflows/run-ticket.js', args:{ticket,epic,prefix,repoName,branch}})`.

## Garde-fous
- **Invariants par story = non négociables** (sans eux, pas de reviewer fiable).
- Reste **factuel** (Brain/code), zéro spéculation. **Arrête-toi** seulement si une ambiguïté empêche
  d'écrire un PRD net ou un critère d'acceptation testable — sinon tranche et avance.
- Cohérence des IDs (`<PREFIX>-<n>`), du DAG (pas de cycle) et des statuts (transitions valides).
