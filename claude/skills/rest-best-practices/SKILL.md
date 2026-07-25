---
name: rest-best-practices
description: >-
  Bonnes pratiques de conception d'API REST **indépendantes du langage/framework** : URLs versionnées &
  nommage des ressources, stabilité du contrat / breaking changes, path variable vs request parameter,
  sémantique des verbes HTTP, sémantique PATCH (absent vs null vs défaut vs inchangé), DTO comme contrat
  public (nommage & clarté), codes HTTP, format d'erreur homogène, pagination/tri/filtrage, documentation
  OpenAPI, sécurité de contrat (mass assignment, autorisation ≠ validation, pas de fuite). À charger dès
  qu'on conçoit/analyse/refactorise une API REST ou qu'on relit une PR/spec OpenAPI qui expose ou modifie une
  API — quel que soit le langage. Pour l'implémentation Java/Spring, se combine avec `spring-boot-api`
  (le « comment ») ; ce skill porte le « quoi » et le « pourquoi ».
---

# Bonnes pratiques API REST (agnostique du langage)

Ce skill porte les règles de **design de contrat REST**, valables quel que soit le langage. L'implémentation
concrète (annotations, validation, gestion d'erreurs, framework de test) est portée par des skills dédiés —
p. ex. `spring-boot-api` pour Java/Spring. **Charge-les en complément** quand la stack le justifie.

Tu es un relecteur **opinionated**. Tu tags toujours : **🔴 MUST** (bloquant) / **🟡 SHOULD** (recommandation) /
**🔵 DECISION** (arbitrage fonctionnel — tu proposes, tu ne tranches pas seul). Tu distingues une **préférence
de style** d'une vraie **rupture de contrat**. Tu ne sur-conçois pas et n'imposes pas le CRUD si une autre
modélisation est meilleure.

> Checklist exhaustive : [`references/rest-checklist.md`](references/rest-checklist.md).

## Méthode
1. **Comprendre** — ressources métier, consommateurs, opérations, règles métier, contraintes de compat.
2. **Inspecter l'existant AVANT de proposer** — routes, contrat des DTO, format d'erreur, conventions du projet.
3. **Analyser / concevoir** — URLs, verbes, path vs query, contrat DTO, codes HTTP, erreurs, pagination, doc,
   sécurité de contrat.
4. **Restituer** : **Résumé → 🔴 Bloquants → 🟡 Corrections → 🔵 Décisions/Recommandations → Proposition
   corrigée → Tests de contrat à ajouter**.

## Règles

### 1. URLs & versioning — 🔴 MUST
`/api/v{n}/{ressources}` : préfixe `/api`, version **dans l'URL**, **noms de ressources** (pas de verbe métier),
**minuscules**, **kebab-case**, **pluriel** pour les collections. URLs & ressources **stables** dans le temps.
```
✅ GET /api/v1/users   GET /api/v1/payment-methods/{paymentMethodId}   POST /api/v1/users
❌ /getUsers   /api/user   /api/v1/paymentMethods   /api/v1/get-payment-methods   /api/v1/createUser
```

### 2. Stabilité du contrat — 🔴 MUST
Une ressource = un contrat exposé. Signale explicitement tout **breaking change** : suppression/renommage de
champ, changement de type, obligatoire↔facultatif, sémantique d'un champ, code HTTP, déplacement de ressource,
structure de réponse, règle de pagination/filtrage. Rupture nécessaire ⇒ **nouvelle version majeure**.

### 3. Path variable vs request parameter — 🔴 MUST
- **Path** : identifie une ressource/sous-ressource précise (absence ⇒ **404**). `/users/{userId}/addresses`.
- **Query** : recherche, filtre, tri, pagination, vue, critère facultatif. `/users?status=active&page=0`.
- Recherche **sans résultat** ⇒ **200** + collection vide (**jamais 404**). Aucun paramètre placé
  arbitrairement dans le body/path/query.

### 4. Verbes HTTP — 🔴 MUST
| Verbe | Usage | Réponse |
|-------|-------|---------|
| GET | lire (aucun effet de bord) | 200 |
| POST | créer / opération métier non-CRUD | 201 (+ body créé et/ou header `Location`) |
| PUT | remplacement **complet**, **idempotent** | 200/204 |
| PATCH | mise à jour **partielle** | 200/204 |
| DELETE | supprimer, idempotent sur l'état final | 204 |

Évite les endpoints **RPC** si la ressource est modélisable REST. PUT dont beaucoup de champs facultatifs sont
ignorés quand absents = en réalité un PATCH.

### 5. PATCH — absent vs null — 🔴 MUST / 🔵 DECISION
Lève toute ambiguïté entre : champ **absent**, champ explicitement **null**, champ à **valeur par défaut**,
champ **inchangé**. **Ne déduis jamais une intention métier de la seule présence de null.** Un flag métier
explicite `{"applyDefaults": true}` est préférable à une déduction fragile.
🔵 Si le defaulting / la mise à jour partielle touche une **part importante** de l'objet (≳ 20 % des champs),
**remets en cause le design du DTO** : DTO de commande dédié, DTO de patch explicitement typé (présence),
indicateurs explicites, opération métier dédiée, séparation en plusieurs ressources, ou représentation complète
en PUT.

### 6. DTO = contrat public — 🟡 SHOULD (🔴 sécurité)
Noms **explicites & métier**, unités claires, booléens qui expriment un état, dates/montants/statuts/ids non
ambigus. Sépare **création / modification / réponse** quand les responsabilités diffèrent. La représentation
exposée est **distincte du modèle de persistance** (le « comment » côté framework — ex. ne pas exposer les
entités JPA — est dans `spring-boot-api`), mais **évite les divergences gratuites** entre couches.
```
❌ value  data  flag  type  statusCode  date  amount  info      (sans contexte)
✅ paymentStatus  createdAt  expirationDate  amountInCents  currencyCode  isDefaultPaymentMethod
```

### 7. Codes HTTP — 🔴 MUST
200 lecture · 201 création · 204 sans contenu · 400 entrée invalide · 401 non-authentifié · 403 non-autorisé ·
404 inexistant · 409 conflit d'état/unicité · 415 media type · 422 validation sémantique (si convention projet) ·
500 erreur interne **inattendue**. Jamais 200 fourre-tout ; jamais 500 pour une erreur fonctionnelle connue ;
jamais 404 pour une collection vide ; **401 ≠ 403** ; pas de détail interne sur 500.

### 8. Format d'erreur — 🟡 SHOULD (stable, documenté, exploitable, sans fuite)
```json
{ "timestamp":"2026-07-25T10:15:30Z", "status":400, "code":"VALIDATION_ERROR",
  "message":"The request contains invalid fields.", "path":"/api/v1/users",
  "fieldErrors":[{"field":"email","code":"INVALID_EMAIL","message":"The email address is invalid."}],
  "correlationId":"4d9b9e65-5128-4d84-91df-c16ff2a48272" }
```
Suit la convention du projet si elle existe (ne recrée pas un format concurrent).

### 9. Pagination / tri / filtrage — 🟡 SHOULD
Collections potentiellement grandes ⇒ pagination. `?page=0&size=20&sort=created-at,desc`. Vérifie : taille
**max** bornée, valeurs par défaut explicites, tri stable, doc des params, protection contre les requêtes
coûteuses, format de réponse paginée cohérent avec l'existant.

### 10. OpenAPI / documentation — 🟡 SHOULD
Documente ressource, opérations, params, contraintes, formats, exemples, codes HTTP possibles, modèle d'erreur,
champs obligatoires, distinction DTO requête vs réponse. Compréhensible sans connaître l'implémentation.

### 11. Sécurité de contrat — 🔴 MUST
Pas d'ids/données sensibles inutiles exposés. **Mass assignment** : n'accepte pas aveuglément des champs
techniques (rôles, statuts internes, `owner`…). Autorisation au bon niveau ; **validation ≠ autorisation**.
Filtre les données retournées selon les droits. Jamais de stack trace / SQL / détail interne exposé. Jamais de
secret / token / donnée personnelle sensible journalisé.

## Tests de contrat attendus — 🟡 SHOULD (outillage = skill de test de la stack)
Cas nominal · champ obligatoire absent · format invalide (400) · ressource inexistante (404) · conflit (409) ·
droits (401/403) · format d'erreur · mise à jour partielle & **absent vs null** · idempotence PUT/DELETE ·
pagination & filtres · limites de taille. L'**outillage** de test (framework, harness) est porté par le skill de
test de la stack (ex. `spring-boot-testing`).

## Format de restitution (revue)
**Résumé** · **🔴 Bloquants** (rupture de contrat, mauvais code HTTP, faille de contrat) · **🟡 Corrections** ·
**🔵 Recommandations/Décisions** · **Proposition corrigée** (routes/contrat) · **Tests de contrat à ajouter**.

## Exemples de déclenchement
- « Relis cette spec OpenAPI et liste les erreurs de design. »
- « Conçois les endpoints REST pour gérer les moyens de paiement d'un utilisateur. »
- « Transforme ce contrôleur RPC en API REST orientée ressources. »
- « Ce PATCH distingue-t-il correctement un champ absent d'un champ à null ? »
- « Quels codes HTTP pour cette création avec conflit d'unicité ? »
