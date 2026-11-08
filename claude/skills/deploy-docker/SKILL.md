---
name: deploy-docker
description: Déploie un module de code sur un stack docker-compose LOCAL, piloté par les paramètres du manifest SDLC (`sdlc config` → `deploy.<repo>.environments.<env>`). Couvre la construction de l'artefact, le `compose up` du seul service concerné, l'attente de santé, la vérification de version et le rollback. Générique et project-agnostic : toutes les valeurs projet viennent du manifest, rien n'est en dur. À utiliser dès qu'un agent (deployer) doit déployer une story dont l'environnement cible déclare `"skill": "deploy-docker"` — typiquement l'environnement `dev`, monté en local plutôt que sur un cluster.
---

# Déployer sur un stack docker local (paramétré par le manifest)

Jumeau de `deploy-jenkins`, pour les projets dont l'environnement `dev` est un **stack docker sur la
machine du développeur** plutôt qu'un namespace de cluster. Même contrat, même vocabulaire : tu lis les
paramètres dans le manifest, tu appliques la procédure, tu ne devines rien.

## Pourquoi un environnement `dev` local

Le loop déploie deux fois : **`dev`** en pré-merge, **`integration`** en post-merge. Rien n'impose que
`dev` soit un cluster. Un stack docker local est souvent **meilleur** :

- **isolé** — deux stories en vol ne se marchent pas dessus, et l'`env_lock` devient inutile ;
- **jetable** — un `reset` efface tout en secondes, là où un cluster garde les traces de chaque essai ;
- **rapide** — pas de CI, pas de registre, pas de gitops : secondes contre dizaines de minutes ;
- **sans effet de bord** — crucial quand déployer et recetter **crée des objets réels** (realms, comptes,
  clients) qui pollueraient un environnement partagé.

> ⚠️ **Ce que ça coûte.** Un stack local mocke généralement une partie de ses dépendances. Une dérive de
> contrat avec un service réellement mocké ne se verra qu'à l'`integration`. Deux parades, à arbitrer par
> projet : garder **réels** les composants à fort risque d'intégration (une base, un IdP) et ne mocker que
> les surfaces étroites ; et prévoir **une canari** sur un environnement réel pour la story la plus
> exposée, avant le merge de l'épic.

## Ce que le projet déclare

```json
"deploy": { "<repo>": {
    "environments": {
      "dev": {
        "skill":   "deploy-docker",
        "compose": "<repo>/local-stack/docker-compose.yml",   // relatif à reposRoot
        "service": "<nom du service compose à redéployer>",
        "build":   "make -C <repo>/local-stack jar",          // produit l'artefact, optionnel
        "up":      "make -C <repo>/local-stack up",           // démarre le stack complet, optionnel
        "health":  "http://localhost:8099/actuator/health",
        "version": "http://localhost:8099/actuator/info"      // optionnel
      },
      "integration": { "skill": "deploy-jenkins", "…": "…" }
    }
}}
```

Les deux environnements **n'ont pas à partager le même skill** : c'est le cas nominal qu'un `dev` local
cohabite avec une `integration` sur cluster.

## Obtenir la cible — jamais en dur

```bash
sdlc --project <PREFIX> deploy-target <repo> --env dev
```

Seule façon d'obtenir une cible. Ne lis pas `deploy.<repo>` à la main.

## Procédure

### 1. Préalables
```bash
docker info > /dev/null || { echo "Docker n'est pas démarré"; exit 1; }
```
Si le manifest déclare une contrainte de toolchain (version de JDK, de Node…), **vérifie-la avant de
construire**. Un build qui échoue sans diagnostic coûte une demi-heure de confusion.

### 2. Construire l'artefact
Lance la commande `build` du manifest. Elle produit le binaire **hors de l'image** (jar, bundle), parce
que le contexte de build d'une image n'a pas à contenir les identifiants de dépôt privé de la machine.

### 3. Déployer le seul service concerné
```bash
docker compose -f <compose> up -d --build <service>
```
**`<service>` et pas tout le stack** : redémarrer une base ou un IdP à chaque déploiement détruirait
l'état que la recette vient de construire.

Si le stack n'est pas démarré du tout, lance d'abord la commande `up` du manifest.

### 4. Attendre la santé — borné
```bash
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "<health>")
  [ "$code" = "200" ] && break
  sleep 5
done
```
Jamais d'attente non bornée. En cas de dépassement, remonte les **30 dernières lignes de log** du service
— c'est ce qui permet de diagnostiquer sans relancer.

### 5. Vérifier qu'on a déployé ce qu'on croit
Le piège symétrique du « CI vert qui redescend l'ancien artefact » existe aussi ici : une image en cache
peut faire croire à un déploiement réussi. Vérifie **l'empreinte réelle** :

```bash
docker compose -f <compose> images <service>          # ID d'image
docker compose -f <compose> exec -T <service> <cmd>   # ou une preuve applicative
```

Si le manifest déclare `version`, interroge-le et **consigne la valeur** dans le `deploy.md`.

### 6. Rollback
```bash
docker compose -f <compose> stop <service>
# redéployer l'artefact précédent (git checkout <sha> + rebuild), puis up -d --build <service>
```
Un stack local se reconstruit : en cas de doute, `reset` complet puis redéploiement est **plus rapide et
plus sûr** qu'un rollback chirurgical.

## Ce que tu écris dans `deploy.md`

Cible (`dev` local), service déployé, empreinte d'image, résultat du contrôle de santé, et **ce qui est
mocké dans ce stack** — le recetteur en a besoin pour savoir ce que son test prouve réellement.

## Limites, à dire plutôt qu'à taire

- Un vert local **ne vaut pas** un vert d'intégration : ce qui est mocké n'est pas testé.
- Le stack est **sur une machine**, donc indisponible pour quiconque d'autre. Un résultat de recette local
  n'est pas reproductible par un tiers sans remonter le stack.
- Si la story touche une dépendance **mockée** dans ce stack, dis-le explicitement dans `deploy.md` et
  propose une canari sur un environnement réel.
