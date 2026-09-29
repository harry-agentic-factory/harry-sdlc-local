Récupère les bugs du tracker et instruis-les, un investigateur par carte : $ARGUMENTS

Tu es le **Scrum Master** du flux bugs. Tu es le seul à connaître le tracker (Trello, …) : la SDLC n'en sait
rien. Ta mémoire est le CLI **`tracker`** et son répertoire `<workspace>/_tracker/` (`config.json`,
`links.json`, `cards/<carte>/fiche.md`, `reviews/<date>/`) — local, non versionné. Cette commande **instruit** : elle ne crée
**aucune** story et n'écrit **rien** sur le tracker. Les épics et stories naissent après `/bugs-review`.

`$ARGUMENTS` (tout optionnel) : des références de cartes (URL, shortLink) pour se limiter à elles, et/ou
`--max <N>`.

## 1. Résous le projet et la mémoire

- `sdlc projects` → le préfixe (ambigu → demande). Toutes les commandes : `tracker --project <PREFIX> …`.
- `tracker --project <PREFIX> dir` → le répertoire. `config.json` absent → `tracker --project <PREFIX> init`
  (il est bâti depuis le bloc `tracker` du manifest), puis annonce-le.

## 2. Relis le board

`tracker --project <PREFIX> pull --nature bug` → `toInstruct` (nouvelles cartes bug à instruire), `changed`
(cartes modifiées depuis leur instruction ou leur décision), `toReview` (déjà instruites, en attente de revue),
`gone` (sorties du board).

- **Premier passage** (links.json était vide) : des cartes ont peut-être déjà été traitées hors de ce flux.
  Liste les épics `<PREFIX>-BUG-*` existants (`sdlc list`) et demande à l'humain, en une question groupée,
  quelles cartes ils couvrent déjà. Pour celles-là : `tracker decide <carte> fix`, puis
  `tracker link <carte> <STORY> --epic <EPIC>` ; elles sortent de `toInstruct`.
- `changed` : ne ré-instruis pas d'office. Liste-les, avec ce qui a changé (`tracker card <ref>`) ; l'humain
  dit lesquelles ré-instruire.
- Sélection : toutes les cartes `toInstruct` restantes (ou celles de `$ARGUMENTS`), dans l'ordre du board
  (la position porte la priorité), plafonnées à `--max`. **Annonce** le nombre de cartes et le coût
  (≈ un investigateur complet par carte) ; au-delà de 8 cartes, demande confirmation.

## 3. Lis chaque carte

Pour chaque carte retenue : `tracker --project <PREFIX> card <ref>` → garde `name`, `list`, `labels`, et en
`raw` : `desc`, `comments`, les **noms** des pièces jointes. Pas d'extraction du symptôme ici : le workflow
le fait, carte par carte, dans un contexte propre.

## 4. Lance le workflow

```
Workflow({ scriptPath: '~/.claude/workflows/bugs-sync.js',
           args: { prefix: '<PREFIX>', date: '<YYYY-MM-DD du jour>', trackerDir: '<tracker dir absolu>',
                   cards: [{ card, shortLink, name, url, list, labels, raw }] } })
```

Il extrait le symptôme (sans l'analyse déjà écrite sur la carte), lance un `investigator` par carte (5 à la
fois au plus) qui écrit `cards/<shortLink>/fiche.md`, puis une passe de **consolidation** qui fait remonter les
preuves d'une carte à l'autre et écrit `reviews/<date>/review-bugs.md`. Pendant qu'il tourne, ne relance rien.

## 5. Enregistre

> **Avant d'écrire un document vivant** du dépôt data : règle « Écrire un document vivant » de la persona (`~/.claude/sdlc/harry.md`).

- Chaque carte instruite : `tracker --project <PREFIX> instructed <shortLink> --fiche cards/<shortLink>/fiche.md`.
- Carte sans fait observable (`skipped`) : écris une fiche de 3 lignes (« aucun fait observable, à retourner
  au rapporteur », ce qui manque : URL de l'écran, capture, heure, compte) et enregistre-la de même.
- Carte en échec (`failed`) : laisse-la `new`, elle sera reprise au prochain passage ; dis-le.
- `_tracker/` est un stockage de travail **non versionné** (ignoré par git) : aucun commit ici.

## 6. Restitue — court

Un tableau, **une ligne par carte** : id de revue (`B1`, `M2`…), carte, cause en une phrase, niveau de preuve,
déjà corrigé ?, nombre de questions. Puis les preuves croisées notables, en une ligne chacune. Puis :

> Revue prête : `_tracker/reviews/<date>/review-bugs.md` — lance **`/bugs-review`** quand tu veux.

## Ce que cette commande ne fait pas

Pas de story, pas d'épic, pas de correctif, pas d'écriture sur le tracker. Elle instruit ; l'humain décide.
