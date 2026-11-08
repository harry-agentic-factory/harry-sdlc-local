# REF-1 — panneau « Parcours » de l'écran « Nouvelle feature »

Cas de référence du mécanisme de fidélité. Extrait de la spec d'une story livrée **sans** les éléments que sa
maquette validée montrait : c'est un cas de **non-conformité volontaire**, rouge par construction. Le rouge est le
succès du mécanisme, pas une régression — ne jamais « réparer » en assouplissant l'attendu.

## Comportement

Le panneau liste les activités du parcours de la feature, une pastille par étape.

## Fidélité à la maquette

Maquette : SAMPLE-UI2/maquettes/nouvelle-feature-v7.html

| Élément | Attendu (maquette) | Jeton / composant du socle | Contrôle |
|---|---|---|---|
| Icônes | une pastille par étape, quatre étapes, la 3e répétant le dessin de la 1re ; la ligne « usine » est un second groupe, hors de la liste contrôlée | trois dessins à ajouter au socle | `.exd-icon svg` → `icône` = `file, list, file, file-check` |
| Trait | un trait pointillé continu de haut en bas | à créer comme composant du socle | `.exd-list::before` → `border-left-style` = `dashed` |
| Italique | libellés en semibold, jamais en italique | graisse du socle | `.exd-label` → `font-style` = `normal` |

### Écarts déclarés

aucun.

## Critères d'acceptation

- **AC1** — Given le panneau rendu, When on le compare à la maquette, Then les trois éléments ci-dessus sont tenus.
  - 🔬 Must-validate : comparaison élément par élément, assertion sur les trois contrôles.

## Tests obligatoires au build

Comparaison à la maquette avant les mesures d'alignement.

## Sources

Maquette validée, et le code livré au commit de référence.
