Enquête sur un signalement jusqu'à établir sa cause : $ARGUMENTS

`$ARGUMENTS` accepte indifféremment :
- une **URL de carte** du tracker (ex. `https://trello.com/c/aB3dEf/12-le-titre`),
- un **identifiant court** de carte (`aB3dEf`),
- un **identifiant de story** SDLC (`HIA-BUG-20260924-USERFORM-1`).

## 1. Résous l'entrée — ne devine jamais le tracker

Le tracker (Trello, …) n'est connu que du CLI **`tracker`** : la SDLC n'en sait rien. Sa config vit
dans `<workspace>/_tracker/config.json` (`tracker --project <PREFIX> dir`) ; absente →
`tracker --project <PREFIX> init`. **Rien n'est en dur ici** : un autre projet a un autre tracker, voire aucun.

- **Identifiant de story** (il matche le préfixe du projet) → `sdlc get <STORY>` pour le titre, les
  repos, le statut et les artefacts déjà produits ; `tracker --project <PREFIX> show --story <STORY>`
  pour la ou les cartes d'origine.
- **URL, identifiant court ou id de carte** → `tracker --project <PREFIX> card <ref>` : nom, liste,
  labels, description, commentaires, pièces jointes. Les credentials restent dans le CLI : jamais de
  `cat`/`Read` sur leur fichier, jamais d'URL contenant la clé en sortie.

## 2. ⚠️ Extrais le SYMPTÔME, pas l'analyse

Une carte contient souvent **déjà** une analyse — cause supposée, correctif envisagé, références de
code. **Tu dois la retirer avant de la passer à l'agent.**

Sinon l'agent la recopie et te la rend comme sa conclusion : tu crois avoir une enquête, tu n'as qu'un
écho. C'est arrivé lors du run de référence, et ça invalide tout le résultat.

Garde : **ce qui a été observé** — qui, quand, sur quel écran ou quel appel, ce qui était attendu, ce
qui s'est produit, les identifiants réels (compte, tenant, horodatage). Retire : « la cause est… »,
« il faudrait corriger… », les numéros de ligne, les hypothèses.

En cas de doute, **annonce** en une ligne ce que tu as retenu comme symptôme. Si la carte ne contient
qu'une analyse et aucun fait observable, dis-le : il faut retourner voir le rapporteur.

## 3. Lance l'investigateur

Convoque l'agent **`investigator`** avec ce symptôme épuré, le préfixe du projet, et les identifiants
réels qui figurent dans le signalement. Il résout ses propres accès depuis le manifest ; ne lui
énumère pas les commandes, il a ses skills.

## 4. Classe le résultat

> **Avant d'écrire un document vivant** du dépôt data : règle « Écrire un document vivant » de la persona (`~/.claude/sdlc/harry.md`).

- Écris `analysis.md` à côté de la story quand il y en a une, et attache-le :
  `sdlc link <STORY> spec_func <chemin>`.
- Consigne une ligne de journal : `sdlc journal <STORY> --entry "<ce qui a été établi, sans secret>"`.
- **Pas de story, mais une carte ?** Écris le dossier dans `<tracker dir>/cards/<shortLink>/fiche.md`
  et enregistre-le : `tracker --project <PREFIX> instructed <ref> --fiche cards/<shortLink>/fiche.md`.
  La carte passe `instructed` et entrera dans la prochaine `/bugs-review`. Ne crée aucune story d'office.

## 5. Restitue en dix lignes, pas en trois pages

| | |
|---|---|
| **Constat** | les faits, avec leur niveau de preuve |
| **Cause** | ou `non établie` — c'est une réponse valable |
| **Reproduit** | oui / non / impossible, avec le protocole |
| **Contournement** | comment débloquer l'humain **maintenant**, s'il y en a un |
| **Ce qui manque** | les accès ou mesures qui trancheraient |

Le dossier complet reste dans le fichier. Ce que tu affiches doit tenir à l'écran.

## Ce que cette commande ne fait pas

Elle **n'écrit pas de correctif** et **ne déplace pas la carte**. Elle instruit, elle ne décide pas :
c'est l'humain qui tranche à la lecture du dossier.
