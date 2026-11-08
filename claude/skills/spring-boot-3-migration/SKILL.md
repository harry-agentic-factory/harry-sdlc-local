---
name: spring-boot-3-migration
description: WIP — written during a real migration that never reached its end, so no step is known to have been validated on a running service; read it as the best known state of an interrupted job, not as a method. Ordered playbook to migrate a Spring Boot 2.x service (or a multi-module starter SDK) to Spring Boot 3.x — Java 17, javax→jakarta, Spring Security 5→6 (resource server replacing Keycloak adapters), spring.factories→AutoConfiguration.imports, bootstrap.yml→spring.config.import, springfox→springdoc, Spring Batch 4.3→5.0 incl. the batch metadata migrator. Load BEFORE touching any pom.xml of a 2.x→3.x upgrade, or when auditing whether a codebase is ready to migrate.
---

# Spring Boot 2.x → 3.x migration playbook

> **WIP.** Écrit pendant une migration réelle qui n'est **pas** allée à son terme, et dont aucune
> trace n'existe dans un dépôt data. On ne sait donc pas lesquelles de ces étapes ont été éprouvées
> sur un vrai service, ni où le chantier s'est arrêté. À suivre avec cette réserve, et à mettre à
> jour depuis la prochaine migration qui ira au bout.

Grounded in a real migration: the EasyMS SDK (10 starters + 3 sample apps, 167 files changed,
Boot 2.6.2 → 3.1.0) and its config server, plus the official Spring Batch 5.0 and Spring Boot 3
migration guides. Every step below was either paid for in that migration or documented upstream.

## Step 0 — Audit before you touch anything

Run `scripts/audit-sb2-markers.sh <repo-root>`. It greps the codebase for every Boot-2-only
marker (javax imports, `WebSecurityConfigurerAdapter`, `antMatchers`, springfox, `bootstrap.yml`,
auto-configuration entries in `spring.factories`, Keycloak adapters, Spring Batch factories) and
prints a per-module readiness report. Decide the **order of attack** from it:

1. shared libraries / starters first (everything depends on them),
2. security configuration,
3. cloud integrations (vaults, service buses) — watch property-source ordering,
4. applications / samples,
5. one PR per concern. Do not mix "bump versions" with "rewrite security" in one review.

Hard prerequisites: **JDK 17** and **Maven ≥ 3.8.7** (or Gradle 7.5+). Building Boot 3 under an
old JDK fails with plugin errors and **no javac diagnostic at all** — pin the JDK in CI and in
every local build command before interpreting any other failure.

## Step 1 — POM / version matrix

Reference matrix (versions actually used together in the EasyMS migration; take the latest patch
of each line):

| Dependency | Boot 2.x baseline | Boot 3.1 target |
|---|---|---|
| spring-boot-starter-parent | 2.6.2 | 3.1.0 |
| Java | 11 | 17 |
| spring-cloud-dependencies | 2021.0.x | 2022.0.3 |
| spring-boot-admin | 2.x | 3.0.4 |
| springfox / swagger 3.0 | 3.0.0 | **removed** → springdoc-openapi-starter-webmvc-ui 2.1.0 |
| logstash-logback-encoder | 6.x | 7.0.1 |
| javax.inject | 1 | jakarta.inject-api 2.0.1 |
| jacoco | 0.8.4 | 0.8.10 |
| Keycloak adapter jars | any | **removed** → spring-boot-starter-oauth2-resource-server |

Boot 3.2/3.3 targets: bump spring-cloud to 2023.0.x and springdoc to 2.3+; the rest of this
playbook is unchanged.

## Step 2 — javax → jakarta

Mechanical but wide: `javax.persistence`, `javax.validation`, `javax.servlet`,
`javax.transaction`, `javax.inject`, `javax.annotation` → `jakarta.*`. Two traps:
- transitive libraries that still ship `javax.*` servlet/validation APIs (old feign modules,
  swagger annotations) — exclude or upgrade them, never keep both namespaces on the classpath;
- `javax.sql`, `javax.crypto`, `javax.naming` are **JDK** packages and must NOT be renamed.

## Step 3 — Spring Security 5 → 6 (the big one)

`WebSecurityConfigurerAdapter` is gone. Each adapter subclass becomes a `SecurityFilterChain`
bean; multiple chains are split with `securityMatchers`. Mappings:

- `authorizeRequests()` → `authorizeHttpRequests(auth -> ...)`
- `antMatchers(...)` → `requestMatchers(...)`
- actuator chain: `securityMatchers(m -> m.requestMatchers(EndpointRequest.toAnyEndpoint()))`,
  permit `HealthEndpoint`/`InfoEndpoint`, protect the rest (e.g. `hasRole("ACTUATOR")`).
