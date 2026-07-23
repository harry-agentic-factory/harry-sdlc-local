---
name: agent-resilience
description: Discipline de contexte & résilience pour tout agent autonome LONG (recette, deploy, fix, migration…) qui enchaîne beaucoup d'appels d'outils et de gros résultats. Évite les morts sur « Connection closed mid-response » en gardant le contexte maigre, en persistant l'avancement au fil de l'eau, en réutilisant les ressources et en étant resume-safe. À charger au démarrage de toute tâche longue/multi-étapes.
---

# Résilience d'un agent long

Un agent qui accumule beaucoup d'appels d'outils + de **gros résultats** voit son **contexte gonfler** ;
chaque tour ré-embarque tout le contexte → requêtes et réponses volumineuses → **fragilité aux coupures**
de la connexion à l'API du modèle (`Connection closed mid-response`). **Ce n'est pas ta logique, c'est la
taille.** Applique cette discipline **du début à la fin** :

1. **Filtre ce qui entre dans le contexte.** Ne dumpe **jamais** une réponse/log entier. Extrais à la
   source : `jq` pour du JSON, `grep`/`tail` pour des logs, `?tree=…` sur les API qui le supportent. Vise
   des sorties **< ~2 Ko**. N'affiche que ce que tu vas **asserter** ou **décider**.
2. **Persiste au fil de l'eau.** Écris chaque résultat/étape dans **l'artefact de ton étape**
   (`acceptance.md` / `deploy.md` / `implement.md` / …) **dès qu'il est établi**, pas à la fin. Si tu es
   coupé, rien n'est perdu.
3. **Sois resume-safe.** Si tu **reprends** après une coupure : **relis d'abord ton artefact** (ce que tu
   as déjà fait), puis **continue** à l'étape suivante. **Ne recommence jamais de zéro.**
4. **Réutilise les ressources.** Garde vivants token, port-forward, crumb, env local, session — ne les
   recrée pas à chaque itération. Nettoie en **fin** de tâche.
5. **Découpe si ça s'allonge.** Au-delà de ~25-30 appels d'outils (ou plusieurs gros résultats), écris un
   **point d'avancement** (fait / restant) dans ton artefact avant de continuer.
6. **Cible tes re-vérifs.** Rejoue seulement l'**assertion clé** (une commande filtrée), pas tout le
   parcours.
7. **Fichiers temporaires / scripts → dans TON workspace, jamais `/tmp`.** Écris tout script/fichier
   jetable dans le **scratch de ta bulle** (`<workspace>/scratch/`, fourni par `sdlc workspace`) ou, à
   défaut, le dossier du ticket. `/tmp` est **hors de ton périmètre** → **popup de permission** + fichier
   non contenu/non nettoyé. Le scratch, lui, est dans ton périmètre et part avec la bulle.

## Artefacts = journal horodaté, le plus RÉCENT en tête
Ton artefact d'étape (`review.md` / `deploy.md` / `implement.md` / `acceptance.md`) est un **journal**,
pas un fichier écrasable. À chaque run :
- **PREPEND** une section datée en **tête** : `## <ISO 8601> — <résumé 1 ligne>` (newest-first), puis le
  détail. **N'écrase JAMAIS** les entrées précédentes (v1/v2, itérations de fix-loop) — elles descendent.
- Le bloc du **haut** = le run **le plus récent** → un `## Recap` en tête reflète toujours le dernier état,
  et `sdlc status` lit cette tête.
- Même sémantique que `journal.md` (décisions de gate) : historique préservé, lecture immédiate du récent.

> Les skills d'étape (`recette`, `deploy-jenkins`, …) et les agents longs (recetteur, deployer, fixer)
> **chargent ce skill** et n'en dupliquent pas le contenu.

## Consigne la dette/les learnings au fil de l'eau
Dès que tu rencontres une dette, un incident, un learning (process/harness) ou un point sécu, **consigne-le**
sans attendre la fin — un item survit à une coupure et remonte au post-mortem d'épic :
`sdlc --project <PREFIX> pm add --agent <ton-rôle> --kind <debt|learning|incident|security|brain> [--epic E --story S] --text '...'` (**jamais de secret** dans le `text`).
