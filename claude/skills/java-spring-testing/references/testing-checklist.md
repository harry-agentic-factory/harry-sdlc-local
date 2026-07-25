# Checklist tests Java / Spring Boot

Grille de création & revue. Tags : **🔴 MUST** / **🟡 SHOULD** / **🔵 DECISION**. Les **cas de contrat** à couvrir
viennent de `rest-best-practices` ; l'implémentation testée de `spring-boot-api`.

## Matrice des niveaux
| Niveau | Composant | Spring | Deps mockées | BDD | Annotation |
|---|---|---|---|---|---|
| Unitaire service | service | non | oui | non | `@ExtendWith(MockitoExtension.class)`, `@Mock`, `@InjectMocks` |
| Contrôleur | contrôleur REST | Web limité | service mocké | non | `@WebMvcTest`, `@MockBean`, `MockMvc` |
| Persistance | repository / mapping | JPA limité | non | H2 | `@DataJpaTest`, `TestEntityManager` |
| Intégration | chaîne complète | complet | aucune (appli) | H2 + données | `@SpringBootTest`, `@AutoConfigureMockMvc`, `@ActiveProfiles("test")` |

## Annotations recommandées
- Unitaire : `@ExtendWith(MockitoExtension.class)` · `@Mock` · `@InjectMocks` · (AssertJ `assertThat`).
- Contrôleur : `@WebMvcTest(XxxController.class)` · `@MockBean` (ou convention projet) · `MockMvc` · `ObjectMapper`.
- Persistance : `@DataJpaTest` · `TestEntityManager` · `@Sql` (si datasets) · `flush()` pour les contraintes.
- Intégration : `@SpringBootTest` · `@AutoConfigureMockMvc` · `@ActiveProfiles("test")` · `@Sql` (datasets).

## Scénarios à couvrir
### Service (unitaire)
- [ ] Nominal · règles métier · branches importantes · valeurs limites.
- [ ] Erreurs fonctionnelles · exceptions levées.
- [ ] Interactions significatives (`verify`) · **absence** d'appel quand le traitement s'arrête.
- [ ] Transformations de données portées par le service.

### Contrôleur (MockMvc)
- [ ] Nominal · body valide · body invalide · champ obligatoire absent · format incorrect.
- [ ] Path variable invalide · request param invalide · ressource inexistante · exception métier.
- [ ] Code HTTP **et** contenu JSON (`jsonPath`) · format d'erreur · sécurité si contrôleur sécurisé.

### ControllerAdvice
- [ ] validation→400 · inexistant→404 · conflit→409 · autorisation→401/403 · inattendue→500.
- [ ] Format JSON de l'erreur (`$.code`, `$.message`…).
- [ ] 🔴 EasyMS présent ⇒ mécanisme existant réutilisé, pas recréé.

### Persistance (@DataJpaTest)
- [ ] Requêtes dérivées · JPQL · natives (si H2 compatible).
- [ ] Contraintes (`flush()` pour les déclencher) · relations · cascades · mappings · converters.
- [ ] Tri & pagination · données réellement persistées vérifiées.

### Intégration (@SpringBootTest)
- [ ] Création→lecture · update · delete.
- [ ] Recherche avec / sans résultat · validation · inexistant · conflit métier.
- [ ] Contraintes de persistance · rollback fonctionnel · pagination/filtrage · mapping exceptions→HTTP.
- [ ] Sécurité si dans le périmètre · **pas** de redite des cas unitaires.

## Anti-patterns à signaler
### Niveau de test
- [ ] 🔴 `@SpringBootTest` pour un simple test unitaire.
- [ ] 🔴 Service réel dans un test de contrôleur isolé.
- [ ] 🔴 Repository mocké dans un `@DataJpaTest`.
- [ ] 🔴 Composant applicatif mocké dans un test d'intégration.
- [ ] 🔴 BDD utilisée dans un test unitaire.
- [ ] 🟡 Logique métier testée uniquement en intégration.

### Données
- [ ] 🔴 Tests dépendants les uns des autres · id créé par un autre test.
- [ ] 🔴 Données communes modifiées par plusieurs tests · scripts SQL non nettoyés · données résiduelles.
- [ ] 🔴 Ordre d'exécution obligatoire · usage accidentel d'une base externe.
- [ ] 🟡 Données de test peu lisibles · SQL globaux difficiles à comprendre.

### Qualité
- [ ] 🔴 Absence d'assertion · test qui vérifie seulement « ça ne plante pas ».
- [ ] 🔴 Assertion uniquement sur le code HTTP sans vérifier le body.
- [ ] 🔴 Test « intégration » qui mocke l'essentiel de la chaîne.
- [ ] 🔴 Test de repository qui ne déclenche jamais le `flush()` nécessaire.
- [ ] 🟡 `@Disabled` sans justification · mocks inutiles · couplage à l'implémentation · duplication · lenteur.
- [ ] 🟡 Assertions trop générales (`isNotNull` seul) · duplication de l'algo de prod.
- [ ] 🟡 Noms vagues (`test1`, `testUser`, `shouldWork`, `nominalCase`).

## Profil de test
- [ ] 🟡 Profil `test` dédié (`application-test.yml`), H2 mem, `ddl-auto: create-drop`.
- [ ] 🔴 Aucune base partagée/prod joignable ; secrets de prod non chargés ; services externes neutralisés.
- [ ] 🟡 Schéma/migrations gérés de façon cohérente ; profil activé quand nécessaire.

## Build
### Maven
- [ ] Surefire pour `*Test.java` (UT/contrôleur/JPA).
- [ ] Failsafe pour `*IT.java`/`*IntegrationTest.java` (phases `integration-test`/`verify`).
- [ ] Build de référence = `mvn clean verify` si Failsafe utilisé.
- [ ] 🔴 N'impose pas la séparation si une convention cohérente existe.

### Gradle
- [ ] Tâche `test` · éventuelle source/tâche `integrationTest` · rattachée à `check`/`build`.
- [ ] 🔴 Build **échoue** si un test obligatoire échoue.

### Général — à signaler
- [ ] 🔴 Tests exclus silencieusement · IT seulement manuels · profils jamais activés en CI.
- [ ] 🔴 Suites `@Disabled` non justifiées · build vert alors que des tests critiques n'ont pas tourné.

## Jeux de données
- [ ] 🟡 Mécanisme existant inspecté avant d'en proposer un nouveau.
- [ ] 🟡 `@Sql` ciblés (`/datasets/<contexte>/insert-*.sql` + `delete-*.sql`, BEFORE/AFTER).
- [ ] 🟡 Scripts lisibles, ciblés, déterministes, maintenables, séparés par contexte fonctionnel.
- [ ] 🔵 Annotation composée (`@WithXxxDataset`) seulement si elle réduit vraiment la duplication.
- [ ] 🔴 Isolation : test seul / n'importe quel ordre / plusieurs fois / build complet.
