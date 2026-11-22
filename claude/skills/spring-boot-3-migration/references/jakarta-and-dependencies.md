# Jakarta, and the dependency set

## Which `javax` packages move — and which must NOT be touched

This is the single most common way to turn a mechanical step into a day of confusion. Jakarta EE
renamed the **enterprise** packages; the JDK ones keep their `javax` name forever.

| Rename | Leave alone (JDK) |
|---|---|
| `javax.persistence` → `jakarta.persistence` | `javax.sql` (`DataSource`) |
| `javax.servlet` → `jakarta.servlet` | `javax.net`, `javax.net.ssl` |
| `javax.validation` → `jakarta.validation` | `javax.imageio` |
| `javax.annotation` → `jakarta.annotation` (`@PostConstruct`, `@PreDestroy`) | `javax.xml.*` |
| `javax.transaction` → `jakarta.transaction` | `javax.security.auth.*` |
| `javax.mail` → `jakarta.mail` | `javax.crypto` |
| `javax.inject` → `jakarta.inject` | `javax.management` |
| `javax.ws.rs` → `jakarta.ws.rs` | `javax.naming` |

Measured on a real service: 102 files rewritten across 6 moved packages (servlet 76 occurrences,
persistence 67, validation 16, annotation 8, mail 6, transaction 1), and **5 `javax` packages left
untouched** on purpose (`javax.sql` 18, `javax.net` 3, `javax.security` 2, `javax.xml` 1,
`javax.imageio` 1). A blanket `sed 's/javax/jakarta/'` would have broken all five.

If you rewrite by script rather than by recipe, make the script print what it left behind and assert
that everything remaining is a JDK package. "No `javax` left" is the wrong goal.

## Artifact swaps

| Out | In |
|---|---|
| `springfox-boot-starter` | `springdoc-openapi-starter-webmvc-ui` |
| `spring-security-oauth2` (`org.springframework.security.oauth`) | nothing — the project is gone, use the resource-server support in Spring Security |
| `javax.annotation:javax.annotation-api` | nothing — `jakarta.annotation-api` comes with the starters |
| `javax.xml.bind:jaxb-api` | `jakarta.xml.bind:jakarta.xml.bind-api` |
| `javax.inject:javax.inject` | `jakarta.inject:jakarta.inject-api` |
| Keycloak Spring adapters (`keycloak-spring-boot-starter`, `keycloak-spring-security-adapter`) | nothing — see `security-5-to-6.md` |
| `hibernate-java8` | nothing — absorbed into `hibernate-core` years ago, and keeping it drags a **second** `hibernate-core` onto the classpath, which fails at runtime with `NoSuchMethodError` on Hibernate internals |

## Version floors

| | Boot 2 era | Boot 3.1 |
|---|---|---|
| Java | 11 | **17** |
| Spring Framework | 5.3 | 6.0 |
| Spring Security | 5.x | 6.x |
| spring-cloud | 2021.0.x | **2022.0.x** |
| spring-boot-admin | 2.x | **3.x** |
| Hibernate | 5.x | 6.2 |
| QueryDSL | 4.x | 5.x **with the `jakarta` classifier** |
| ShedLock | 4.x (last Java 8 line) | 5.x (needs Java 17) |
| Apache POI, commons-* | unchanged, but check transitives | — |

## Delete the pins that override the parent

The step most often skipped, and the one that causes silent regressions rather than build failures.

A version pinned in a service's own `pom.xml` **beats** the parent's BOM. Pins accumulate for good
reasons — forcing a security fix, working around a bug — and each becomes a lie once the parent moves.
Measured on one service: the starter, the test library, `log4j-core`/`log4j-api` and a shared domain
library were all pinned locally. The log4j pin, written in 2021 to force a fix, would have **downgraded**
log4j under the new BOM.

```bash
# every version declared in the module itself, to be justified one by one
grep -nE "<version>" pom.xml
```

Keep a pin only with a written reason, and prefer `dependencyManagement` in the parent over a pin in a
leaf. Two cases genuinely need one: an artifact with a **classifier** (the BOM does not manage
classifier variants, hence an explicit `${querydsl.version}`), and a mediation fix where a transitive
resolves too low (for example POI 5.2.5 needing `commons-io` ≥ 2.15 while another dependency pulls 2.4).

## QueryDSL, specifically

```xml
<dependency>
  <groupId>com.querydsl</groupId>
  <artifactId>querydsl-jpa</artifactId>
  <version>${querydsl.version}</version>
  <classifier>jakarta</classifier>
</dependency>
```

And the processor moves to the compiler plugin, because the old `apt-maven-plugin` carries the
**pre-jakarta** `JPAAnnotationProcessor` and dies with `NoClassDefFoundError: javax/persistence/Entity`:

```xml
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-compiler-plugin</artifactId>
  <configuration>
    <annotationProcessorPaths>
      <path>
        <groupId>com.querydsl</groupId><artifactId>querydsl-apt</artifactId>
        <version>${querydsl.version}</version><classifier>jakarta</classifier>
      </path>
      <path>
        <groupId>jakarta.persistence</groupId><artifactId>jakarta.persistence-api</artifactId>
        <version>${jakarta-persistence.version}</version>
      </path>
      <path>
        <groupId>org.projectlombok</groupId><artifactId>lombok</artifactId>
        <version>${lombok.version}</version>
      </path>
    </annotationProcessorPaths>
  </configuration>
</plugin>
```

Two traps in that block:

1. **Naming the processor path disables classpath discovery.** Everything the build needs as a
   processor must be listed, **Lombok included** — leave it out and it silently stops running, which
   surfaces as hundreds of "cannot find symbol" on generated getters.
2. **Generated Q-classes committed into `src/main/java`** make QueryDSL 5 fail with "Attempt to
   recreate a file for type". Check for them: a repository can easily hold stale generated classes for
   old entities and none for the recent ones. Archive and remove them, then count what the build
   generates.

## Hibernate 6

- the **versioned dialects are gone**: `PostgreSQL81Dialect`, `MySQL5Dialect` and friends →
  `PostgreSQLDialect`, `MySQLDialect`, which negotiate the server version;
- a dialect set as a raw Hibernate property (`spring.jpa.properties.hibernate.dialect`) is passed
  **verbatim** and beats `spring.jpa.database-platform` in the same file. A production incident came
  from exactly that: a MySQL dialect over PostgreSQL, which rendered every offset page as
  `LIMIT <offset>,<count>` and returned 500 from page 1 onwards while page 0 worked — so it hid for
  years;
- `BIT(1)` in a Liquibase changelog is a MySQL-ism recent H2 refuses; state `BOOLEAN` and declare the
  already-applied changeset's checksum valid, **read from the live database**, never guessed.
