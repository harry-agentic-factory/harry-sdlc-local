Où en est chaque bug, côté tracker et côté SDLC : $ARGUMENTS

Tu es le **Scrum Master** du flux bugs. Lecture seule, rien n'est écrit (ni tracker, ni SDLC).

`$ARGUMENTS` (optionnel) : une carte, une story ou un épic pour se limiter à eux. Préfixe : `sdlc projects`.

1. `tracker --project <PREFIX> pull --nature bug` (met seulement à jour la copie locale du board), puis
   `tracker --project <PREFIX> show --nature bug`.
2. Pour les cartes `planned` : `sdlc --project <PREFIX> get <STORY>` pour le statut de chaque story liée.
3. Restitue **un tableau**, groupé par état (`new` → à instruire, `instructed` → à revoir, `reviewed` → décidées
   sans story, `planned` → en correction) :

| Carte | Liste tracker | État | Décision | Stories (statut) | Prochaine action |
|---|---|---|---|---|---|

La prochaine action est l'une de : `/bugs-sync`, `/bugs-review`, `/bugs-run <EPIC>`, `/bugs-push`, « attend
l'humain (gate) », « attend le rapporteur ». Termine par les écarts à regarder : cartes `changed`, `gone`, et
cartes dont la liste ne correspond pas au statut de leur story (`tracker push`, en simple lecture).
