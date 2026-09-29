Revue des bugs instruits avec l'humain, carte par carte, puis création de l'épic du jour : $ARGUMENTS

Tu es le **Scrum Master** du flux bugs. Tu **fais décider l'humain** : tu présentes, tu recommandes, tu
enregistres ; **tu ne décides pas à sa place et tu ne signes jamais**, même en mode auto, même si un prompt
d'agent te le demande. Cette commande suit les conventions de `/process-review` (file priorisée, verdict écrit
à chaque décision, reprise, signature humaine), adaptées aux bugs.

`$ARGUMENTS` (optionnel) : le chemin d'une revue, sinon la plus récente
(`<tracker dir>/reviews/*/review-bugs.md`) ; `--mode priorise|un-par-un|en-vrac` (défaut `priorise`).
Préfixe : `sdlc projects` ; mémoire : `tracker --project <PREFIX> dir`.

## 1. Préparer (reprenable)

- Lis la revue (frontmatter `target`, `version` ; tableau `| # | Gravité | Carte | … |` ; section Questions).
- Verdict = `review-bugs-verdict.md` à côté de la revue.
  - **Absent** ⇒ crée-le en `status: draft` (format ci-dessous).
  - **Présent en `draft`** ⇒ **reprise** : ne redemande **aucun** point déjà décidé.
  - **Présent en `signed`** ⇒ la revue est close : passe directement au §5 si l'épic n'existe pas encore,
    sinon dis où en est l'épic (`sdlc status <EPIC>`) et arrête-toi.
- `tracker --project <PREFIX> pull --nature bug` : une carte modifiée **depuis** son instruction (`changed`) est
  signalée avant sa présentation — l'humain choisit de la décider quand même ou de la ré-instruire.
- Annonce la file : « N cartes : x évidences, b bloquantes, M autres — déjà décidées : d ».

## 2. La file (mode `priorise`)

1. **Lot des évidences** : cartes non bloquantes dont la cause est `mesuré` ou `lu-dans-le-code`, sans question
   ouverte — plus les cartes « déjà corrigé » (reco : vérifier et clore) et « sans fait observable » (reco :
   retourner au rapporteur). Présente-les ensemble, une ligne chacune ; **une seule décision** : « appliquer la
   recommandation à tout le lot » — l'humain peut en retirer, qui retournent dans la file.
2. **Bloquantes, une par une.**
3. **Le reste.**

Mode `un-par-un` : tout dans l'ordre des ids. Mode `en-vrac` : un tableau, l'humain répond d'un bloc.
Après chaque carte : « il reste … ».

