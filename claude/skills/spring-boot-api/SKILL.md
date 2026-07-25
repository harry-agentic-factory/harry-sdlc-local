---
name: spring-boot-api
description: >-
  Implémentation & revue d'API REST **en Spring Boot (Java)** : contrôleurs `@RestController`/`*Resource`,
  mapping des routes (`@GetMapping`/`@PostMapping`… `@PathVariable` vs `@RequestParam`), DTO (séparation avec
  les entités JPA), validation Bean Validation (`@Valid`/`@Validated`), gestion d'erreurs centralisée
  (`@RestControllerAdvice`/`@ExceptionHandler`, `ResponseStatusException`), codes HTTP via `ResponseEntity`,
  pagination Spring (`Pageable`/`Page`), doc OpenAPI (springdoc), et intégration du socle **EasyMS** quand il
  est présent. À charger dès qu'on écrit/relit un contrôleur Spring Boot, qu'on crée/revoit des DTO, qu'on
  câble la validation/les exceptions, ou qu'on relit une PR Spring qui expose/modifie une API. **Se combine
  avec `rest-best-practices`** (règles de design agnostiques) : ce skill porte le « comment » Spring, pas les
  règles de contrat elles-mêmes.
---

# API REST en Spring Boot (le « comment »)

Ce skill traduit les règles de [`rest-best-practices`](../rest-best-practices/SKILL.md) en **implémentation
Spring Boot**. **Charge d'abord `rest-best-practices`** pour le QUOI/POURQUOI (URLs, verbes, codes HTTP, contrat
DTO, format d'erreur, sécurité de contrat, PATCH absent-vs-null) — ici on ne les répète pas, on montre comment
les réaliser en Spring et on signale les pièges spécifiques. Tags : **🔴 MUST** / **🟡 SHOULD** / **🔵 DECISION**.

> Checklist Spring : [`references/spring-boot-api-checklist.md`](references/spring-boot-api-checklist.md).

## Méthode
1. **Inspecter l'existant AVANT de proposer** — contrôleurs `*Resource`/`*Controller`, DTO/converters,
   exceptions, `@RestControllerAdvice`, conventions de validation, doc OpenAPI, tests, et le socle **EasyMS**
   (cf. §EasyMS). Lis le `CLAUDE.md` du repo. Ne propose pas une archi neuve avant d'avoir lu les conventions.
2. **Réaliser / relire** le contrôleur à l'aune de `rest-best-practices` + des règles Spring ci-dessous.
3. **Restituer** comme `rest-best-practices` (Résumé → 🔴 → 🟡 → 🔵 → Proposition corrigée → Tests).

## Règles Spring

### 1. Contrôleur & routes — 🔴 MUST
`@RestController` + `@RequestMapping("/api/v1/…")`. Un verbe = une annotation (`@GetMapping`, `@PostMapping`,
`@PutMapping`, `@PatchMapping`, `@DeleteMapping`). **`@PathVariable`** pour l'identité de ressource,
**`@RequestParam`** pour recherche/filtre/tri/pagination (cf. `rest-best-practices` §3). Le contrôleur reste
**mince** : il délègue au service, ne porte pas la règle métier.

### 2. Codes HTTP & réponses — 🔴 MUST
`ResponseEntity<T>` pour maîtriser le statut. Création ⇒ `201` + `Location` (`ServletUriComponentsBuilder` /
`created(uri)`). Suppression ⇒ `204` (`noContent()`). N'utilise pas `ResponseStatusException` pour masquer une
absence de mapping centralisé (cf. §4). Respecte les codes de `rest-best-practices` §7.

### 3. DTO & entités JPA — 🔴 MUST
**N'expose jamais une entité JPA** directement (cycles de sérialisation, lazy-loading, fuite du schéma). DTO
distincts requête/réponse via un `converter`/mapper. Garde la séparation **contrat / domaine / persistance**
tout en évitant les divergences gratuites (cf. `rest-best-practices` §6). Pour PATCH partiel, utilise un type qui
distingue **absent vs null** (ex. wrappers `Optional`/`JsonNullable`, ou DTO de patch dédié) — ne déduis pas
l'intention du null (cf. `rest-best-practices` §5).

