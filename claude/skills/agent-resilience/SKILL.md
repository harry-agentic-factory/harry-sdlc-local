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

> Les skills d'étape (`recette`, `deploy-jenkins`, …) et les agents longs (recetteur, deployer, fixer)
> **chargent ce skill** et n'en dupliquent pas le contenu.
