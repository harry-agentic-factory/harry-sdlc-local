---
name: access-browser
description: Observer une application dans un vrai navigateur (Playwright MCP) pour une enquête — voir ce que l'utilisateur voit, lire une console, inspecter les requêtes réseau, consulter une console tierce déjà authentifiée. Paramétré par le manifest SDLC (`sdlc config` → `infra.ui`). À charger quand le symptôme est visuel, dépend d'une session, ou vit dans un outil externe sans API disponible.
---

# Observer dans un navigateur (paramétré par le manifest)

```bash
sdlc --project <PREFIX> config | jq .infra.ui
```

Tu y trouves `profile` (le profil qui porte les sessions), `apps` (nom → URL) et les `_gotcha`.

## Quand l'utiliser — et quand s'en passer

L'IHM est le dernier recours, pas le premier réflexe : elle est lente, fragile et bavarde en
contexte. Préfère une API ou un journal quand ils répondent à la même question.

Elle est **irremplaçable** dans trois cas :
- le symptôme est **visuel** (un libellé, un état affiché, un curseur, un écran de login) ;
- l'information vit dans une **console tierce sans API accessible** (facturation, fournisseur d'envoi) ;
- il faut **reproduire le parcours réel** d'un utilisateur, service worker et cache compris.

## Règle — lecture seule, et jamais d'identifiants

Tu navigues, tu observes, tu captures. **Tu ne remplis aucun champ d'identifiant, tu ne cliques sur
aucun bouton qui écrit** (créer, supprimer, envoyer, retirer d'une liste). Si une page demande une
authentification que le profil n'a pas, **c'est une `limitation`**, pas une invitation à se
connecter : l'humain se connecte lui-même dans la fenêtre, tu reprends après.

## Méthode

1. `browser_navigate` vers l'URL du manifest.
2. `browser_snapshot` — l'arbre d'accessibilité, pas une capture d'image : c'est lisible, diffable,
   et ça donne les `ref` pour interagir.
3. Pour une recherche ou un filtre, **cible par sélecteur CSS stable** plutôt que par libellé :
   ```js
   // repérer les champs réels avant de taper
   [...document.querySelectorAll('input')].map(el => ({type: el.type, name: el.name, placeholder: el.placeholder}))
   ```
4. **Extrais le résultat par `browser_evaluate`**, pas en relisant un snapshot entier : tu ramènes
   trois lignes au lieu de trois cents.
   ```js
   () => JSON.stringify({ titre: document.querySelector('h2')?.innerText,
     lignes: [...document.querySelectorAll('table tbody tr')].map(tr => tr.innerText) })
   ```
5. `browser_console_messages` et `browser_network_requests` quand le symptôme est technique.

## ⚠️ Un résultat vide n'est pas un fait

C'est **le** piège de l'observation via IHM. Une recherche peut être en **préfixe**, sensible à la
casse, ou porter sur un autre champ que celui que tu crois.

> **Avant d'écrire « 0 résultat », refais la même recherche sur un cas dont tu SAIS qu'il existe.**

Sans ce test de contrôle, tu confonds *absence de fait* et *outil mal utilisé* — et tu conclus avec
aplomb à l'inverse de la réalité.

## Le profil et son verrou

Le profil du manifest porte les sessions : c'est ce qui permet d'arriver déjà authentifié.

Un seul navigateur peut le tenir à la fois. Sur `Browser is already in use`, **ne bascule pas en
profil isolé** (tu perdrais les sessions) : cherche d'abord une instance **orpheline** laissée par
une session morte.

```bash
ps aux | grep '[p]laywright' | grep -o 'user-data-dir=[^ ]*'
```

Une instance lancée par automatisation porte `--remote-debugging-pipe`. Si elle est orpheline, sa
fermeture est une décision qui appartient à l'humain — c'est peut-être sa fenêtre.

## Ce que tu rends

Des faits observables, avec l'URL et la date : *« sur `<url>`, la ligne X affiche Y »*. Une capture
d'écran seulement si le visuel est le sujet — sinon le texte extrait suffit et coûte mille fois moins.
