---
name: spring-boot-3-migration
description: Migrating a Spring Boot 2 application or SDK to Spring Boot 3 (Java 17, Spring 6, Spring Security 6, Jakarta EE). Load this when a build breaks after bumping the parent, when planning such an upgrade, when javax imports or WebSecurityConfigurerAdapter or springfox or a Keycloak Spring adapter must go, when a starter's auto-configuration stops being picked up, or when an application that CONSUMES a migrated starter no longer compiles. Covers what OpenRewrite does for you, the residue it leaves, the order to attack it in, and the traps that fail at runtime rather than at compile time.
---

# Spring Boot 2 → 3

## Start here: most of it is mechanical, and a tool does it

Run OpenRewrite before touching anything by hand. On the SDK this skill is drawn from, the migration
was **167 files, 4293 insertions, 2102 deletions, 21 commits over four months** — and the majority of
those lines are import rewrites and DSL conversions that a recipe performs in minutes. Telling detail:
the plugin was added in the **very first commit** of that migration, not after a manual attempt.

(OpenRewrite is an open-source refactoring engine, created at Netflix and now stewarded by Moderne. It
parses to a typed syntax tree rather than matching text, which is why it can rewrite a DSL and not only
imports.)

```xml
<plugin>
  <groupId>org.openrewrite.maven</groupId>
  <artifactId>rewrite-maven-plugin</artifactId>
  <version>4.46.0</version>
  <configuration>
    <activeRecipes>
      <!-- The pair actually used on the migration this skill is drawn from. Order matters: the
           language level first, the framework second. Verified inside the jars: rewrite-spring 4.36.0
           declares UpgradeSpringBoot_3_0 and NOT _3_1, so a 3.1+ target needs a newer rewrite-spring.
           List the recipes a version really ships rather than guessing an id:
             unzip -p rewrite-spring-<v>.jar 'META-INF/rewrite/*.yml' | grep -oE 'name: org\.openrewrite\.java\.spring\.boot3\.[A-Za-z_0-9]+' | sort -u -->
      <recipe>org.openrewrite.java.migrate.UpgradeToJava17</recipe>
      <recipe>org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0</recipe>
    </activeRecipes>
  </configuration>
  <dependencies>
    <dependency>
      <groupId>org.openrewrite.recipe</groupId>
      <artifactId>rewrite-spring</artifactId>
      <version>4.36.0</version>
    </dependency>
    <dependency>
      <groupId>org.openrewrite.recipe</groupId>
      <artifactId>rewrite-migrate-java</artifactId>
      <version>1.20.0</version>
    </dependency>
  </dependencies>
</plugin>
```

```bash
mvn rewrite:dryRun     # read the patch first
mvn rewrite:run
```

**What it will not do, and what therefore costs the time**: anything where a library was *abandoned*
rather than renamed (Keycloak Spring adapters, `spring-security-oauth2`, springfox), anything that
depends on your own architecture (which security filter chain, which authorization model), and
everything that fails at **runtime** instead of at compile time. That residue is the rest of this
skill. See `references/openrewrite-recipes.md`.

## The order to attack it in

Working out of order is what turns a two-day migration into a two-week one: each layer hides the next.

1. **Inventory first**, so the size is known before any edit:
   ```bash
   scripts/audit-sb2-markers.sh .
   ```
2. **Parent and dependency set** — Boot `3.1.x`, Java `17`, spring-cloud `2022.0.x`,
   spring-boot-admin `3.x`. Remove the dead artifacts rather than bumping them (`spring-security-oauth2`,
   `javax.annotation-api`, `jaxb-api`). `references/jakarta-and-dependencies.md`.
3. **Remove the version pins that override the parent.** This is the step people skip, and it is the
   one that produces silent regressions: a pin written in 2021 to force a security fix becomes a
   **downgrade** once the new BOM is newer. Measured on a real service: starter, test, log4j and
   domain-library versions all pinned locally, all overriding the new parent.
4. **OpenRewrite**, then read the diff.
5. **The abandoned libraries**, one at a time, deepest first (security adapter, then documentation,
   then anything else).
