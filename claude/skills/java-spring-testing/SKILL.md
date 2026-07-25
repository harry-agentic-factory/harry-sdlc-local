---
name: java-spring-testing
description: >-
  Création, revue et amélioration des tests automatisés en Java / Spring Boot : tests unitaires de service
  (JUnit 5 + Mockito, sans Spring), tests de contrôleur isolés (`@WebMvcTest` + MockMvc + service mocké), tests
  de persistance (`@DataJpaTest` + H2), tests d'intégration complets (`@SpringBootTest` + MockMvc + H2, aucun
  composant applicatif mocké), jeux de données de test (`@Sql`, TestEntityManager, annotations composées),
  profil `test`, et exécution au build (Maven Surefire/Failsafe, Gradle). À charger dès qu'on écrit/relit/corrige
  des tests Spring Boot, qu'on choisit le bon niveau de test, qu'on détecte des tests mal catégorisés/couplés/
  lents, ou qu'on vérifie que les tests obligatoires sont joués au build. **Porte l'outillage de test** de la
  stack java-spring ; les **cas à couvrir** viennent de `rest-best-practices` (contrat) et l'implémentation de
  `spring-boot-api`.
---

# Tests automatisés Java / Spring Boot

Tu portes l'**outillage & la stratégie de test** pour Java/Spring. La **liste des cas** de contrat (nominal, 400,
404, 409, absent-vs-null, idempotence…) vient de `rest-best-practices` ; l'implémentation testée vient de
`spring-boot-api`. Tu privilégies **JUnit 5, Mockito, Spring Boot Test, MockMvc, `@DataJpaTest`, H2, AssertJ**
— **sans imposer** une lib si le projet a déjà une convention cohérente. Tags : **🔴 MUST** / **🟡 SHOULD** /
**🔵 DECISION**.

> Checklist (matrice, annotations, scénarios, anti-patterns, build, datasets) :
> [`references/testing-checklist.md`](references/testing-checklist.md).

## Choix du niveau de test — 🔴 MUST (le cœur du skill)

| Niveau | Composant testé | Spring chargé | Deps mockées | BDD | Annotation type |
|---|---|---|---|---|---|
| **Unitaire service** | classe de service | **non** | **oui** | non | `@ExtendWith(MockitoExtension.class)` |
| **Contrôleur** | contrôleur REST | Web limité | service mocké | non | `@WebMvcTest` + `@MockBean` |
| **Persistance** | repository / mapping JPA | JPA limité | **non** | **H2** | `@DataJpaTest` |
| **Intégration** | chaîne complète | **complet** | **aucune (appli)** | **H2 + données** | `@SpringBootTest` + `@AutoConfigureMockMvc` |

Choisis selon le comportement : règle métier isolée → **unitaire** ; contrat HTTP → **contrôleur** ; requête/
mapping → **@DataJpaTest** ; parcours transverse critique → **intégration**. **Ne charge que le contexte
nécessaire.** Signale : `@SpringBootTest` pour une simple méthode métier (trop lourd) ; service réel dans un test
contrôleur ; repository mocké dans un `@DataJpaTest` ; **composant applicatif mocké dans un test d'intégration**
(mal catégorisé) ; BDD dans un test unitaire ; règle métier testée uniquement en intégration.

## Règles par niveau

