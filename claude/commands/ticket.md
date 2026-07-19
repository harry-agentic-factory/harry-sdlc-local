Réhydrate le contexte d'un ticket SDLC : $ARGUMENTS

Appelle `python3 -m sdlc.cli --project SAMPLE get $ARGUMENTS` (depuis `sample-proj-sdlc-local/tooling` ou PYTHONPATH
dessus) et présente : statut, prochaine étape, repos, branche, MR, et la **carte des artefacts**
(`prd`, `spec-func`, `spec-tech`, `review`, `deploy`, `acceptance`, `demo`). Ouvre/annonce les `.md`
pertinents. Si l'argument est un épic, utilise `next <EPIC>` pour montrer le prochain actionnable.

But : donner en **un appel** tout ce qu'il faut pour reprendre le travail, sans re-fournir le contexte.