6. **Compile.** Then the tests. Then boot the thing — see "what fails at runtime" below.
7. **Spring Batch last**, if present, because its metadata schema is the only irreversible part. Its
   **code** migration is recipe-able — `org.openrewrite.java.spring.boot3.SpringBatch4To5Migration`,
   verified present in rewrite-spring 4.36.0 — but its **data** migration is not, and that asymmetry is
   the whole danger. Use the `spring-batch-metadata-migration` skill: Spring ships the new schema and
   its own migration script **destroys** parameter values.

## Spring Security 5 → 6: the whole DSL changes shape

`WebSecurityConfigurerAdapter` is **gone**, and the chained `.and()` DSL is replaced by lambda
configurers. The mechanical part is recipe-able; the architectural part is not.

```java
// Boot 2
@Configuration
class SecurityConfig extends WebSecurityConfigurerAdapter {
    protected void configure(HttpSecurity http) throws Exception {
        http.csrf().disable()
            .sessionManagement().sessionCreationPolicy(STATELESS)
            .and().authorizeRequests().antMatchers("/public/**").permitAll()
            .anyRequest().authenticated();
    }
}

// Boot 3
@Configuration
@EnableWebSecurity
class SecurityConfig {
    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        return http
            .csrf(AbstractHttpConfigurer::disable)
            .sessionManagement(s -> s.sessionCreationPolicy(STATELESS))
            .authorizeHttpRequests(a -> a
                .requestMatchers("/public/**").permitAll()
                .anyRequest().authenticated())
            .build();
    }
}
```

Also gone: `antMatchers` / `mvcMatchers` → `requestMatchers`, `authorizeRequests` →
`authorizeHttpRequests`, `@EnableGlobalMethodSecurity` → `@EnableMethodSecurity`. Details and the
multiple-filter-chain case in `references/security-5-to-6.md`.

**The Keycloak Spring adapters do not exist any more** (deprecated in Keycloak 19, removed in 22).
There is no replacement library: the application becomes a plain OAuth2 resource server, and whatever
the adapter did with roles becomes a `Converter<Jwt, AbstractAuthenticationToken>` you own. Budget for
this as a design task, not a rename — and read `references/security-5-to-6.md` before writing the
converter, because the default one reads only `resource_access` and will 403 every user whose roles are
realm roles.

## Auto-configuration: the starter is loaded differently

For anyone shipping a starter, this is the change that produces "my auto-configuration is simply not
applied", with no error:

```
# Boot 2 — deleted
src/main/resources/META-INF/spring.factories
    org.springframework.boot.autoconfigure.EnableAutoConfiguration=com.acme.AcmeAutoConfiguration

# Boot 3 — one class name per line
src/main/resources/META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports
    com.acme.AcmeAutoConfiguration
```

And `@Configuration` becomes `@AutoConfiguration`, which carries the ordering:
`@AutoConfiguration(before = {Other.class})`.

**The trap, measured**: between two auto-configurations, `@ConditionalOnMissingBean` only sees beans
registered *earlier*. Two starters each defining the same bean "conditionally" produce a
`BeanDefinitionOverrideException` or, worse, the wrong winner — and no unit test catches it, because it
only happens in a full context with both starters present. The fix is explicit ordering
(`@AutoConfigureBefore`), and the only thing that *detects* it is booting a witness application that
consumes both. `references/autoconfiguration-loading.md`.

## What breaks for the CONSUMERS of a migrated starter

Nobody documents this part, and it is where the time goes. A starter's own migration deletes things,
and every application built on it pays:

| What the starter did | What the consumer sees |
|---|---|
| split a package (`…security.oauth2.*` → `…security.common.*`) | `package does not exist`, on imports that were right yesterday |
| deleted its test base class (`AbstractResourceTest`) and its security test extension | every test class fails to compile; the consumer must now own a test base |
| deleted helpers (`SecurityUtils`, `ActuatorSecurityConfig`, `RoutesHandler.antMatchers`) | compile errors in code that merely *used* the starter |
| replaced its JWT plumbing with a converter + properties | the consumer's authorization model has to be re-expressed, and its semantics re-proven |
| stopped forcing a log level | diagnostics that silently depended on it go quiet |