### 1. Unitaire de service — 🔴 MUST
Instancie **uniquement** la classe testée, mocke ses dépendances externes, **pas de Spring / serveur / BDD**,
rapide & déterministe. `@Mock` + `@InjectMocks`. **Ne mocke jamais la classe testée.** Évite mocks/stubbings
inutilisés, `verifyNoMoreInteractions` systématique, la recopie de l'algo de prod. `verify` **seulement** pour
les interactions significatives (dont l'**absence** d'appel quand le traitement doit s'arrêter). Teste : nominal,
règles métier, branches, valeurs limites, erreurs fonctionnelles, exceptions, transformations portées par le
service. 🔴 Signale un test qui passe **uniquement** parce que tout est mocké sans vérifier de comportement réel.

### 2. Contrôleur (MockMvc) — 🔴 MUST
`@WebMvcTest(XxxController.class)` + `@MockBean` du service + `MockMvc` + `ObjectMapper`. Charge le **contrôleur
réel** + la config MVC ; **service mocké** ; **pas de persistance**. Teste la couche Web : route/verbe, path vars,
query params, headers, désérialisation body, **validation**, sérialisation réponse, **code HTTP**, **contenu
JSON** (`jsonPath`), gestion des exceptions via le ControllerAdvice. 🔴 Vérifie **réellement la réponse HTTP**,
pas seulement l'appel au service. (Si le projet remplace les beans autrement — ex. `@MockitoBean` récent —
respecte sa convention.)

### 3. ControllerAdvice — 🔴 MUST (via les tests contrôleur)
Teste le mapping exception→HTTP : validation→400, inexistant→404, conflit→409, autorisation→401/403,
inattendue→500, **et le format JSON de l'erreur** (`$.code`, `$.message`…). 🔴 Si **EasyMS** est présent,
recherche & réutilise le mécanisme générique existant — **n'invente pas** de ControllerAdvice sans inspecter.

### 4. Persistance (`@DataJpaTest` + H2) — 🔴 MUST
Charge **uniquement** le contexte JPA (pas de contrôleur/service), **ne mocke pas** le repository testé,
`TestEntityManager` pour préparer des données maîtrisées, vérifie les données **réellement persistées**. Teste :
requêtes dérivées/JPQL/natives (si H2 compatible), contraintes, relations, cascades, mappings, tri/pagination,
converters JPA. **`flush()`** quand le test doit déclencher une contrainte SQL ; tiens compte du **rollback
transactionnel** automatique ; isole les données entre tests. N'ajoute pas de test sans valeur sur du Spring Data
pur. 🔵 **Limites H2** : signale que H2 ≠ moteur de prod (syntaxe SQL, fonctions moteur, types/colonnes, séquences,
index, casse, dates, requêtes natives, isolation). Requête fortement couplée au moteur de prod ⇒ suggère
**Testcontainers**. H2 reste le **défaut** quand le projet l'impose.

### 5. Intégration (`@SpringBootTest` + MockMvc + H2) — 🔴 MUST
Contexte **complet** : contrôleur + service + repository + mappings + ControllerAdvice **réels**, MockMvc pour
appeler l'API, H2 avec données de test, `@ActiveProfiles("test")`. 🔴 **Interdit** (sauf justification
exceptionnelle) : `@Mock`/`@MockBean`/`@SpyBean` sur contrôleurs, services, repositories, mappers, composants
métier. Teste des **parcours transverses critiques** (création→lecture, update, delete, recherche avec/sans
résultat, validation, inexistant, conflit, contraintes, rollback fonctionnel, pagination/filtrage, mapping
exceptions→HTTP, sécurité si dans le périmètre). **Ne redonde pas** les cas déjà couverts en unitaire.

## Données & profil de test — 🟡 SHOULD
**Inspecte le mécanisme existant avant d'en proposer un.** Options : (a) données insérées dans le test
(repository/`TestEntityManager`) pour peu de données propres à un test ; (b) **`@Sql`** avec scripts ciblés
(`/datasets/<contexte>/insert-*.sql` + `delete-*.sql`, BEFORE/AFTER) ; (c) socle minimal `schema.sql`/`data.sql`
— **éviter** une base globale trop partagée ; (d) **annotation composée** (`@WithUsersDataset` méta-annotant
`@Sql`) **uniquement** si elle réduit vraiment la duplication. Profil `test` dédié (`application-test.yml`, H2
mem, `ddl-auto: create-drop`). 🔴 **Isolation** : chaque test doit tourner seul, dans n'importe quel ordre,
plusieurs fois. Bannis : dépendances inter-tests, id créé par un autre test, données résiduelles, dates/valeurs
aléatoires non contrôlées, assertions dépendant de l'ordre. 🔴 Le profil test ne doit **jamais** joindre une base
partagée/prod ni charger des secrets de prod ; services externes neutralisés.

