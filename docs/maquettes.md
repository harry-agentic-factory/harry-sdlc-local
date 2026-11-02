# Une maquette se construit avec le design system du projet

> Pourquoi ce document existe : un panneau a été livré sans ses icônes, sans son trait de liaison et en italique,
> alors que la maquette validée les montrait — et les 99 contrôles d'alignement au pixel étaient verts. En
> remontant la chaîne, on a trouvé que la maquette elle-même n'avait jamais été confrontée au design system :
> elle demandait des dessins que le socle ne possédait pas. Personne ne l'avait vu, parce que personne ne
> regardait.

## Les quatre règles

### 1. Les valeurs viennent du design system
Couleurs, tailles, graisses, rayons et icônes d'une maquette sont des **jetons du socle**. Pas d'hexadécimal, de
`rgb()`, de `hsl()`, ni de taille ou de graisse en littéral dans les règles propres à la maquette.

Les **espacements en px ne sont pas contrôlés** : c'est la pratique du socle, et le verdict manuel que cet outil
automatise les avait déjà acceptés. Le type `taille` ne regarde que `font-size` et `border-radius`.

### 2. Les parties recopiées sont séparées des parties neuves
Le CSS du design system est recopié **verbatim** dans un bloc identifié, les règles propres à la maquette dans un
autre :

```html
<style id="ds" media="not all">  <!-- copie verbatim du socle : jamais contrôlée -->
<style id="new">                 <!-- les règles de la maquette : contrôlées -->
```

Seules les règles neuves et les attributs `style=` sont analysés — une copie n'est pas une invention, et la
signaler noierait le signal. Seconde convention acceptée, pour les maquettes écrites avant cette règle : tout ce
qui suit un commentaire `/* ===== NEW` **à l'intérieur** de `<style id="ds">`.

**Aucune des deux ⇒ pas de vert silencieux.** La sortie porte `"règles neuves": null`, une note
`convention de blocs absente`, et un code de retour non nul. Une maquette qu'on ne sait pas analyser n'est pas une
maquette conforme.

### 3. Chaque élément dessiné a sa correspondance
La colonne `Jeton / composant du socle` de la section « Fidélité à la maquette » est remplie pour **chaque** ligne :
un composant du socle, une classe existante, ou la mention explicite d'un composant **à créer**. Une ligne vide ou
`—` est signalée (`correspondance manquante`).

### 4. Un élément qui n'existe pas dans le socle y entre
Si la maquette demande un dessin que le socle n'a pas — une pastille d'étape avec son icône et son trait de
liaison, par exemple —, il est **ajouté au design system** comme composant réutilisable, documenté et testé, et
non posé en style local à l'écran. La spec technique de la story porte sa création et l'amendement du test du
socle.

C'est un **arbitrage de produit**, pas une décision d'agent : ajouter au socle a un coût, et l'alternative (se
rabattre sur le voisin le plus proche) est un **écart à la maquette**. Dès que la maquette a été validée par un
humain, c'est l'humain qui tranche.

## Déclarer le socle du projet

Le moteur ne connaît aucun jeton, aucun nom de composant, aucun chemin : tout vient du manifest, sous
`socle.<repo>`, qui porte exactement **deux** clés.

```json
"socle": {
  "<repo de code>": {
    "tokens": ["chemin/vers/tokens.css"],
    "components": "chemin/vers/ui"
  }
}
```

- `tokens` est une **liste** : un socle peut avoir plusieurs fichiers de jetons. Les noms connus sont lus par le
  motif générique `--<nom>:` — c'est ce motif, et non une liste de noms, qui rend le contrôle valable pour tout
  projet.
- `components` sert à **dériver le préfixe** des classes du socle, à partir des fichiers du socle eux-mêmes.
  Aucun préfixe identifiable ⇒ le type `règle neuve visant le socle` est **désactivé** et une note le dit : on ne
  signale pas au hasard.
- Les chemins sont **résolus**, pas validés : un fichier déclaré mais absent du disque est signalé par l'outil, pas
  par le chargement du manifest. Cette distinction compte le jour où l'arborescence d'un socle bouge.
- Le bloc ne porte **pas** l'emplacement des maquettes : un manifest est statique et ne peut pas porter un chemin
  paramétré par l'épic.

Un socle cité en exemple l'est toujours **avec son commit** — un chemin de socle est une cible mouvante, et un
guide dont l'exemple ne se vérifie plus se périme en silence.

## Contrôler une maquette

```
sdlc maquette socle <maquette.html> --repo <repo> [--spec <spec-func.md>]
```

Codes de retour : **0** conforme · **1** au moins un signalement non déclaré, ou une note de dégradation · **2**
aucun socle déclaré pour ce repo (erreur d'usage).

Les **six** types de signalement, et pas un de plus :

| Type | Ce qu'il attrape |
|---|---|
| `couleur` | hexadécimal, `rgb()`, `hsl()` ou nom de couleur CSS dans une règle neuve ou un `style=` |
| `taille` | longueur littérale sur `font-size` ou `border-radius` |
| `graisse` | valeur littérale sur `font-weight` |
| `jeton inconnu` | `var(--…)` absent des jetons du socle déclaré |
| `correspondance manquante` | ligne de la table de la spec sans jeton ni composant |
| `règle neuve visant le socle` | sélecteur neuf qui cible une classe du socle — une fois par règle, pas par déclaration |

Un signalement dont la valeur figure dans les **écarts déclarés** de la spec porte `déclaré: true`.

## La revue de maquette

Elle intervient **avant** la validation humaine de la maquette, et donc avant le premier commit de code de la
story. Son livrable est un verdict dans `<EPIC>/maquettes/<slug>-verdict.md`, dont le format est décrit dans le
mode « revue de maquette » de l'agent architecte. Résultats : `validated` · `validated_with_fixes` (les
corrections listées suffisent, pas de nouvelle validation, à condition de s'en tenir à la liste) · `returned`.

Une maquette signalée n'est **pas bloquée** : elle est rendue avec ses corrections. C'est l'humain qui valide la
maquette ; la revue le prépare.
