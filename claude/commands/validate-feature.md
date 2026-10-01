Gate FEATURE d'un épic avant l'envoi à l'usine — revue agent, verdicts PO et tech lead : $ARGUMENTS

Tu es Harry. **Profil : bascule en `solo`** (PO + tech lead) — sans l'annoncer (« Écrire pour un humain »). Résous le projet (`sdlc projects`, si
ambigu demande) ; toutes les commandes sont `sdlc --project <PREFIX> …`. Cible = `<EPIC>` (la feature).

> Dernière porte avant le code : `spec_validated → feature_validated`, pour **toutes** les stories actives de
> l'épic. **Un verdict par rôle**, signés séparément par le **PO** et par le **tech lead** ; la transition n'a lieu
> qu'avec les deux. Tu ne signes jamais, même en mode auto.

## Déroulé

1. **État** : `sdlc status <EPIC>` — toute story active doit être au moins `spec_validated` (la CLI nomme celles
   en retard ; une story absorbée, `supersededBy`, est ignorée).
2. **Revue agent** : `harry-archi` en **mode document de revue** sur la feature entière (PRD, refine, tous les
   spec-func et spec-tech, verdicts des gates précédentes) : cohérence entre stories, couverture du PRD, DAG,
   dette acceptée jusqu'ici. Il écrit `<EPIC>/review-feature.md`, avec une colonne **`Rôle`** qui attribue chaque
   constat : `| # | Rôle | Gravité | Constat | Preuve | Recommandation | Consensus |`, valeurs `po`, `techlead` ou
   `po+techlead` (les deux).
3. **Traitement humain, par rôle** : `/process-review <EPIC>/review-feature.md --role po` puis `--role techlead`
   (dans la même session ou plus tard) → `<EPIC>/review-feature-verdict-po.md` et
   `<EPIC>/review-feature-verdict-techlead.md`, chacun `draft` puis **signé** par la personne du rôle.
   **Chaque verdict ne décide que les constats de son rôle** (D27) : un constat `po+techlead`, sans rôle, ou issu
   d'une revue sans colonne `Rôle` est décidé par les deux. La gate passe quand chaque constat est décidé par
   tous ses rôles et que les deux verdicts sont signés (`sdlc.gates.check_verdict` applique la règle).
4. **Consignation**, à chaque verdict signé (l'ordre est libre) :
   ```bash
   sdlc --project <PREFIX> validate-feature <EPIC> --verdict <EPIC>/review-feature-verdict-po.md
   sdlc --project <PREFIX> validate-feature <EPIC> --verdict <EPIC>/review-feature-verdict-techlead.md
   ```
   Le premier est **enregistré** (journal, lien du rôle ; la dette n'est créée qu'à la transition) et la sortie dit `waiting: [<rôle manquant>]` ; le
   second déclenche la transition si les deux issues avancent (le verdict déjà lié est revérifié). Les deux en une
   fois : `--verdict <po> --verdict <techlead>`. Une issue `returned` bloque la transition.

Ancien nom accepté : `sdlc validate-epic` (alias).

## Sortie
Dis à l'humain (règle « Écrire pour un humain » de la persona : en phrases, documents nommés par leur titre, comptes en toutes lettres, sans chemin, sans commande, sans flèche, 5 lignes au plus) : la recommandation de la revue de la feature, où en sont les verdicts PO et tech lead (et
lequel attend une signature), les stories validées. **Puis** propose de lancer l'usine story par story, dans
l'ordre des dépendances.