- resource server: `oauth2ResourceServer(s -> s.jwt(j -> j.jwtAuthenticationConverter(converter)))`.
- **Keycloak adapters are dead** (deprecated upstream): replace with the standard OAuth2 resource
  server (`issuer-uri` / `jwk-set-uri`) and a `Converter<Jwt, AbstractAuthenticationToken>` that
  maps token roles to authorities. Decide explicitly which claim you read: `realm_access.roles`,
  `resource_access.<client>.roles`, or both — and null-guard every level of those claims (API
  tokens frequently have no `resource_access` at all).

Real before/after extracted from the EasyMS diff: `references/security-5-to-6.md`.

## Step 4 — Starter auto-configuration registration

`META-INF/spring.factories` no longer registers auto-configurations. For each starter:
- move the `EnableAutoConfiguration` entries to
  `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` (one FQCN
  per line) and annotate the classes with `@AutoConfiguration` instead of plain `@Configuration`;
- `spring.factories` **stays** only for `EnvironmentPostProcessor` and
  `ApplicationContextInitializer` entries.

## Step 5 — Externalized configuration

`bootstrap.yml` is dead (no bootstrap phase by default). Replace with
`spring.config.import: optional:configserver:<url>` in `application.yml`. Gotchas:
- `optional:` keeps the app bootable without the config server; drop it only where the config
  server is a hard dependency;
- set `spring.cloud.config.import-check.enabled: false` if some profiles legitimately run
  without the import;
- anything that must load **after** the config server property sources (vault secrets, …) must
  be an `ApplicationContextInitializer`, not an `EnvironmentPostProcessor` — the config server
  itself contributes via an initializer, and an EnvProcessor runs too early (this produced a
  real deadlock/lost-config bug in EasyMS, fixed by switching to a ContextInitializer).

## Step 6 — OpenAPI: springfox → springdoc

springfox is abandoned and incompatible with Boot 3. Replace with
`springdoc-openapi-starter-webmvc-ui`. UI paths become `/swagger-ui/index.html` + `/v3/api-docs`;
whitelist `/swagger-ui/**`, `/v3/api-docs/**` in the public security chain; re-declare the
OAuth2 authorization flow of the console with springdoc properties (client-id, token URLs).

## Step 7 — Spring Batch 4.3 → 5.0

Four families of breaking changes — details and code in `references/spring-batch-4-to-5.md`:
1. **Builders**: `JobBuilderFactory`/`StepBuilderFactory` are no longer beans → 
   `new JobBuilder("job", jobRepository)`, explicit `PlatformTransactionManager` on every
   `.tasklet(t, tx)` / `.chunk(n, tx)`; `ItemWriter#write(Chunk)` replaces `write(List)`.
2. **Boot interplay**: in Boot 3, `@EnableBatchProcessing` (or extending
   `DefaultBatchConfiguration`) makes Boot's batch auto-configuration **back off** — jobs stop
   being launched at startup. Several `Job` beans → select with `spring.batch.job.name`.
3. **Strongly-typed job parameters**: `JobParameter<T>` is generic, any type is allowed, the
   type is persisted as a fully qualified class name; new CLI notation
   `name=value,type,identifying`.
4. **Metadata persistence model**: `BATCH_JOB_EXECUTION_PARAMS` restructured (4 typed columns →
   name/type/value), `JOB_CONFIGURATION_LOCATION` dropped, `CREATE_TIME` added to
   `BATCH_STEP_EXECUTION`, native sequences on Oracle/MSSQL, Map-based repository removed,
   default execution-context serializer is now Base64 (Jackson optional).

**The metadata of a live system must be migrated with a script, not recreated.** Use the
runbook + SQL migrator in `references/batch-metadata-migration.md`. Golden rule: **finish or
restart every failed v4 job execution BEFORE upgrading** — v5 cannot restart v4 executions.

## Step 8 — Validate like production

- `mvn -T1C clean verify` under JDK 17 (unit + integration tests, not just `test`);
- boot each service against a **real** IdP / config server (a docker-compose with Keycloak and
  an imported realm is the cheapest harness — pattern in the EasyMS secured starter);
- smoke the security matrix: no token → 401/403, wrong role → 403, right role → 200;
- for batch: run one job end-to-end on a **copy** of the production metadata schema migrated
  with the script, and verify restartability of a deliberately failed execution.

## References

- `references/security-5-to-6.md` — real before/after security configs.
- `references/spring-batch-4-to-5.md` — batch code migration, typed parameters.
- `references/batch-metadata-migration.md` — metadata migrator (runbook + SQL).
- `scripts/audit-sb2-markers.sh` — pre-migration audit.
- Official: Spring Boot 3.0 migration guide, Spring Batch 5.0 migration guide
  (github.com/spring-projects/spring-batch/wiki/Spring-Batch-5.0-Migration-Guide),
  Spring Security 6 migration docs.
