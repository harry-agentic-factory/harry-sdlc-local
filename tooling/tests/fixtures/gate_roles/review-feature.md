---
kind: review
gate: feature
target: FEAT-59643d4e743f
version: 1
reviewer: harry-archi
date: 2026-09-30
---

# Revue feature — FEAT-59643d4e743f · Suivi annuel des compétences (Harington)

## Synthèse

- **Recommandation globale PO** : `go-avec-réserves`
- **Recommandation globale tech lead** : `go-avec-réserves`
- **Compte par gravité** : bloquant **0** · majeur **3** · mineur **4** · suggestion **2**
- **Périmètre relu (feature entière)** : PRD, refine, décisions D1–D12, la story unique US-1
  (spec-func + spec-tech corrigé v-finale), les **deux verdicts signés** (spec-func `validated`,
  spec-tech `validated`), les revues détaillées `harry-archi` (spec-func v1, spec-tech v1 + revue
  ciblée v2), la dette projet et le backlog. Code confronté : `resume_matcher_api` @ `main`
  (placement, patterns seed/advisory-lock, claim `user_name`, enveloppe d'erreur, Sendinblue),
  Brain `technical/repos.md` (architecture cible + statut legacy de `talenteo-oauth2`).

**Verdict d'ensemble.** La feature est **prête pour l'usine avec réserves**, à condition de lever
**deux préalables externes AVANT le premier commit** (provisionnement de la permission côté oauth
legacy + jetons de recette). Le socle est sain : périmètre incr.1 net et cohérent d'un bout à
l'autre, une seule story livrable de valeur autonome et testable, spec-tech corrigée (les 2
bloquants et 4 majeurs de la revue spec-tech sont **levés** au verdict), et une dette abondante mais
**tracée** et non contradictoire. Ce que je signale relève de la **cohérence de traçabilité de la
dette** (les IDs PM réutilisés d'US-1 ne pointent pas la dette de CETTE feature), d'un **risque
d'implémentation résiduel** concentré sur une dépendance externe (permission oauth), et de la
**reproductibilité de recette** conditionnée aux jetons. Rien qui justifie un `return`, mais deux
points à traiter au tout début de l'implémentation, pas « plus tard ».

## Constats

| # | Rôle | Gravité | Constat | Preuve | Recommandation | Consensus |
|---|---|---|---|---|---|---|
| M1 | [techlead] | majeur | **Dépendance externe non confirmée : provisionnement de `PERM_SKILLS_SELF_ASSESS` côté `talenteo-oauth2` (legacy).** Toute l'auth US-1 repose sur `@jwt_required(required_permission='PERM_SKILLS_SELF_ASSESS')`, mais ce droit n'existe pas encore dans `authorities`, et le Brain classe `talenteo-oauth2` **legacy** (« no new feature there ») : ajouter/provisionner un droit dans un service legacy est une action externe non tenue par cette feature, et **bloque tous les 200 + le 403** d'AC7. C'est un « go-usine conditionné » classique, exactement le motif PM-022/PM-025 d'une autre feature. | spec-tech §1.5 (`PERM_SKILLS_SELF = 'PERM_SKILLS_SELF_ASSESS'`, « à confirmer avant l'usine, PM-020/021 ») ; `technical/repos.md` (talenteo-oauth2 = Legacy, « no new feature there ») ; dette PM-020/021 | **Lever avant le premier commit** : confirmer que le droit est provisionnable côté oauth (qui, quand, format du claim `authorities`) et que les jetons de recette le porteront. Si non provisionnable à temps, escalader l'arbitrage (dégrader la permission ou décaler). Ne pas lancer le code des chemins auth-dépendants avant confirmation. | 0.8 |
| M2 | [techlead] | majeur | **Préalable de recette non tenu par la feature : jeu de jetons de recette (avec ET sans le droit).** La recette de la quasi-totalité des AC (EMP_A avec droit ; un jeton sans droit pour AC7/403 ; EMP_A/EMP_B pour l'ownership) suppose des jetons RS256 réels porteurs (ou non) de `PERM_SKILLS_SELF_ASSESS`, alignés sur les `user_name` seedés. Sans eux, T7/AC7 et tous les 200 sont **inexécutables** — la recette de l'incrément ne serait pas reproductible. Dépend de M1. | spec-tech §5 « S2 — préalable de recette » (« jetons avec/sans `PERM_SKILLS_SELF_ASSESS` ») ; spec-func AC7 §6 ; §1.8 « fixtures de recette EMP_A/EMP_B … user_name = identité des jetons » | **Lever au démarrage d'implémentation** : produire/obtenir les 2 jeux de jetons et documenter le mapping jeton→`user_name` seedé. À tracer comme préalable de recette bloquant l'accept, pas comme dette de conception. | 0.8 |
| M3 | [po+techlead] | majeur | **Traçabilité de la dette de CETTE feature : « Aucune dette ouverte » alors que les specs traînent 6 réserves actives (PM-018/019/020/021/026/031/032).** `docs/dette.md` §« Dette de cette feature » indique **aucune dette ouverte**, mais toutes les réserves citées par les specs d'US-1 portent des IDs PM enregistrés sur **d'autres features** (FEAT-bafe574dff3c, FEAT-de5be1ba8da2, FEAT-667f137da382). Résultat : les dettes réellement portées par FEAT-59643d4e743f ne sont **rattachées à aucun verdict de cette feature** — risque qu'elles sortent du radar au go-usine et à l'incr.2. Ce n'est pas une contradiction technique mais un **trou de traçabilité** à combler avant l'usine. | `docs/dette.md:6` (« Aucune dette ouverte » pour la feature) vs PM-018/019/020/021 (FEAT-bafe574dff3c), PM-031/032 (FEAT-de5be1ba8da2), PM-026 (FEAT-bafe574dff3c) ; spec-func §8 et spec-tech §5 (ces IDs cités comme dette d'US-1) | Au traitement de cette gate, **ouvrir/rattacher explicitement les réserves d'US-1 à FEAT-59643d4e743f** via les verdicts feature (PO + tech lead) : identité/permission (PM-018/019/020/021), horloge/codes (PM-031/032), outillage migration (PM-026). Le PO acte ce qu'il porte hors incr.1 ; le tech lead porte les contrats externes. Sinon la dette de la feature reste invisible. | 0.75 |
| m1 | [po] | mineur | **Lecture « par année » : le PRD/refine promettent une capacité que le contrat ne rend que partiellement — écart tracé mais à relire au niveau feature.** Le PRD (« lire l'auto-évaluation d'une année ») et le refine (« lire l'auto-évaluation d'une année donnée ») annoncent une lecture ciblée par année ; le contrat la sert via `GET .../history?year=YYYY` (D11), sans endpoint dédié. C'est **tranché et cohérent** (D11 + AC8), mais la formulation du PRD reste littéralement plus large que ce qui est livré. Non bloquant. | `out/prd.md:64`, `out/refine.md:32` vs D11 (`out/decisions.md:15`) ; spec-func E6 + AC8 (filtre `?year`) | Laisser tel quel (D11 fait foi) ou ajouter une phrase au PRD renvoyant explicitement à D11 pour éviter une relecture future croyant à un endpoint manquant. Acceptable en l'état. | 0.6 |
| m2 | [po] | mineur | **Découpage à une seule story : US-front annoncée dans l'incr.1 mais absente du refine — DAG incomplet vs promesse d'incrément.** Le PRD décrit l'incrément 1 comme « auto-évaluation + reporting **par salarié** » (donc back **et** front) ; le refine ne contient qu'US-1 (socle back) et renvoie US-front en « hors de ce refine ». La feature envoyée à l'usine ne livre donc **pas** l'écran, alors que CS3 (affichage) fait partie des critères de succès de l'incrément. C'est un choix PO assumé (« premier incrément petit : le socle back »), mais l'incrément « démontrable de bout en bout » à l'utilisateur final ne l'est pas sans le front. | `out/prd.md:65-68` (front reporting-v2 dans l'incr.1) et CS3 `:91-92` vs `out/refine.md` (US-1 seule) + §« Hors de ce refine » (US-front) | Confirmer explicitement au verdict PO que **US-1 seule** part à l'usine (valeur = API vérifiable), CS3 restant couvert par US-front à suivre. Bon découpage technique ; juste acter que « incrément 1 » livré ≠ « incrément 1 » du PRD (le front suit). | 0.7 |
| m3 | [techlead] | mineur | **Résidu rédactionnel N1 (advisory lock du seed) : non levé au fond, porté en réserve non bloquante.** La revue ciblée spec-tech v2 a laissé N1 ouvert (formulation « seed sous le même advisory lock que le scheduler » imprécise vs code réel — lock de session relâché en `finally`), la sûreté réelle venant de `ON CONFLICT DO NOTHING`. Le spec-tech corrigé le reformule correctement (§1.8), donc l'impact est nul, mais c'est un point à ne pas ré-introduire à l'implémentation. | revue spec-tech v2 constat N1 ; spec-tech §1.8 (reformulé : sûreté par `ON CONFLICT DO NOTHING` + try/except, advisory dédié seulement si un seul worker voulu) ; `resume_matcher_api/CLAUDE.md:91` (advisory locks Gunicorn confirmés) | Aucune action de gate : implémenter le seed via `ON CONFLICT DO NOTHING` + try/except IntegrityError/rollback ; n'invoquer un advisory lock **dédié** que si un seul worker doit seeder. Vérifiable en revue de code. | 0.7 |
| m4 | [techlead] | mineur | **Dépendance identité `user_name → Employee` matérialisée uniquement par le seed : robuste pour US-1, fragile dès l'incr.2.** L'ownership et la résolution « me » reposent entièrement sur `employee.user_name` seedé (pas de rapprochement Boond attesté, PM-019). C'est suffisant et correctement tracé pour US-1 (auto-éval « je = ma resource »), mais l'incr.2 (validation manager, agrégats BU) exige BU/manager côté Boond — **non confirmés**. À ne pas oublier comme préalable d'incr.2, pas d'US-1. | spec-tech §1.4 (`current_employee()` via `user_name`, pont Boond hors US-1) ; PRD §« Dette/risques » (BU/manager à confirmer avant incr.2) ; dette PM-019/PM-030 | Aucune action avant le code d'US-1 (le seed suffit). Tracer BU/manager Boond comme **préalable d'incr.2** au verdict feature, pour ne pas coder US-front/incr.2 dessus sans contrat. | 0.7 |
| S1 | [po+techlead] | suggestion | **Backlog du projet illisible / pollué (doublons, sondes de recette).** `docs/backlog.md` liste une vingtaine d'entrées « ? — … » dont plusieurs variantes du même PRD compétences et des « sondes de recette à ignorer ». N'affecte pas la feature, mais rend impossible de vérifier au niveau feature qu'il n'y a pas de doublon d'épic ou de conflit de périmètre avec une autre feature « Skills Tracking ». | `docs/backlog.md:4-23` (multiples « PRD — Suivi annuel des compétences » + « Sonde recette … à ignorer ») | Hors périmètre de gate ; signaler au PO de nettoyer le backlog (dé-dupliquer les PRD compétences, retirer les sondes) pour la lisibilité des prochaines features. Sans impact sur le go-usine d'US-1. | 0.6 |
| S2 | [techlead] | suggestion | **Outillage de test à créer de zéro : bien porté par US-1, mais c'est un effort d'infrastructure sous-estimable dans l'estimation.** Le repo n'a ni `pytest`, ni `tests/`, ni `conftest.py` (constaté à la revue spec-tech). B1 est levé au plan (§1.9/§3 + invariant 14-ter), donc conforme, mais T0 (app de test sans thread background + base + fabrique JWT RS256 + monkeypatch horloge) est un vrai chantier avant que T1–T8 tournent — à ne pas comprimer. | revue spec-tech B1 (levé) ; spec-tech §1.9 (Pipfile + conftest), §3 T0, invariant 14-ter ; `resume_matcher_api/Pipfile` `[dev-packages]` vide (constaté) | Aucune correction de spec : réserver du budget pour T0 dans l'estimation d'US-1 (fondation de toute la stratégie de tests). Signalé au tech lead pour le go-usine. | 0.65 |

## Points explicitement vérifiés et jugés conformes (pas de constat)

- **Placement conforme à l'architecture cible** : back `resume_matcher_api`, front `reporting-v2/`,
  `talenteo-oauth2` consommé en lecture seule (legacy) — aligné `technical/repos.md` et D9. Aucune
  construction sur du legacy (`career-ms` explicitement écarté).
- **Cohérence PRD ↔ refine ↔ spec-func ↔ spec-tech ↔ décisions** : périmètre incr.1 identique
  partout ; hors-scope (validation manager, écarts profil, BU/global, admin, relances, front) cité
  de façon cohérente dans les 4 documents et rappelé en §9 des specs. D1–D12 cohérents et référencés
  (D11 = lecture par année ; D12 = ownership by-construction / `NO_EMPLOYEE_MAPPING`).
- **US-1 = valeur autonome et testable sans le front** : les 8 AC sont chiffrés et pilotables en API
  pure (HTTP, `code` stable, longueurs, niveaux). CS1/CS2/CS4/CS5 couverts ; CS3 (écran) correctement
  exclu et renvoyé à US-front. DAG sain (story sans dépendance).
- **Gates story déjà franchies proprement** : spec-func `validated` (10 constats `applied`), spec-tech
  `validated` (revue ciblée v2 : 2 bloquants + 4 majeurs + tous mineurs **levés**, seul N1 rédactionnel
  résiduel non bloquant). Aucun bloquant technique rouvert au niveau feature.
- **Codes d'erreur applicatifs stables (R10, PM-032)** : liste figée et cohérente entre spec-func et
  spec-tech ; `FORBIDDEN_OWNERSHIP` réservé (non émis) et `NO_EMPLOYEE_MAPPING` acté (D12) —
  contradiction spec-func/spec-tech **résolue**.
- **Immutabilité de l'historique (CS2/R5)** : nouvelle campagne = nouvelle `self_assessment`, entrée N
  inchangée après N+1 ; invariant 15 + AC8/T6. Sélection de campagne courante corrigée (M1 spec-tech
  levé : l'ouverte prime, `max(year)` seulement pour discriminer le code fenêtre).
- **Affirmation PRD « Sendinblue déjà présent dans le back »** : **exacte**
  (`resume_matcher_api/CLAUDE.md:81` Brevo/SendinBlue) — pas de constat ; relances bien hors incr.1 (D8).

## Distinction « à corriger avant le code » vs « dette acceptable tracée »

- **À lever AVANT le premier commit** : M1 (permission oauth provisionnée) et M2 (jetons de recette) —
  ce sont des préalables externes, pas des choix de conception ; sans eux ni le code auth-dépendant ni
  la recette ne tiennent. M3 (rattacher la dette de la feature) doit être fait **au traitement de cette
  gate** (dans les verdicts), pas reporté.
- **Dette acceptable, tracée, non bloquante pour US-1** : PM-026 (outillage migration `.sql`/`create_all`,
  pas d'Alembic), PM-031 (horloge injectable — déjà implémentée via `services/clock.py`), PM-032 (codes
  d'erreur — figés ici), PM-019 (rapprochement Boond auto — hors US-1, seed suffit). N1/m3 (rédactionnel
  seed) et S2 (effort T0) relèvent de la vigilance à l'implémentation, pas d'un blocage de gate.
- **Préalable d'incr.2 (pas d'US-1)** : BU/manager côté Boond (m4, PM-019/030) — à confirmer avant de
  coder US-front/incr.2, sans impact sur le go-usine d'US-1.

## Recommandation globale par rôle

- **PO — `go-avec-réserves`** : le découpage (US-1 socle back seul, US-front à suivre) est sain et
  livre une valeur vérifiable ; réserves à acter au verdict : l'incrément livré ≠ incrément 1 « complet »
  du PRD (le front suit, CS3 différé — m2), lecture par année servie par le filtre `history` (m1, D11),
  et rattachement explicite de la dette portée à cette feature (M3).
- **Tech lead — `go-avec-réserves`** : plan implémentable tel quel (bloquants spec-tech levés), mais
  **go conditionné** à la levée de deux préalables externes avant le premier commit — permission
  `PERM_SKILLS_SELF_ASSESS` provisionnée côté oauth legacy (M1) et jetons de recette avec/sans droit
  (M2) — plus le rattachement de la dette (M3) et la vigilance sur l'effort T0 (S2), le seed
  concurrent-safe (m3) et le préalable BU/manager d'incr.2 (m4).

## Tableau récapitulatif

| # | Rôle | Gravité | Constat | Preuve | Recommandation | Consensus |
|---|---|---|---|---|---|---|
| M1 | techlead | majeur | Permission `PERM_SKILLS_SELF_ASSESS` non provisionnée côté oauth legacy (dépendance externe) | spec-tech §1.5 ; `technical/repos.md` (oauth legacy) ; PM-020/021 | Confirmer/provisionner avant le premier commit ; sinon escalader | 0.8 |
| M2 | techlead | majeur | Jetons de recette (avec/sans droit) non tenus → AC7 + 200 inexécutables | spec-tech §5 S2, §1.8 ; spec-func AC7 | Produire les 2 jeux de jetons + mapping `user_name` au démarrage | 0.8 |
| M3 | po+techlead | majeur | « Aucune dette ouverte » pour la feature alors que 6 réserves actives (IDs d'autres features) | `docs/dette.md:6` vs PM-018/019/020/021/026/031/032 | Rattacher les réserves d'US-1 à FEAT-59643d4e743f dans les verdicts feature | 0.75 |
| m1 | po | mineur | Lecture « par année » promise par PRD/refine, servie par filtre `history` (D11) | `prd.md:64`, `refine.md:32` vs D11 ; AC8 | Laisser tel quel (D11 fait foi) ou pointer D11 dans le PRD | 0.6 |
| m2 | po | mineur | Incr.1 du PRD = back+front, mais seule US-1 (back) part à l'usine ; CS3 différé | `prd.md:65-68`, CS3 vs `refine.md` (US-1 seule) | Acter au verdict PO qu'US-1 seule part ; front suit | 0.7 |
| m3 | techlead | mineur | N1 (advisory lock seed) rédactionnel, reformulé au spec-tech, à ne pas ré-introduire | revue spec-tech v2 N1 ; spec-tech §1.8 ; `CLAUDE.md:91` | Seed `ON CONFLICT DO NOTHING` + try/except ; advisory dédié seulement si 1 worker | 0.7 |
| m4 | techlead | mineur | Identité `user_name→Employee` par seed OK pour US-1 ; BU/manager Boond = préalable incr.2 | spec-tech §1.4 ; PRD dette ; PM-019/030 | Tracer BU/manager Boond comme préalable d'incr.2 | 0.7 |
| S1 | po+techlead | suggestion | Backlog projet pollué (doublons PRD compétences, sondes de recette) | `docs/backlog.md:4-23` | Nettoyer le backlog (hors gate) | 0.6 |
| S2 | techlead | suggestion | Outillage de test créé de zéro (T0) : effort d'infra à ne pas sous-estimer | revue spec-tech B1 ; spec-tech §1.9/§3 ; Pipfile vide | Réserver du budget T0 dans l'estimation | 0.65 |

## Sources

- **Brain** : `technical/repos.md`
- **Code** (`resume_matcher_api` @ `main`) : `code/resume_matcher_api/CLAUDE.md` (intégrations
  Sendinblue/Brevo ligne 81, advisory locks Gunicorn ligne 91) ; patterns seed/schéma/claim confirmés
  via les revues spec-tech (app.py, postgres.py, jwt.py, security_incidents.py, assistant/sessions.py,
  loaders/resource.py, migrations/, Pipfile).
- **Feature** : `out/prd.md`, `out/refine.md`, `out/decisions.md`,
  `out/stories/US-1/spec-func.md`, `out/stories/US-1/spec-tech.md`,
  `out/stories/US-1/review-spec-func.md`, `out/stories/US-1/review-spec-tech.md`,
  `out/stories/US-1/review-spec-func-verdict.md`, `out/stories/US-1/review-spec-tech-verdict.md`,
  `docs/dette.md`, `docs/backlog.md`
