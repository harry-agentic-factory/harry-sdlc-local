---
kind: verdict
gate: feature
target: FEAT-59643d4e743f
review: review-feature.md
review_version: 1
role: techlead
status: draft
outcome:
signed_by:
signed_at:
---
# FEAT-59643d4e743f — verdict feature (tech lead)

## Décisions
| # | Décision | Motif | Suite |
|---|---|---|---|
| M1 | reserve | Dépendance externe : droit `PERM_SKILLS_SELF_ASSESS` non provisionné côté `talenteo-oauth2` (legacy) ; go-usine conditionné | Provisionner le droit dans `authorities` (qui/quand/format) AVANT le premier commit des chemins auth-dépendants ; porteur = tech lead ; sinon escalader (dégrader/décaler) |
| M2 | reserve | Préalable de recette : jetons RS256 avec/sans droit non tenus par la feature → AC7 + 200 inexécutables (dépend de M1) | Produire les 2 jeux de jetons + documenter le mapping jeton→`user_name` seedé au démarrage d'implémentation |
| M3 | applied | — | Le tech lead porte les contrats externes (PM-019/020/021/026) ; les réserves de ce verdict rattachent la dette à FEAT-59643d4e743f à la signature |
| m3 | applied | — | N1 déjà reformulé au spec-tech §1.8 (seed sûr par `ON CONFLICT DO NOTHING`+try/except, pas d'advisory lock partagé) ; à vérifier en revue de code, ne pas ré-introduire |
| m4 | reserve | Identité `user_name→Employee` par seed suffit pour US-1 ; BU/manager côté Boond non confirmés | Confirmer le contrat BU/manager Boond comme **préalable d'incr.2** (avant US-front/incr.2), pas d'US-1 (PM-019/030) |
| S2 | reserve | Outillage de test (T0) à créer de zéro (repo sans pytest/tests) ; effort d'infra | Réserver du budget T0 dans l'estimation d'US-1 (fondation des tests T1–T8) |
| S1 | reserve | Backlog projet pollué ; hors périmètre de gate (commun PO) | Nettoyer `docs/backlog.md` hors incrément |

## Ajouts humains
| # | Gravité | Constat |
|---|---|---|

## Discussions

## Signatures précédentes
