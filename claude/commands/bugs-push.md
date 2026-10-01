Reflète l'avancement SDLC sur le tracker, et relis les retours du rapporteur : $ARGUMENTS

Tu es le **Scrum Master** du flux bugs, le seul à écrire sur le tracker. **Aucune écriture sans l'accord
explicite de l'humain**, et jamais de suppression (au pire : archiver).

`$ARGUMENTS` (optionnel) : des cartes pour se limiter à elles. Préfixe : `sdlc projects`.

## 0. Quand

**C'est la dernière étape d'un épic de bugs**, après la promotion : code mergé sur `main`, redéployé depuis `main`,
TNR verte, stories en `done`. Le tracker n'envoie une carte en « à valider » qu'à `done` ; avant, elle reste
« en cours ». Si l'humain lance `/bugs-push` plus tôt, rappelle-le-lui et ne déplace rien vers « à valider ».

## 1. Calcule, sans écrire

- `tracker --project <PREFIX> pull --nature bug` (état frais du board).
- `tracker --project <PREFIX> push` → `moves` (déplacements impliqués par les statuts SDLC, toujours **vers
  l'avant** : une carte suit sa story **la moins avancée**) et `signals`.

## 2. Traite les signaux — ce sont des retours humains, pas des erreurs

| Signal | Sens | Proposition |
|---|---|---|
| `reporter-accepted` | le rapporteur a mis la carte en validée alors que la story est `recette_ok` | `sdlc set-status <STORY> accepted` + journal « accepté par le rapporteur sur le tracker » — **sur accord humain** |
| `sent-back-by-human` | on l'avait avancée, un humain l'a remise en arrière | lis ses derniers commentaires (`tracker card <ref>`) : re-test KO ? → propose `/investigate <ref>` ou un retour en fix (`sdlc reject`). Si c'était un **recul volontaire** de notre part (poussée trop tôt), `tracker forget-push <ref…>` puis re-calcule. |
| `card-ahead-of-story` | la carte est plus loin que la story | demande à l'humain : carte déplacée à la main par erreur, ou story à faire avancer ? |
| `unknown-story` | une story liée est introuvable dans la SDLC | montre-la ; ne corrige rien seul |

## 3. Écris, sur accord

Montre le tableau des déplacements (carte, de → vers, stories et statuts) et le commentaire qui sera posté
(« Suivi SDLC : <STORY> (<statut>) → <liste> »). Sur un OK explicite, total ou partiel :
`tracker --project <PREFIX> push --apply --comment [--only <carte> …]`.
## Sortie

Déplacements faits, signaux traités (et ce qui attend l'humain), cartes restées en place et pourquoi.
