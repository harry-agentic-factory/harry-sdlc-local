# Checklist REST (agnostique du langage)

Grille de revue de **contrat**. Tags : **🔴 MUST** / **🟡 SHOULD** / **🔵 DECISION**. L'implémentation (annotations,
validation, gestion d'erreurs, tests) est couverte par le skill de la stack (ex. `spring-boot-api`,
`spring-boot-testing`).

## A. URLs & routing
- [ ] 🔴 Préfixe `/api`.
- [ ] 🔴 Version dans l'URL (`/v1`…), pas dans un header ni implicite.
- [ ] 🔴 Noms de ressources (substantifs), pas de verbe métier.
- [ ] 🔴 Minuscules + kebab-case ; pluriel pour les collections.
- [ ] 🟡 Imbrication ≤ 2 niveaux (au-delà, interroger).
- [ ] 🔴 Pas de renommage/déplacement de ressource sans version majeure.

## B. Verbes & sémantique
- [ ] 🔴 GET = lecture pure, aucun effet de bord.
- [ ] 🔴 POST création ⇒ 201 + body et/ou `Location`.
- [ ] 🔴 PUT = remplacement complet, idempotent (pas de PATCH déguisé).
- [ ] 🔴 PATCH = partiel explicite.
- [ ] 🔴 DELETE idempotent ⇒ 204 (ou convention projet).
- [ ] 🟡 RPC justifié seulement si non modélisable en ressource.

## C. Path vs query
- [ ] 🔴 Path ⇔ identifie une ressource (absence ⇒ 404).
- [ ] 🔴 Recherche/filtre/tri/pagination/vue ⇒ query param.
- [ ] 🔴 Recherche sans résultat ⇒ 200 + collection vide.
- [ ] 🔴 Aucun paramètre arbitraire dans le body.

## D. Contrat DTO
- [ ] 🟡 Noms explicites & métier (pas `value`/`data`/`flag`/`info`).
- [ ] 🟡 Unités explicites, `currencyCode`, dates non ambiguës.
- [ ] 🟡 Booléens = état/question (`isDefaultPaymentMethod`).
- [ ] 🟡 DTO création / modif / réponse séparés si responsabilités différentes.
- [ ] 🟡 Représentation exposée distincte du modèle de persistance, sans divergence gratuite.
- [ ] 🔴 Pas de mass assignment (champs techniques non acceptés aveuglément).

## E. PATCH — absent vs null
- [ ] 🔴 absent ≠ null ≠ défaut ≠ inchangé, distinction claire.
- [ ] 🔴 Aucune intention métier déduite du null seul.
- [ ] 🔵 Flag métier explicite préféré à la déduction.
- [ ] 🔵 Defaulting/partiel > ~20 % des champs ⇒ remettre en cause le DTO.

## F. Codes HTTP
- [ ] 🔴 200/201/204 selon l'opération.
- [ ] 🔴 400/401/403 (401 ≠ 403) / 404 / 409.
- [ ] 🟡 415 / 422 (si convention).
- [ ] 🔴 500 = interne inattendue seulement ; collection vide ≠ 404.

## G. Erreurs
- [ ] 🟡 Format homogène (timestamp/status/code/message/path/fieldErrors/correlationId), convention projet.
- [ ] 🔴 Aucune fuite (stack trace / SQL / interne) au client.

## H. Pagination
- [ ] 🟡 Pagination sur grandes collections ; taille max bornée ; défauts explicites.
- [ ] 🟡 Tri stable & documenté ; format paginé cohérent avec l'existant.

## I. OpenAPI
- [ ] 🟡 Ressource, opérations, params, contraintes, exemples, codes, modèle d'erreur.
- [ ] 🟡 Champs obligatoires ; DTO requête vs réponse distincts.

## J. Sécurité de contrat
- [ ] 🔴 Pas d'ids/données sensibles inutiles exposés.
- [ ] 🔴 Autorisation au bon niveau (≠ validation) ; données filtrées selon les droits.
- [ ] 🔴 Aucun secret/token/donnée perso journalisé ou renvoyé.

## K. Tests de contrat (outillage = skill de test de la stack)
- [ ] 🟡 Nominal · obligatoire absent · format invalide (400).
- [ ] 🟡 404 · 409 · droits (401/403).
- [ ] 🟡 Format d'erreur · partiel + absent-vs-null.
- [ ] 🟡 Idempotence PUT/DELETE · pagination/filtres/limites.