Two consequences worth planning for: **budget a module of your own for the test base class** you used
to inherit, and **freeze the authorization semantics as an executable assertion before migrating** —
the set of permissions a known token yields, asserted in a test, not read in a log. A log line that the
migration removes takes your oracle with it, and the assertion then passes while measuring nothing.

## What fails at runtime, not at compile time

Everything in this section compiles cleanly and breaks when you boot or when a request arrives.

- **`spring.config.import` accumulates.** A command-line `--spring.config.import` does *not* replace
  one activated by a profile; both are honoured. And disabling the config client
  (`spring.cloud.config.enabled=false`) does not help: it unregisters the `configserver:` resolver, so
  the import then fails with "file extension is not known". The clean way out is a dedicated profile
  that mirrors the real configuration with local endpoints.
- **The bootstrap phase is gone.** `spring-cloud-starter-bootstrap` plus a `bootstrap.yml` silently
  stops doing what it did; configuration must move to `spring.config.import`.
- **Hibernate 6 removes the versioned dialects.** `PostgreSQL81Dialect` and friends no longer exist;
  `PostgreSQLDialect` negotiates. And a dialect set as a raw Hibernate property
  (`spring.jpa.properties.hibernate.dialect`) **beats** `spring.jpa.database-platform` in the same
  file — a real production incident came from exactly that.
- **A second `hibernate-core` on the classpath** gives `NoSuchMethodError` on Hibernate internals.
  Look for long-obsolete companions such as `hibernate-java8`, absorbed years ago.
- **QueryDSL needs its `jakarta` classifier** (`querydsl-apt` and `querydsl-jpa`), and the Boot BOM does
  not manage classifier variants, so the version must be explicit. Also: declaring the processor through
  `annotationProcessorPaths` turns **off** classpath discovery, so every processor must be listed there
  — Lombok included, or it silently stops running.
- **Liquibase changelogs carry dialect-isms.** A `BIT(1)` column type written for MySQL is refused by
  recent H2 and has to be stated as `BOOLEAN`, with the checksum of the already-applied changeset
  declared valid. Read the live checksum; do not guess it.
- **springfox is dead**, and under Boot 2.6+ it already failed with a bare NPE in
  `documentationPluginsBootstrapper` unless `spring.mvc.pathmatch.matching-strategy=ant_path_matcher`.
  Replace it with springdoc rather than carrying it: `springfox-boot-starter` →
  `springdoc-openapi-starter-webmvc-ui`, `@ApiOperation(value, notes)` →
  `@Operation(summary, description)`.
- **`ResponseStatusException#getStatus()`** became `getStatusCode()`.

## Prove it, because a green build proves very little here

A migration of this shape changes thousands of lines without changing intended behaviour, so the only
meaningful gate is a **frozen baseline captured before any edit**, replayed after. If the project's CI
does not run tests, a green pipeline means "it packages" and nothing more.

Minimum worth having before starting:
- the application **booting** on a real database with its real migrations, not H2;
- an assertion on the **authorization outcome** of a known token (see above);
- for a starter, a **witness application** that consumes it — the only thing that catches
  auto-configuration ordering;
- for Spring Batch, the proof harness of the `spring-batch-metadata-migration` skill.

## References

- `references/openrewrite-recipes.md` — what the recipes cover, how to read their diff, what they miss.
- `references/jakarta-and-dependencies.md` — which `javax` packages move and which must NOT be touched,
  the artifact swaps, the version pins to delete.
- `references/security-5-to-6.md` — the DSL, multiple filter chains, the entry point, and owning a JWT
  converter after the Keycloak adapters.
- `references/autoconfiguration-loading.md` — `spring.factories` → `AutoConfiguration.imports`,
  `@AutoConfiguration`, ordering, and the conditional-bean trap.
- `scripts/audit-sb2-markers.sh` — inventory of every Boot 2 marker in a repository.
- Spring Batch: the dedicated `spring-batch-metadata-migration` skill. Do not improvise that one; its
  data migration is irreversible and the framework's own script loses data.