### 4. Validation — 🔴 MUST
Bean Validation : `@NotNull @NotBlank @Size @Min @Max @Positive @Email @Pattern` sur les DTO ; `@Valid` sur le
body du contrôleur, `@Validated` sur la classe pour valider path/query params ; `@Valid` **récursif** sur les
objets imbriqués. Entrée invalide ⇒ **400** (via le ControllerAdvice, cf. §5). **Règles métier complexes dans
le service**, pas dans le contrôleur.

### 5. Exceptions centralisées — 🔴 MUST
Mapping exception → HTTP dans un **`@RestControllerAdvice`** (`@ExceptionHandler`, souvent
`extends ResponseEntityExceptionHandler` pour les erreurs de validation Spring). **Pas** de cascade `try/catch`
de traduction HTTP dans les contrôleurs. Exceptions métier explicites, jamais avalées ; **aucune stack trace /
message SQL / nom de classe interne** renvoyé au client ; format d'erreur homogène (cf. `rest-best-practices`
§8) ; logs utiles sans donnée sensible.

### 6. Pagination — 🟡 SHOULD
Utilise l'abstraction Spring (`Pageable`, `Page<T>`, `Sort`) ou le format déjà standardisé du projet. Borne la
**taille max** de page, défauts explicites, tri stable (cf. `rest-best-practices` §9).

### 7. OpenAPI — 🟡 SHOULD
Documente via springdoc (`@Operation`, `@Schema`, `@ApiResponse`) ou l'outil du projet : opérations, params,
contraintes, exemples, codes, modèle d'erreur, DTO req/rép.

### 8. Sécurité — 🔴 MUST
Autorisation au bon niveau (`@PreAuthorize`/filtre selon le projet — voir la dette RBAC du repo si elle
existe) ; **validation ≠ autorisation** ; pas de mass assignment (n'accepte pas `role`/`status` interne/`owner`
en entrée) ; filtre les données retournées selon les droits ; aucun secret journalisé (cf. `rest-best-practices`
§11).

## Intégration EasyMS — 🔴 MUST (ne rien inventer)
Beaucoup de projets Harington utilisent le socle **EasyMS** (ex. `com.easyms:easyms-secured-rest-starter`,
`com.easyms.rest.ms.rest.Validator`, un `RestExceptionHandler`/ControllerAdvice du projet, un modèle `ApiError`,
des exceptions comme `UnprocessedEntityException`). **Ces noms sont des indices — vérifie-les dans le repo, ne
les présume pas.** Quand EasyMS est présent :
1. **cherche** les implémentations existantes (validation, gestion d'erreurs, ControllerAdvice, format d'erreur) ;
2. **réutilise** les composants génériques plutôt que d'en recréer ;
3. **inspire-toi** des contrôleurs / exceptions / validations déjà en place ;
4. **évite** les implémentations parallèles ; signale toute incohérence avec le socle.
Ne recrée **pas** un mécanisme fourni par EasyMS. Un skill EasyMS dédié pourra étendre ce point ; ici on reste
sur les **règles d'intégration générales**.

## Tests — délégué
L'outillage de test Spring (MockMvc, `@WebMvcTest`, `@SpringBootTest`, tests de ControllerAdvice/validation,
contrat OpenAPI) est porté par le skill **`java-spring-testing`** (à charger si présent). La **liste des cas** à
couvrir vient de `rest-best-practices` §Tests de contrat.

## Exemples de déclenchement
- « Analyse ce contrôleur Spring Boot et vérifie qu'il respecte nos bonnes pratiques REST. »
- « Propose le `@RestControllerAdvice` et les exceptions nécessaires en réutilisant les composants EasyMS. »
- « Vérifie les DTO, la validation et les codes HTTP de cette PR Spring. »
- « Ce PATCH Spring distingue-t-il un champ absent d'un champ à null ? »
- « Câble la validation Bean Validation + 400 sur ce endpoint. »
