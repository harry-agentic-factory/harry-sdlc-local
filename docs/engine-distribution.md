# Comment une version du moteur atteint les sessions

> Écrit parce qu'une session a cru à un écart qui n'existait pas, et a bâti un plan dessus. Les faits ci-dessous
> ont été **mesurés** le 2026-11-02 ; chacun porte de quoi le rejouer.

Le moteur est consommé de **deux** façons, et c'est ce qui rend la question moins évidente qu'elle n'en a l'air :
sa **bibliothèque** Python, et ses **prompts** (`claude/commands`, `claude/agents`, `claude/skills`,
`claude/sdlc/harry.md`). Un dossier de prompts n'a pas de version : c'est le déploiement qui la déclare.

## Sessions locales — `install.sh`

```
install.sh vX.Y.Z        # clone détaché du tag sous $HARRY_SDLC_HOME/vX.Y.Z, puis bascule `current`
install.sh --dev <path>   # une copie de travail devient la version active
```

- Le tag doit **exister sur le dépôt distant**, et `VERSION` du clone doit valoir `X.Y.Z` — sinon l'installation
  est refusée.
- La bascule est un **renommage atomique** de `current` ; les liens de `~/.claude/{commands,agents,skills,workflows}`
  et `~/.claude/sdlc/harry.md` pointent littéralement `$HARRY_SDLC_HOME/current/...` et ne changent **jamais**
  après. Basculer ou revenir en arrière = bouger `current`.
- `bin/sdlc` n'installe **rien** : c'est un lanceur bash qui résout sa propre cible, injecte
  `PYTHONPATH="$ENG/tooling"` et exécute `python3 -m sdlc.cli`. Conséquence pratique : **il n'y a pas de paquet
  `sdlc` importable** en local. Un outil destiné aux skills est donc une **sous-commande du CLI**, jamais un
  script posé dans `claude/scripts/` — ce dossier n'est pas lié dans `$CLAUDE_HOME`, et un script n'y pourrait pas
  importer le module.
- Tant que `current` pointe un `--dev`, la session tourne avec ce worktree, quelle que soit la version du dépôt.
  `sdlc --version` le dit (`0.8.0-dev+<sha> (dev: <chemin>)`). **Vérifier cette ligne avant de conclure quoi que
  ce soit sur le comportement d'une commande.**

## Sessions de la plateforme — lock, image, déploiement

La plateforme épingle la bibliothèque sur un **tag** (`pyproject.toml`, `uv.lock`) et sert les prompts depuis un
dossier de l'hôte dont le déploiement déclare la référence (`HARRY_SDLC_COMMANDS_REF`). Un test de contrat refuse
que les deux divergent.

Les prompts sont **cuits dans l'image** au build : le `Dockerfile` de l'API recopie `claude/` du paquet installé
vers `/opt/harry-sdlc-engine/claude` avec un fichier `.engine-ref`. **Un re-épinglage du lock ne les déplace donc
pas.** La chaîne complète, dans l'ordre :

1. **tag** poussé sur le dépôt public du moteur ;
2. **re-épinglage** `pyproject.toml` + `uv.lock` sur ce tag ;
3. **build de l'image** — l'étape qu'on oublie, et sans laquelle les prompts restent ceux du tag précédent ;
4. **déploiement par tag** : il extrait `claude/` de l'image déployée vers `<parent>/releases/<commit12>`, fait du
   dossier d'hôte un lien vers celui-là, et **exporte lui-même** `HARRY_SDLC_COMMANDS_REF` depuis le commit des
   prompts extraits. Aucun geste manuel sur les fichiers d'environnement.

## Le piège à ne pas refaire

Deux consommations, deux versions possibles, et un dossier sans version au milieu : la tentation est de lire un
écart là où il n'y en a pas. Avant d'écrire qu'il y en a un, **mesurer les trois** : le tag du `pyproject.toml`,
le `rev` du `uv.lock` (et le commit qu'il résout), et la référence déclarée pour les prompts. Si les trois
concordent, la plateforme est simplement **une version en retard** sur le dépôt — ce qui est l'état normal entre
deux releases, pas une dérive.
