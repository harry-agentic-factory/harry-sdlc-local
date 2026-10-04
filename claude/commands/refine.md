Découpe un épic (PRD) en stories + tasks avec leurs dépendances : $ARGUMENTS

Tu es Harry. **Profil : bascule en `PO`** — adopte ce profil pour la suite de la session (in-session, pas de fichier), sans l'annoncer (« Écrire pour un humain »).
Prends le PRD `sample-proj-sdlc-local/<EPIC>/prd.md`.

> Exécution autonome ensuite (« en mode loop » / « en auto ») → skill `loop-engineering` (couplage loop ↔
> state-machine). Stratégie de branches → `docs/branching-strategies.md` (trunk d'épic préféré si multi-stories).

## Déroulé
1. **Découpe** l'épic en **stories** (1 task par story). Simple = 1 story.
2. **Dépendances** : établis le **DAG** (qui dépend de qui) — sans cycle. Propose l'ordre
   d'exécution et ce qui peut aller en parallèle.
3. **Repos touchés** par story (cross-repo : app-repo, plugin, api-repo, ops-repo, web-repo…).
4. **Écris** `sample-proj-sdlc-local/<EPIC>/refine.md` au **format FIXE** ci-dessous et **crée** chaque
   ticket :
   `python3 -m sdlc.cli --project SAMPLE create-ticket <EPIC> <STORY> "<titre>" --deps a,b --repos x,y`
5. **Vérifie** le DAG : `python3 -m sdlc.cli --project SAMPLE next <EPIC>` doit renvoyer les stories
   sans dépendances d'abord.
6. **Stratégie de branches** (cf. `docs/branching-strategies.md`) : note-la dans `refine.md` (section « Protocole de
   branches »). Pour un **épic multi-stories dépendantes → trunk d'épic (stratégie C, préférée)** : crée le trunk
   `epic/<EPIC>` off `main` **par repo touché** (`git -C <repo> branch epic/<EPIC> origin/main && git push -u origin epic/<EPIC>`) ;
   les stories branchent off le trunk et y sont mergées ; promote `main` unique en fin d'épic (gate humaine).

## Format FIXE de `refine.md`
Règle « Format des livrables » de la persona : un seul titre `#`, puis exactement ces sections `##`, dans cet ordre,
sans suffixe. La section `## Stories` **commence** par le tableau, puis un `###` par story, au format exact
`### <STORY> — <titre> · deps: <a, b ou —> · repos: <x, y>` (identifiant du ticket créé, ex. `US-1` ; « — » sans
dépendance) :

```markdown
# <EPIC> — refine

## Stories

| Story | Titre | Deps | Repos |
|---|---|---|---|
| US-1 | <titre> | — | <dépôt> |
| US-2 | <titre> | US-1 | <dépôt>, <dépôt> |

### US-1 — <titre> · deps: — · repos: <dépôt>
<ce que la story livre, sa task>

### US-2 — <titre> · deps: US-1 · repos: <dépôt>, <dépôt>
<ce que la story livre, sa task>

## Ordre suggéré
<l'ordre d'exécution selon le DAG, ce qui peut aller en parallèle>

## Protocole de branches
<la stratégie retenue et les trunks créés>

## Sources
<PRD, Brain, code>
```

N'écris pas « Les stories », « Détail des stories » ni « Découpage » : écris `## Stories`. N'écris pas « DAG »,
« DAG et ordre suggéré » ni « Ordre d'exécution » : écris `## Ordre suggéré`. N'écris pas « Stratégie de branches » ni
« Protocole de branches (stratégie C) » : écris `## Protocole de branches`. Rien d'autre au niveau `##` : « Questions
ouvertes », « Prochain actionnable », « Suite », « Registre SDLC » sont des `###` sous Stories ou Ordre suggéré. Un
refine existant écrit autrement : à sa réécriture, ses sections sont renommées vers ces noms et leur contenu y est
rangé, sans rien perdre.

> **Avant d'écrire un document vivant** du dépôt data : règle « Écrire un document vivant » de la persona (`~/.claude/sdlc/harry.md`).

## Sortie
Dis à l'humain (règle « Écrire pour un humain » de la persona) : le découpage en stories (le tableau stories × dépendances × dépôts reste utile, en titres
lisibles) et la prochaine story à spécifier. Board optionnel (Trello/Planner)
= miroir une-voie, seulement si configuré. Enchaîne ensuite sur `/spec-func` (ou `/spec-tech` si trivial).
