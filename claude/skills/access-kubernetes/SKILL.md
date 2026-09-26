---
name: access-kubernetes
description: "Observer un cluster Kubernetes en LECTURE SEULE pour une enquête — pods, logs, déploiements, images, événements. Paramétré par le manifest SDLC (`sdlc config` → `infra.cluster`) : contexte, préalable d'authentification, namespaces et déploiements viennent du projet, rien n'est en dur. À charger dès qu'une question porte sur ce qui tourne, ce qui a tourné, ou ce qui est déployé."
---

# Observer un cluster (paramétré par le manifest)

Tu **ne devines pas** le cluster : tu lis `infra.cluster` dans le manifest, puis tu appliques la méthode.

```bash
sdlc --project <PREFIX> config | jq .infra.cluster
```

Tu y trouves `context`, `preflight` (commande d'authentification à jouer d'abord), `namespaces`
(namespace → déploiements) et d'éventuels `_gotcha`. **Lis les `_gotcha` avant de commencer** : ils
existent parce que quelqu'un s'est déjà fait avoir.

## Règle absolue — lecture seule

`get`, `describe`, `logs`, `top`, `events`. **Jamais** `apply`, `delete`, `patch`, `scale`, `edit`,
`rollout restart`, ni `exec` d'une commande qui écrit. Un `exec` de lecture est permis quand c'est le
seul moyen (voir plus bas), jamais pour modifier quoi que ce soit.

## Toujours : le préalable, puis un timeout

```bash
<preflight du manifest>          # sans lui, les erreurs mentent (« must be logged in »)
kubectl --context <ctx> --request-timeout=60s …
```

**macOS n'a pas `timeout`.** Passe toujours `--request-timeout` : sans lui, une commande qui n'aboutit
pas bloque jusqu'à la fin des temps et tu conclus à tort à une panne.

## Les quatre questions qui reviennent

### Qu'est-ce qui tourne, et depuis quand ?

```bash
kubectl --context <ctx> -n <ns> get deploy <d> \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl --context <ctx> -n <ns> get pods -l <selector>   # AGE = depuis quand
```

**La version déployée, c'est le tag de l'image du conteneur** — pas un numéro de version dans un
fichier, pas ce que dit la CI. Le conteneur fait foi.

### Que disent les logs ?

```bash
kubectl --context <ctx> -n <ns> logs <pod> --since=24h > "$SCRATCH/svc.log"
grep -n "<motif>" "$SCRATCH/svc.log" | cut -c1-300
```

**Redirige toujours dans un fichier, puis `grep`.** Ne fais jamais défiler un dump entier : tu noies
ton contexte, et tu risques d'y ramasser un secret au passage.

⚠️ **Déclare ta fenêtre d'observation.** Les logs d'un pod redémarré ne remontent pas avant son
démarrage. Vérifie l'âge du pod avant de conclure « rien dans les logs » — sinon tu confonds *absence
d'événement* et *absence de trace*.

```bash
head -1 "$SCRATCH/svc.log"; tail -1 "$SCRATCH/svc.log"   # les bornes réelles de ce que tu observes
```

Pour les redémarrages et les échecs de sonde : `kubectl get events --sort-by=.lastTimestamp`.

### D'où vient la configuration ?

```bash
kubectl --context <ctx> -n <ns> get deploy <d> -o json \
 | jq -r '.spec.template.spec.containers[0].env[]? | "\(.name)\t\(if .valueFrom then "←secret/cm" else "inline" end)"'
```

Ça donne les **noms** des variables et leur provenance. **N'extrais jamais une valeur issue d'un
secret.** Le nom et l'origine suffisent à raisonner ; la valeur ne te sert qu'à fuiter.

### Une valeur non secrète, lisible uniquement dans le pod

```bash
kubectl --context <ctx> -n <ns> exec <pod> -- sh -c 'printenv UNE_VAR_NON_SECRETE'
```

Et si la variable contient une URL avec des identifiants, masque-les **dans la commande**, pas après :

```bash
... -- sh -c 'printenv DB_URL | sed "s#//.*@#//***@#"'
```

## Ce qui n'est pas dans le cluster

Une base managée, un fournisseur de mail, un DNS : ils ne sont pas ici. Le cluster ne te dit que ce
qu'il héberge. Cherche l'accès correspondant dans `infra`, ou déclare la limitation.

## Pièges

| Symptôme | Cause réelle |
|---|---|
| « must be logged in to the server » | le `preflight` du manifest n'a pas été joué |
| la commande ne rend jamais la main | pas de `--request-timeout` |
| « rien dans les logs » | pod redémarré : la fenêtre d'observation commence après |
| le tag de l'image ne correspond à aucun commit | image construite depuis une **branche**, pas depuis la référence — vérifie côté CI |
