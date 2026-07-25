# Checklist API REST Spring Boot (implémentation)

Grille du « comment » Spring. À croiser avec [`rest-checklist.md`](../../rest-best-practices/references/rest-checklist.md)
(le « quoi » / contrat). Tags : **🔴 MUST** / **🟡 SHOULD** / **🔵 DECISION**.

## A. Contrôleur & routing
- [ ] 🔴 `@RestController` + `@RequestMapping("/api/v{n}/…")`.
- [ ] 🔴 Une annotation par verbe (`@GetMapping`/`@PostMapping`/`@PutMapping`/`@PatchMapping`/`@DeleteMapping`).
- [ ] 🔴 `@PathVariable` = identité ; `@RequestParam` = recherche/filtre/tri/pagination.
- [ ] 🔴 Contrôleur mince : délègue au service, pas de règle métier dedans.

## B. Codes HTTP & réponses
- [ ] 🔴 `ResponseEntity<T>` pour maîtriser le statut.
- [ ] 🔴 Création ⇒ 201 + header `Location`.
- [ ] 🔴 Suppression ⇒ 204 (`noContent()`).
- [ ] 🟡 Pas de `ResponseStatusException` en remplacement d'un mapping centralisé.

## C. DTO & JPA
- [ ] 🔴 Aucune entité JPA exposée directement.
- [ ] 🔴 DTO requête/réponse distincts via converter/mapper.
- [ ] 🟡 Séparation contrat/domaine/persistance sans divergence gratuite.
- [ ] 🔴 PATCH : type distinguant absent vs null (Optional/JsonNullable/DTO patch dédié).
- [ ] 🔴 Pas de mass assignment (`role`/`status` interne/`owner` non acceptés en entrée).

## D. Validation
- [ ] 🔴 Bean Validation sur les DTO (`@NotNull @NotBlank @Size @Min @Max @Positive @Email @Pattern`).
- [ ] 🔴 `@Valid` sur le body ; `@Validated` (classe) pour path/query.
- [ ] 🔴 `@Valid` récursif sur les objets imbriqués.
- [ ] 🔴 Entrée invalide ⇒ 400 (via ControllerAdvice).
- [ ] 🔴 Règles métier complexes dans le service, pas dans le contrôleur.

## E. Exceptions
- [ ] 🔴 `@RestControllerAdvice` + `@ExceptionHandler` centralisés (souvent `extends ResponseEntityExceptionHandler`).
- [ ] 🔴 Pas de cascade `try/catch` de traduction HTTP dans les contrôleurs.
- [ ] 🔴 Aucune stack trace / SQL / classe interne renvoyée.
- [ ] 🟡 Format d'erreur homogène (cf. rest-best-practices).
- [ ] 🔴 Logs utiles sans donnée sensible.

## F. Pagination
- [ ] 🟡 `Pageable`/`Page<>`/`Sort` (ou format standardisé du projet).
- [ ] 🟡 Taille max bornée, défauts explicites, tri stable.

## G. OpenAPI
- [ ] 🟡 springdoc (`@Operation`/`@Schema`/`@ApiResponse`) ou outil du projet.
- [ ] 🟡 Params, contraintes, exemples, codes, modèle d'erreur, DTO req/rép.

## H. Sécurité
- [ ] 🔴 Autorisation au bon niveau (`@PreAuthorize`/filtre projet) ; validation ≠ autorisation.
- [ ] 🔴 Données retournées filtrées selon les droits.
- [ ] 🔴 Aucun secret journalisé/exposé.

## I. EasyMS (si présent)
- [ ] 🔴 Composants du socle recherchés AVANT toute nouvelle implémentation.
- [ ] 🔴 Validation / ControllerAdvice / format d'erreur EasyMS réutilisés, pas dupliqués.
- [ ] 🔴 Noms de classes EasyMS vérifiés dans le repo (jamais inventés).
- [ ] 🟡 Incohérences avec le socle signalées.

## J. Tests (délégué à java-spring-testing)
- [ ] 🟡 Outillage = `java-spring-testing` (MockMvc/@WebMvcTest/@SpringBootTest, ControllerAdvice, validation).
- [ ] 🟡 Cas à couvrir = rest-best-practices §Tests de contrat.
