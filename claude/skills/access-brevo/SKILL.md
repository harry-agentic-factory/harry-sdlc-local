---
name: access-brevo
description: Trancher une question d'e-mail — un message a-t-il été SOUMIS, DÉLIVRÉ, rejeté, bloqué ? Journaux d'événements, liste de suppression, état d'authentification du domaine expéditeur. Paramétré par le manifest SDLC (`sdlc config` → `infra.mail`). À charger dès qu'un symptôme est « untel ne reçoit pas ses mails » — AVANT toute hypothèse sur DNS, SPF ou DMARC.
---

# Trancher une question d'e-mail (fournisseur : Brevo)

Tu **ne devines pas** : tu lis `infra.mail` dans le manifest (`console`, `sender`, `credentials`,
`status`), puis tu vas **regarder les journaux d'envoi**.

## La règle qui justifie ce skill

> **Le journal d'envoi tranche en quatre minutes ce que quarante minutes de raisonnement ne règlent pas.**

Incident réel : trois relevés DNS exacts (SPF sans le relais, `DMARC p=quarantine; pct=90`), trois
inférences empilées par-dessus — « l'authentification échoue » → « donc quarantaine » → « donc c'est la
cause » — présentées d'un bloc comme un diagnostic sourcé. **C'était faux.** Le journal a montré que
la remise vers ce domaine fonctionnait (un message délivré ET ouvert le jour même) et que **rien
n'avait jamais été soumis** pour l'adresse en cause. Le défaut était dans l'application, très en
amont.

**Commence donc toujours par la question la plus bête : le message a-t-il seulement été soumis ?**

## L'ordre des trois lectures

### 1. Journaux d'événements — la preuve

`Transactionnel → Email → Logs`, filtrer par destinataire. Ou en API :
`GET /v3/smtp/statistics/events?email=<adresse>`.

Statuts et ce qu'ils signifient :

| Statut | Lecture |
|---|---|
| **aucune ligne** | le message **n'a jamais été soumis** → le défaut est dans l'application, pas dans la remise |
| `delivered` | le serveur destinataire l'a accepté → le problème est après (boîte, filtre local, utilisateur) |
| `soft_bounce` | refus temporaire (boîte pleine, indisponible) |
| `hard_bounce` | refus définitif — inscrit souvent l'adresse en liste de suppression |
| `blocked` | le fournisseur a refusé d'envoyer (liste de suppression, réputation) |
| `opened` / `clicked` | preuve formelle que ça arrive |

⚠️ **La recherche par destinataire est un PRÉFIXE, pas une sous-chaîne.** Chercher `exemple.com` ne
trouvera rien. **Fais toujours un test de contrôle sur une adresse dont tu sais qu'elle a reçu, AVANT
de conclure à zéro** — sinon tu confonds *absence de fait* et *outil mal utilisé*.

### 2. Liste de suppression — l'explication du « une fois, puis plus rien »

`Contacts → Blocklist`, ou `GET /v3/smtp/blockedContacts`.

Une adresse inscrite après un rebond dur fait que le fournisseur **accepte puis jette en silence** :
aucun rebond, aucune erreur, rien côté application. C'est la signature de « je l'ai reçu une fois, et
puis plus jamais ».

L'en retirer est une **écriture** : jamais sans décision humaine explicite, et jamais sans avoir
compris quel rebond l'y a mise — sinon elle y retournera.

### 3. Authentification du domaine — seulement si 1 et 2 n'ont pas tranché

`Settings → Expéditeurs` : l'expéditeur est-il **vérifié**, la signature **DKIM** porte-t-elle le
domaine, **DMARC** est-il configuré ?

**Cette page vaut mieux qu'une lecture de zone DNS.** Elle dit l'état réel tel que le fournisseur le
voit. Et souviens-toi que DMARC passe si **SPF aligné OU DKIM aligné** : un SPF qui n'autorise pas le
relais ne prouve rien tant que DKIM signe sur le domaine.

## Accès

Selon `infra.mail.credentials` / `status` :

- **clé API** (préférée, et seule utilisable sans humain) :
  ```bash
  F=<chemin du manifest>
  K=$(jq -r .apikey "$F")
  curl -s -H "api-key: $K" "https://api.brevo.com/v3/smtp/blockedContacts" | jq .
  ```
  Lis la clé **dans la commande**, jamais avec `cat`/`Read`, et n'affiche jamais une URL qui la contient.
- **session navigateur** (dépannage) : via la console, avec le profil déclaré dans `infra.ui`. Fragile
  (la session expire) et inutilisable en exécution planifiée.
- **`status: missing`** → tu ne tentes rien : tu consignes une `limitation` disant ce que l'accès
  aurait tranché.

## Ce que tu rends

Des faits, avec leur fenêtre d'observation : *« sur la période X→Y, N messages pour cette adresse,
statuts : … »*. Et si c'est zéro, dis-le comme un fait mesuré — en précisant que le test de contrôle
a bien renvoyé des lignes sur une adresse connue.
