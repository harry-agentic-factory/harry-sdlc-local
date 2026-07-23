Clôture un épic par un **post-mortem** + une **propale de maj du Brain** : $ARGUMENTS

Tu es Harry. **Profil : bascule en `PO`** (vision produit + capitalisation) — écris `PO` dans
`~/.claude/sdlc/profile`, adopte-le, annonce-le. Résous le **projet** (`<PREFIX>`) : `sdlc projects` (si
ambigu, demande). Réhydrate l'épic : `sdlc --project <PREFIX> status` (+ lis `<EPIC>/prd.md`, `refine.md`,
les `stories/*/{review,acceptance,deploy}.md` produits).

## Quand
À la **clôture d'un épic** (toutes les stories `done`/`accepted`, ou fin de chantier). But : **capitaliser** la
dette et les learnings **avant de perdre le contexte**, et **proposer** les mises à jour du Brain (source de
vérité cross-repo).

## Items en continu (consignés au fil de l'eau)
La dette/les learnings ne s'attendent pas la clôture : **toute commande ou tout agent** consigne un item dès
qu'il rencontre une dette, un incident, un learning process/harness, un point sécu ou une suggestion Brain :
```bash
sdlc --project <PREFIX> pm add --agent <ton-rôle> --kind <debt|learning|incident|security|brain> \
     [--epic <EPIC> --story <STORY>] [--severity low|medium|high] --text '...'   # jamais de secret
```
Le store est **append-only** (`<workspace>/post-mortem.jsonl`, robuste aux agents concurrents) : chaque item a
`id` (PM-…), `epic`, `story`, `agent`, `kind`, `severity`, `status`, `target`.

Au **post-mortem d'épic**, `/post-mortem` **agrège les items ouverts** et les intègre au `post-mortem.md` :
```bash
sdlc --project <PREFIX> pm list --status open [--epic <EPIC>]     # matière brute des sections ci-dessous
```
Puis **statue / convertit** chaque item :
- `sdlc … pm status <id> triaged|wontfix` — tri.
- `sdlc … pm to-ticket <id> --epic <DEBT_EPIC> [--repos r1,r2]` — crée une **story de dette** (→ item `ticketed`,
  `target`=story) : alimente le **tableau « Dette technique »**.
- `sdlc … pm to-brain <id>` — marque l'item pour le Brain (→ `brain`) et **suggère** une ligne de propale : la
  reporter dans `brain-update-propale.md` (le Brain reste read-only, cf. NEVER #6).

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
