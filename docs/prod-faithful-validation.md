# Prod-faithful validation — pourquoi un vert H2/mock/slice ne prouve pas la prod

> Capitalisation de bugs **prod-only** réellement vécus, **généralisés** en règles réutilisables (tout
> projet Spring/JPA/Postgres). À lire par `fixer`, `reviewer`, `deployer` et tout run en `loop-engineering`.
> Principe : **une classe entière de bugs n'apparaît QUE dans les conditions de prod** — même moteur DB,
> **dialecte réel**, **vrai changelog**, **boot complet du contexte**. Les tests H2/mock/slice les **masquent**.

## Règle d'or
Ajouter aux **must-run gates** (build/CI) **deux** garde-fous, en plus des tests unitaires/slices :
1. un **IT PostgreSQL iso-prod** (Testcontainers) : **vrai `db.changelog.xml`** + **dialecte réel** +
   **écriture `jsonb`** ;
2. un **smoke context-load** (`@SpringBootTest` qui charge le contexte complet).

Un vert H2 / mock / `@DataJpaTest` **ne prouve pas** la prod. Dette de référence : *« test migration/context
iso-prod en CI (Testcontainers) »*.

## Les pièges prod-only (chacun vécu)

### 1. Le dialecte Hibernate **effectif** peut différer du moteur DB réel
En prod, la datasource peut être **PostgreSQL** alors que la config force `hibernate.dialect=MySQLDialect`
(héritage, copier-coller de config). Conséquence : **toute logique branchée sur le NOM du dialecte** (ou sur
un comportement spécifique au dialecte supposé) est un **piège** — elle raisonne sur un dialecte qui n'est pas
celui du moteur réel.
- **Détection** : review — chercher toute lecture du dialecte / branche conditionnelle dessus.
- **Prévention** : ne jamais dépendre du nom du dialecte ; valider le SQL généré sur le **vrai moteur**.

### 2. `jsonb` en écriture échoue sans `stringtype=unspecified`
Une colonne `columnDefinition = "jsonb"` mappée en `String` : l'**écriture** échoue avec **SQLState 42804**
(`column is of type jsonb but expression is of type character varying`) — **sauf** si la datasource a
`stringtype=unspecified` (JDBC URL Postgres). H2 ne reproduit pas : il accepte, donc **masque** le bug.
- **Prévention** : tester l'**écriture** `jsonb` sur **vrai Postgres** ; vérifier `stringtype=unspecified`
  sur la datasource prod ; ou mapper via un type/converter dédié.

### 3. Liquibase : `<dbms>` est un **attribut/preCondition**, jamais un enfant de `<changeSet>`
`<dbms type="postgresql"/>` placé comme **élément enfant** de `<changeSet>` est ignoré/invalide selon le
parseur ; la bonne forme est l'**attribut** `dbms="postgresql"` sur le `<changeSet>` **ou** une
`<preConditions>`. Le **jumeau H2** d'un changelog (changelog de test réécrit pour H2) **masque** les erreurs
du changelog **de prod**.
- **Prévention** : valider le **vrai `db.changelog.xml`** (celui de prod) sur **Postgres** (Testcontainers),
  pas un changelog H2-only.

### 4. Filtre optionnel JPQL `(:x is null OR e.f = :x)` → 42P18 sur Postgres
Sous `stringtype=unspecified`, Postgres ne peut pas inférer le type du paramètre lié dans `(:x is null …)` et
lève **42P18** (`could not determine data type of parameter`). H2 tolère.
- **Prévention** : `cast(:x as string) is null` (adapter le type au paramètre) pour tout **filtre optionnel**
  de ce genre.

### 5. Échecs au **BOOT** (non attrapés par les slices)
`@Value` avec placeholder **circulaire/non résolu**, wiring de bean impossible, `@Scheduled` mal câblé,
`@ConfigurationProperties` manquant : le contexte **ne démarre pas** en prod. Une slice `@DataJpaTest` /
`@WebMvcTest` ne charge **pas** le contexte complet → **ne les attrape pas**.
- **Prévention** : un **`@SpringBootTest` context-load** (démarre le contexte entier, aucun bean mocké) =
  smoke qui attrape tout échec de boot avant le déploiement.

## Où ça se branche dans le loop
- **fixer** : reproduit/valide **iso-prod** (voir agent) — pas seulement H2/mock.
- **reviewer** : checklist « pièges prod-only » sur le diff (voir agent).
- **deployer** : **smokes adversariaux** post-deploy (boot, migration, flux critique).
- **CI/build** : IT PostgreSQL iso-prod (Testcontainers) + smoke context-load en **must-run gates**.

## Références croisées
- `docs/loop-engineering.md` / skill `loop-engineering` — invariant « validation iso-prod ».
- `claude/skills/java-spring-testing/SKILL.md` — niveaux de test (`@SpringBootTest` vs slices).
- `claude/agents/{fixer,reviewer,deployer}.md` — application par agent.