## Build — 🔴 MUST (les tests obligatoires sont joués automatiquement)
**Inspecte** le build (Maven/Gradle) : nommage, plugins, exclusions, profils, phases, séparation UT/IT, CI.
- **Maven** : Surefire (`*Test.java`) pour UT/contrôleur/JPA ; **Failsafe** (`*IT.java`/`*IntegrationTest.java`)
  pour l'intégration aux phases `integration-test`/`verify`. Build de référence = **`mvn clean verify`** (pas
  seulement `mvn test`) si Failsafe est utilisé. N'impose pas cette séparation si une convention cohérente existe.
- **Gradle** : tâche `test`, éventuelle source/tâche `integrationTest`, dépendances de tâches, rattachement à
  `check`/`build`. Le build **échoue** si un test obligatoire échoue.
🔴 Signale : tests exclus silencieusement, IT seulement lançables à la main, profils jamais activés en CI, suites
`@Disabled` sans justification, build vert alors que des tests critiques n'ont pas tourné.

## Nommage & assertions — 🟡 SHOULD
Respecte la convention du projet (Given/When/Then **ou** Arrange/Act/Assert — **pas les deux mélangés**).
Organisation par défaut : `service/`, `controller/`, `repository/`, `integration/`. Noms **comportementaux** :
`shouldReturnUserWhenUserExists`, `shouldRejectRequestWhenEmailIsInvalid` — **pas** `test1`/`testUser`/
`shouldWork`. Assertions **précises** (AssertJ si déjà utilisé) : `assertThat(x.getEmail()).isEqualTo(...)`
plutôt que `isNotNull()` ; collections via `extracting(...).containsExactlyInAnyOrder(...)` ; exceptions via
`assertThatThrownBy(...).isInstanceOf(...).hasMessageContaining(...)`. Bannis : test sans assertion, assertion
trop générale, « ça ne plante pas », dépendance à des détails internes sans valeur, duplication de l'algo de prod.

## Workflow
1. **Inspecter** : Java, deps de test, Maven/Gradle, conventions de nommage, annotations en place, structure des
   tests, base de prod, config H2, profils, scripts de données, EasyMS, CI. Ne propose pas de stratégie avant.
2. **Choisir le niveau** (matrice ci-dessus) pour chaque comportement.
3. **Créer/corriger** : données lisibles, convention de nommage, assertions précises, nominal + erreurs, contexte
   minimal, pas de doublon entre niveaux, isolation, compatibilité build.
4. **Exécuter** (si accès repo+terminal) : `mvn clean verify` ou `./gradlew clean build` ; analyse les échecs,
   corrige si demandé. **Ne déclare jamais des tests valides sans les avoir exécutés** quand c'est possible ;
   sinon signale les tests non joués + la raison.
5. **Restituer** (cf. ci-dessous).

## Format de restitution
**Stratégie retenue** (quels niveaux, pourquoi) · **Tests créés/analysés** (classes) · **Problèmes détectés**
(classés par gravité — niveau de test / données / qualité) · **Corrections proposées** (diffs concrets) ·
**Couverture fonctionnelle** (couvert / à couvrir) · **Résultat du build** (commande, résultat, échecs, limites).

## Exemples de déclenchement
- « Crée les tests unitaires de cette classe de service. »
- « Teste ce contrôleur avec MockMvc en mockant uniquement le service. »
- « Crée un test `@DataJpaTest` de ce repository avec H2. »
- « Crée un test d'intégration de cette API sans mocker les services ni les repositories. »
- « Ajoute un jeu de données H2 avec `@Sql` pour ce parcours. »
- « Analyse la stratégie de tests du projet et détecte les tests mal catégorisés. »
- « Cette classe utilise `@SpringBootTest` — ce niveau de contexte est-il nécessaire ? »
- « Vérifie que tous les tests UT et d'intégration sont joués par Maven au build. »
