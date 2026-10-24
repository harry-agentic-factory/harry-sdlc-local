# Idées de harnais — cadrées, non implémentées

> Ce fichier porte des idées **décidées utiles mais explicitement non codées**, avec ce qui les motive et ce
> qui reste à trancher. Une idée sans sa motivation mesurée redevient une opinion quelques semaines plus tard.
> Convention : une idée reste ici tant qu'elle n'est pas devenue une story ; elle part alors avec un pointeur.

---

## IDEA-1 — L'amélioration continue du harnais ne doit pas dépendre de la chance

**Origine** : Anis, 2026-10-24 — *« je voudrais un mécanisme pour que chaque session qui a de la valeur
ajoutée dans le brain, le CLAUDE.md du projet, le prompt de l'agent ou le skill le fasse, et qu'on puisse
traiter ces propositions »*. Explicitement : **on ne code pas maintenant.**

### Le problème, mesuré le jour même

Cette session a produit **six** améliorations de harnais :

| cible | ce qui a été ajouté |
|---|---|
| skill `recette` | deux oracles exhaustifs (liste paginée ; double écriture) |
| agent `reviewer` | trois points de contrôle (compensation, donnée jetée derrière un log, compteur et contenu de sources différentes) |
| skill `loop-engineering` | deux invariants (`deployed` sans recette = dette invisible ; le board peut mentir) |
| CLI `sdlc` | `set-status --force-reason` |
| CLI `tracker` | `tracker create` |
| les 8 agents + CLI | le standard de contexte des items `pm` |

**Aucune n'a été déclenchée par un mécanisme.** Toutes sont nées de ce que quelqu'un y pense sur le moment.
Le défaut n'est donc pas l'absence de capitalisation — elle a eu lieu — c'est qu'elle **dépend de la chance**.
Une session pressée, ou dont la dernière heure part en incident, n'en produira aucune, et rien ne le signalera.

Symétriquement : il existe déjà `pm add --kind brain` et `pm to-brain`, donc le **constat** a un canal. Ce qui
manque est le canal de la **proposition de modification du harnais lui-même** — un diff proposé, pas une note.

### Ce qui reste à trancher — et ce sont ces questions qui font l'idée, pas le code

1. **Déclencheur** : à la clôture (`/post-mortem`), ou en continu comme `pm add` ? Le continu capte l'instant
   où on comprend ; la clôture oblige à relire la session. Probablement les deux, avec un **rappel** à la
   clôture listant ce qui a été proposé en route.
2. **Granularité** : une note (« le skill X devrait dire Y ») ou un **diff applicable** ? Un diff coûte plus
   cher à produire et se périme, mais une note se re-discute entièrement. Piste : la note est obligatoire,
   le diff optionnel.
3. **Où ça atterrit** : le harnais est un **repo distinct** du dépôt data. Une proposition issue d'une session
   HIA doit traverser cette frontière. Un fichier dans le dépôt data, relevé périodiquement ? Une PR
   directement sur le harnais ? Attention — le harnais actif est un **worktree**
   (`~/.local/share/harry-sdlc/current`), éditer ailleurs est inerte.
4. **Qui tranche** : `harry-archi` dans son périmètre, l'humain au-delà ? Une modification de skill change le
   comportement de **toutes** les sessions futures : c'est plus engageant qu'une story.
5. **Le garde-fou qui manque le plus** : comment éviter qu'une amélioration proposée depuis **un seul
   incident** devienne une règle générale. C'est exactement l'erreur commise dix fois ce jour-là —
   généraliser depuis une mesure étroite. Une proposition devrait porter **combien de fois** le cas a été
   rencontré, et une règle tirée d'une occurrence unique devrait être marquée comme telle.

### Ce que ça ne doit pas devenir

Un canal qui produit des règles plus vite qu'on ne les relit. Les skills sont déjà longs ; une règle de plus
y est **gratuite à écrire et coûteuse à lire**. Donc le mécanisme doit aussi pouvoir **retirer** : une
proposition de suppression vaut une proposition d'ajout.

---

## IDEA-2 — Un récap d'avancement disponible à tout moment, pas seulement à la fin

**Origine** : Anis, 2026-10-24 — *« je viens souvent sur les sessions longues te demander où en es-tu et je te
pose des questions sur tes avancements ; j'ai besoin d'avoir un récap à tout moment sur l'avancement d'une
session longue et les points de blocage »*. Explicitement : **on ne code pas maintenant.**

### Le problème, mesuré le jour même

Dans cette seule session, il a posé la question sous cinq formes : *« tu en es où ? »*, *« c'est quoi ton
programme de la nuit ? »*, *« tu étais bloqué depuis tout à l'heure ? »*, *« on a livré toutes les stories
fonctionnelles ? »*, *« la 9 c'est quoi déjà ? »*.

Et deux fois, ma réponse a été **fausse**, pas imprécise :

- *« tu étais bloqué ? »* — **oui**, 47 minutes, parce que j'avais lancé une enquête en **avant-plan**. Rien
  ne le signalait, ni à lui ni à moi.
- *« on a livré toutes les stories ? »* — j'ai répondu depuis le board, qui affichait `implemented` sur du code
  **déjà en production**. J'ai relayé un retard **fictif** comme un fait.

Donc le besoin n'est pas cosmétique : **l'état d'une session longue n'est pas interrogeable de façon fiable**,
y compris par moi.

### Ce qui existe déjà et ne suffit pas

`sdlc status <EPIC>` donne l'état des **stories**, pas celui de la **session** : ni les agents en vol, ni ce
qui attend une gate humaine, ni ce qui est bloqué et par quoi. Et il peut mentir, puisque rien ne le notifie
quand un fait survient (c'est l'invariant ajouté à `loop-engineering` le même jour).

### Ce qui devrait y figurer — par ordre de ce qui a réellement manqué

1. **Ce qui tourne**, et depuis quand. Un agent lancé il y a 47 min doit être visible **en tant que tel**.
2. **Ce qui est bloqué, et par quoi** — distinguer trois choses que je confonds dans mes réponses : une
   **gate humaine** (attendu, sain), une **attente technique** (un build, un CD), et un **vrai blocage**
   (quelque chose a échoué et rien n'avance).
3. **Ce qui attend une décision de lui**, nommément. C'était dispersé dans des paragraphes toute la journée.
4. **Ce qui a été livré et prouvé**, avec le chiffre — pas « déployé » mais « déployé et recetté, 18/18 ».
5. **Ce que j'ai dit de faux et corrigé.** Dix fois ce jour-là. Sans trace, il ne peut pas savoir lesquelles
   de mes affirmations antérieures tiennent encore.

### Ce qui reste à trancher

1. **Dérivé ou tenu à jour ?** Un fichier que j'écris se périme comme tout document (vécu trois fois le même
   jour). Dérivé de l'état réel — agents en vol, statuts SDLC, derniers builds — il est juste mais plus
   coûteux. Un hybride : dérivé pour les faits, tenu pour les intentions.
2. **Qui le lit ?** S'il est pour lui, il doit tenir en dix lignes. S'il sert aussi à **me** réhydrater après
   compaction, il doit être exhaustif. Ce ne sont pas le même document.
3. **Et le piège central** : un récap que j'écris moi-même hérite de mes erreurs. Les deux réponses fausses
   ci-dessus auraient été **écrites telles quelles** dans un récap tenu à la main. Donc la partie qui compte
   — « suis-je bloqué ? » — doit être **mesurée**, pas déclarée.