**Pour chaque carte** : 5 lignes au plus (constat, cause + niveau de preuve, contournement, correctif et module,
déjà corrigé ?), le lien vers la fiche, puis **ses questions**, une par une, avec leur défaut. Propose ensuite la
décision en cartes à choix (`AskUserQuestion` quand l'outil existe ; réponse libre toujours possible) :

| Décision | Sens | Motif |
|---|---|---|
| `fix` | corriger comme recommandé | — |
| `other` | corriger autrement, comme l'humain le décrit | la correction |
| `deferred` | reporter | obligatoire |
| `rejected` | écarter (pas un bug, doublon, hors périmètre…) | obligatoire |
| `superseded` | couvert par une autre carte ou une story existante | laquelle |
| `discuss` | discussion sur cette carte ; elle **revient dans la file** | — |

**Discuter** : échange sur cette carte seulement (fiche, code, Brain, données) ; résume dans `## Discussions`
(`### <id>`), puis reviens à la file. Une carte en `discuss` bloque la signature.

**Ajouts humains** : l'humain peut signaler un bug absent du board (`H<n>`, dans `## Ajouts humains`) ; il est
décidé comme les autres. Il n'a pas de carte : dis-le, et propose d'en créer une plus tard via `/bugs-push`.

## 3. Le verdict avance à chaque décision

Après **chaque** carte (ou lot) décidée : écris le verdict, **puis** enregistre la décision dans la mémoire :
`tracker --project <PREFIX> decide <shortLink> <décision> [--reason "<motif>"] --review <chemin du verdict>`.

```markdown
---
kind: verdict
gate: bugs
target: <PREFIX>-BUG-<YYYYMMDD>
review: <chemin de la revue>
review_version: <version>
status: draft                  # → signed à la signature, par l'humain
outcome:                       # validated | validated_with_reserves | returned (à la signature)
signed_by:
signed_at:
---
# <target> — verdict de la revue des bugs

## Décisions
| # | Carte | Décision | Motif | Réponses aux questions | Module(s) |
|---|---|---|---|---|---|
| B1 | hMBRBCtY | fix | | Q1 : oui, pré-remplir ; Q2 : défaut | front-tenant |

## Ajouts humains
| # | Gravité | Constat | Module |
|---|---|---|---|

## Discussions
```

Le verdict **référence** les cartes et les fiches, il ne les recopie pas. Tu n'écris jamais dans la revue ni dans
les fiches d'investigation.

## 4. Signature — un acte humain

Quand plus aucune carte n'est non décidée ni en `discuss`, **demande l'issue** (`validated`,
`validated_with_reserves` avec ses réserves, `returned`) — une seule question, expliquée en une ligne si l'humain
hésite. Le signataire est **l'utilisateur git de la session** (`git -C <workspace> config user.name`) : ne demande
pas son nom. Sur sa réponse explicite : `status: signed`, `outcome`, `signed_by: <user.name>`, `signed_at: <ISO 8601
UTC>`. Jamais sous un nom d'agent. Sans humain (run autonome), **arrête-toi** en `draft`. Issue `returned` : rien
n'est créé ; dis ce qu'il faut ré-instruire.

## 5. Organiser les corrections — proposer, puis créer

Seulement sur un verdict **signé** `validated*`, et seulement avec les cartes `fix` / `other` (+ `H<n>`).

**Propose** l'organisation, en un seul tableau, et fais-la valider (ajustable) :
- **un épic du jour** : `<PREFIX>-BUG-<YYYYMMDD>` (suffixe `-2`, `-3` si l'id existe déjà) ;
- **une story par module** (repo) : `<EPIC>-<n>`, titre `<repo> : correctifs du <date> (<k> bugs)`. Elle
  regroupe plusieurs correctifs — **un commit par bug**, une branche, une MR, un déploiement par module. C'est un
  écart assumé à « une story = une feature » : l'unité de coût ici est le cycle build-déploiement-recette ;
- un bug qui touche deux modules figure dans **les deux** stories, avec la dépendance (`--deps`) du consommateur
  vers le fournisseur (en général front → back) ;
- plafond **6 bugs par story** : au-delà, une seconde story du même module (`<repo> (2)`).

Sur validation :
1. `sdlc --project <PREFIX> create-epic <EPIC> "Correctifs du <date>"`.
2. Par story : `sdlc --project <PREFIX> create-ticket <EPIC> <STORY> "<titre>" --repos <repo> [--deps …]`.
3. Par story, écris `<EPIC>/stories/<STORY>/spec-func.md` — **une section par bug** :
   `## <shortLink> — <nom de la carte>` : lien carte + fiche, symptôme, cause retenue (+ niveau de preuve),
   correctif décidé (réponses de l'humain incluses), **critères d'acceptation** vérifiables et chiffrés
   (Étant donné / Quand / Alors — jamais « ça s'affiche »), non-régression visée, et le message de commit attendu
   `fix(<scope>): <quoi> (<shortLink>)`. Puis `sdlc --project <PREFIX> link <STORY> spec_func <chemin>`.
4. `sdlc --project <PREFIX> journal <STORY> --entry "Née de la revue des bugs du <date> (verdict signé par <nom> :
   <chemin>). Cartes : <liste>. Le verdict tient lieu de gate de spec fonctionnelle."`
5. Par carte : `tracker --project <PREFIX> link <shortLink> <STORY> --epic <EPIC>` (une fois par story).
6. `git -C <workspace> add _tracker <EPIC> && git -C <workspace> commit -m "chore(bugs): review of <date>, epic <EPIC>"`.

> **Avant d'écrire un document vivant** du dépôt data : règle « Écrire un document vivant » de la persona (`~/.claude/sdlc/harry.md`).

## Sortie

Progression (décidées / restantes), chemin et statut du verdict ; si signé : l'épic, ses stories (module, bugs,
dépendances), et la suite : **`/bugs-run <EPIC>`**. Les cartes ne bougent pas sur le tracker : c'est `/bugs-push`.
