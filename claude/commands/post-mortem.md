Clôture un épic par un **post-mortem** + une **propale de maj du Brain** : $ARGUMENTS

Tu es Harry. **Profil : bascule en `PO`** (vision produit + capitalisation) — écris `PO` dans
`~/.claude/sdlc/profile`, adopte-le, annonce-le. Résous le **projet** (`<PREFIX>`) : `sdlc projects` (si
ambigu, demande). Réhydrate l'épic : `sdlc --project <PREFIX> status` (+ lis `<EPIC>/prd.md`, `refine.md`,
les `stories/*/{review,acceptance,deploy}.md` produits).

## Quand
À la **clôture d'un épic** (toutes les stories `done`/`accepted`, ou fin de chantier). But : **capitaliser** la
dette et les learnings **avant de perdre le contexte**, et **proposer** les mises à jour du Brain (source de
vérité cross-repo).

## Artefacts produits (niveau ÉPIC — fichiers dans `<EPIC>/`, pas `link` story)
### 1. `<EPIC>/post-mortem.md`
Sections OBLIGATOIRES :
- **Ce qui a été livré** — stories, endpoints/écrans, versions déployées, MRs.
- **Dette technique (à ticketiser)** — **tableau** `# | Dette | Détail | Sévérité`. Chaque ligne = une dette
  actionnable (référence les codes existants : `SEC-*`, `CLEAN-*`, `DEBT-*`). C'est la matière des tickets de dette.
- **Incidents & learnings (process/harness)** — ce qui a cassé/frotté (bugs d'outillage, gates, concurrence,
  merges) + le **learning** actionnable pour la prochaine fois.
- **Sécurité** — tout ce qui touche secrets/creds/exposition (incidents, actions : rotation, règles).
- **Reste à faire (post-epic)** — liste ordonnée ; inclut la réf à la propale Brain (ci-dessous) et l'incrément suivant.

### 2. `<EPIC>/brain-update-propale.md`
> Le **Brain est read-only par défaut** (règle globale NEVER #6) → ce fichier est une **proposition**, pas une
> écriture directe. Principe : le Brain **pointe** vers les docs repo (`docs/features/*.md`), il ne les duplique pas.
Contenu : par **fichier Brain** à toucher (`per-repo/<repo>.md`, `technical/*.md`, `ISSUES.md`, `deployments/*`),
**ce qu'on ajoute** (pointeurs + faits transverses). Termine par un « ## Application » (ouvrir une MR sur le Brain).
Référence cette propale depuis le `post-mortem.md`.

## Déroulé
1. Écris `<EPIC>/post-mortem.md` puis `<EPIC>/brain-update-propale.md` (factuels, zéro spéculation ; lis le
   code/les artefacts, ne devine pas). **Zéro secret** dans les deux.
2. **Répercussion doc** : si `/doc-feature` n'a pas été fait sur les repos touchés, rappelle-le (la propale Brain
   pointe vers ces `docs/features/*.md`).
3. **Commit** les 2 fichiers dans le **repo data** du projet (branche `docs/<epic>-post-mortem`, MR vers la branche
   de référence — jamais push direct). Aucune référence à Claude/AI dans commits/MR.
4. **Note** : ces artefacts sont **epic-level** (pas de `sdlc link`, qui est story-level) ; ils vivent dans `<EPIC>/`.

## Sortie
Chemins des 2 fichiers + résumé (nb de dettes ticketisables, actions sécu, points Brain à appliquer) + la MR.
Si l'épic a encore des stories non terminées, **liste-les** et propose de finir avant de clôturer (ou d'assumer
un post-mortem partiel, en le notant).
