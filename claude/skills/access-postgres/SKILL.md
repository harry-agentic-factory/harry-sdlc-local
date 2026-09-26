---
name: access-postgres
description: "Interroger la base d'un service en LECTURE SEULE pour une enquête, sans jamais extraire les identifiants. Paramétré par le manifest SDLC (`sdlc config` → `infra.database`) : hôte, provenance des credentials, client et mode d'accès viennent du projet. À charger dès qu'une question porte sur ce qui est RÉELLEMENT stocké — la base tranche souvent en une requête ce que le code ne fait que suggérer."
---

# Interroger la base (paramétré par le manifest)

```bash
sdlc --project <PREFIX> config | jq .infra.database
```

Tu y trouves `engine`, `location`, `via`, `urlFrom`, `credentialsFrom`, `client`, `readOnly`.

## Pourquoi y penser TÔT

Le code dit ce qui *devrait* se passer ; la base dit ce qui *s'est* passé. Un champ qu'on soupçonne
écrasé, un statut qu'on croit incohérent, une valeur qu'on déduit de trois appels — **un `SELECT` le
règle en dix secondes**, et le résultat est une mesure, pas une inférence.

Incident réel : une langue de compte soupçonnée d'être effacée par une mise à jour. Toute la
démonstration a été faite en lisant le code. Un `SELECT lang_key FROM account WHERE id = …` aurait
donné la réponse immédiatement, et au niveau de preuve le plus élevé.

## Règle absolue — `SELECT` uniquement

Aucun `INSERT`, `UPDATE`, `DELETE`, `ALTER`, `CREATE`, `TRUNCATE`. Aucune transaction ouverte et
laissée en plan. Tu observes une production : une requête lourde sans `LIMIT` sur une grosse table est
une écriture déguisée (elle consomme le service).

Ajoute toujours un `LIMIT`, et préfère un `WHERE` indexé.

## Ne jamais extraire les identifiants

Ils sont dans un secret. **Tu ne les lis pas, tu ne les affiches pas, tu ne les mets pas dans une
variable visible.** Tu les injectes **dans la même commande** que celle qui s'en sert.

Schéma générique, base hors du cluster, accès par redirection de port :

```bash
# 1. ouvrir la redirection vers l'hôte déclaré (en arrière-plan, bornée dans le temps)
# 2. jouer la requête en injectant le mot de passe depuis le secret, sans l'afficher :
PGPASSWORD="$(kubectl --context <ctx> -n <ns> get secret <s> -o jsonpath='{.data.<clé>}' | base64 -d)" \
  <client> -h 127.0.0.1 -p <port> -U "<user>" -d "<db>" \
  -c "SELECT … LIMIT 50;"
```

`PGPASSWORD` est passé **en préfixe de commande** : il ne persiste pas dans l'environnement du shell,
n'apparaît pas dans un `echo`, et disparaît avec le processus. Ne fais jamais
`PASS=$(...)` puis `echo $PASS`.

Si le client n'est pas installé localement, un pod jetable portant le client est une **écriture dans
le cluster** : ne le fais pas de ta propre initiative — déclare la limitation.

## Méthode

1. **Formule la question en une requête.** « Le champ a-t-il été écrasé ? » devient
   `SELECT <champ>, <date_modif> FROM <table> WHERE id = '<id>'`.
2. **Regarde la ligne réelle avant d'agréger.** Un cas précis, daté, vaut mieux qu'un compte.
3. **Compare à ce que dit le code**, et si les deux divergent, c'est la base qui gagne —
   *mesure > lecture de code*.
4. **Cite ta requête** dans tes faits : un résultat sans sa requête n'est pas reproductible.

## Ce que tu rends

```
constat : lang_key vaut NULL pour le compte <id>
preuve  : 1 ligne, colonne lang_key = NULL, modified_date = 2026-09-23 09:51
source  : SELECT lang_key, modified_date FROM account WHERE id = '<id>'
niveau  : mesuré
```

## Pièges

| Symptôme | Cause réelle |
|---|---|
| authentification refusée | identifiants pris dans le mauvais namespace / mauvaise clé du secret |
| la redirection de port se ferme seule | processus tué à la fin de la commande — la lancer en arrière-plan et la borner |
| requête interminable | pas de `LIMIT`, ou filtre non indexé — tu pèses sur la production |
| la valeur lue contredit l'IHM | il y a peut-être un cache applicatif ou un miroir : dis-le, ne tranche pas seul |
