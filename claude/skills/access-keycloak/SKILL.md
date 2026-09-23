---
name: access-keycloak
description: Observer un Keycloak en LECTURE SEULE pour une enquête — realms, clients, utilisateurs, rôles, flows d'authentification, thèmes servis. Paramétré par le manifest SDLC (`sdlc config` → `infra.identity`). Les identifiants d'admin ne sortent JAMAIS du pod. À charger dès qu'une question porte sur l'authentification, les droits, un compte, ou l'écran de login.
---

# Observer Keycloak (paramétré par le manifest)

```bash
sdlc --project <PREFIX> config | jq .infra.identity
```

Tu y trouves `namespace`, `deployment`, `method` et les particularités du projet.

## Règle absolue — les identifiants restent dans le pod

`kcadm.sh` s'authentifie **à l'intérieur** du conteneur, avec des variables d'environnement qui n'en
sortent pas. Tu enchaînes l'authentification et la requête **dans la même commande**, et tu
n'affiches jamais le contenu de ces variables.

```bash
kubectl --context <ctx> -n <ns> exec <pod-kc> --request-timeout=60s -- sh -c '
  /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080/admin --realm master \
    --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1
  /opt/keycloak/bin/kcadm.sh get realms --fields realm,loginTheme'
```

Le nom exact des variables dépend de la version et du déploiement : lis-les avec
`kubectl get deploy … -o json | jq '…env[].name'` — **les noms, jamais les valeurs**.

## Lecture seule

`get`, `get-roles`, `list`. **Jamais** `create`, `update`, `delete`, `add-roles`, `remove-roles`,
`set-password`. Une attribution de rôle est un changement de privilège en production : elle relève
d'une décision humaine explicite, pas d'une enquête.

## Les questions courantes

**Un compte existe-t-il, et sous quelle forme ?**
```bash
kcadm.sh get users -r <realm> -q search=<fragment> --fields id,username,email,enabled
```
⚠️ `username` et `email` **diffèrent souvent**. Cherche sur les deux avant de conclure à l'absence —
et n'oublie pas qu'un compte peut exister dans un autre realm.

**Quels rôles porte-t-il ?**
```bash
kcadm.sh get users/<id>/role-mappings/realm -r <realm> --fields name --format csv --noquotes
```

**Quel thème sert l'écran de login ?** — sans aucun identifiant, la page est publique :
```bash
curl -s "<url-auth-du-realm>" | grep -oE "/resources/[^/]+/login/[a-z0-9-]+" | sort -u
```
Le chemin des ressources révèle le thème réellement servi. C'est plus fiable qu'un export de realm,
qui peut être périmé. Un `?v=` sur les feuilles de style trahit souvent la version du plugin.

**Quels flows, quelles exécutions ?**
```bash
kcadm.sh get authentication/flows -r <realm> --fields id,alias
```
⚠️ Un alias de flow contenant des **espaces** casse les URL construites naïvement : passe par la
liste des exécutions plutôt que par un alias encodé à la main.

## Pièges

| Symptôme | Cause réelle |
|---|---|
| `Resource not found` sur un utilisateur | recherche sur `username` alors que la valeur est dans `email` (ou l'inverse) |
| un rôle « manquant » | tu regardes le mauvais realm — le compte peut exister dans plusieurs |
| l'export de realm contredit la prod | l'export est un fichier, pas l'état : la base fait foi |
| 404 sur un flow | alias avec espaces, double-encodé |

## Ce que tu rends

Des faits : *« le compte `<id>` du realm `<r>` porte les rôles A et B »*, avec la commande en source.
Et si une action corrective supposerait d'écrire (attribuer un rôle, réinitialiser un mot de passe),
tu la **décris** — tu ne l'exécutes pas.
