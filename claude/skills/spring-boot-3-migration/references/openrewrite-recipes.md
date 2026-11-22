# OpenRewrite on a Boot 2 → 3 migration: what it does, and where it stops

OpenRewrite parses the code to a **typed syntax tree** and applies recipes to it, which is why it can
convert a fluent DSL and not merely rename imports. It was created at Netflix and is now stewarded by
Moderne; the Spring and Java recipes live in `rewrite-spring` and `rewrite-migrate-java`.

## The configuration that was actually used

Measured on the SDK this skill is drawn from — added in the **first commit** of the migration, before
any manual attempt:

```xml
<plugin>
  <groupId>org.openrewrite.maven</groupId>
  <artifactId>rewrite-maven-plugin</artifactId>
  <version>4.46.0</version>
  <configuration>
    <activeRecipes>
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

Order matters: the language level first, the framework second. All three artifacts resolve from **Maven
Central** (verified), and the recipe ids are declared in YAML **inside the jars** — so list what a
version actually ships instead of trusting a recipe id from a blog post:

```bash
unzip -p ~/.m2/repository/org/openrewrite/recipe/rewrite-spring/4.36.0/rewrite-spring-4.36.0.jar \
    'META-INF/rewrite/*.yml' \
  | grep -oE 'name: org\.openrewrite\.java\.spring\.boot3\.[A-Za-z_0-9]+' | sort -u
```

On 4.36.0 that prints eight Boot 3 recipes, and the useful fact is which one is **missing**:
`UpgradeSpringBoot_3_0` is there, `_3_1` is **not**. Targeting 3.1 with this version silently gives you
the 3.0 migration, so a 3.1+ target needs a newer `rewrite-spring`.

Also shipped in 4.36.0, and worth knowing before hand-writing it:
`org.openrewrite.java.spring.boot3.SpringBatch4To5Migration`,
`SpringBootProperties_3_0_0` (property renames), `MavenPomUpgrade`,
`ActuatorEndpointSanitization`, `MigrateThymeleafDependencies`.

```bash
mvn rewrite:dryRun     # writes a patch under target/rewrite/ -- READ IT
mvn rewrite:run        # applies it
```

`dryRun` first, always. The patch is the only place you will see, in one view, everything the recipe
decided — and a recipe that touches 150 files is not something to discover commit by commit.

## What it reliably handles

- `javax.*` → `jakarta.*` **on the packages that actually moved**, leaving the JDK ones alone. Doing
  this with `sed` is how people break `javax.sql`, `javax.net` and `javax.imageio`.
- the Spring Security lambda DSL: `.csrf().disable().and().authorizeRequests()` →
  `.csrf(AbstractHttpConfigurer::disable).authorizeHttpRequests(a -> …)`;
- `antMatchers`/`mvcMatchers` → `requestMatchers`, `authorizeRequests` → `authorizeHttpRequests`,
  `@EnableGlobalMethodSecurity` → `@EnableMethodSecurity`;
- `WebSecurityConfigurerAdapter` subclasses → a `SecurityFilterChain` bean, in the simple single-chain
  case;
- property renames in `application.yml` (`spring.redis.*` → `spring.data.redis.*`,
  `management.metrics.export.*` → `management.<registry>.metrics.export.*`);
- Java language modernisation (text blocks, `instanceof` patterns, `List.of`) via the Java 17 recipe —
  cosmetic, and worth a separate commit so it does not drown the real diff.

## Where it stops, and why

| Not handled | Why |
|---|---|
| Keycloak Spring adapters | the library was **abandoned**, not renamed. There is no target to rewrite to: the application becomes a resource server and you own the authorization mapping. |
| `spring-security-oauth2` (the old project) | removed, not replaced. Its annotations (`@EnableResourceServer`) have no equivalent. |
| springfox → springdoc | different API and different annotations; a recipe exists for parts of it but the OpenAPI annotations and config classes need judgement. |
| multiple filter chains | ordering and matcher scoping are architecture, not syntax. |
| `spring.factories` → `AutoConfiguration.imports` | partially handled; verify, because a miss produces **no error**, just an auto-configuration that never applies. |
| anything in a changelog, a Dockerfile, a Helm chart, a CI file | out of scope by construction, and a migration touches all of them. |
| Spring Batch **metadata** | `SpringBatch4To5Migration` handles the **code** (builders, typed parameters). The **data** migration is not, and cannot be, a recipe: the schema change collapses four typed columns into one and the framework's own SQL script drops them without moving the values. Code green, history destroyed. |

## Reading the patch: three things to look for

1. **Did it touch a `javax` package it should not have?** Grep the patch for `javax.sql`, `javax.net`,
   `javax.imageio`, `javax.xml`, `javax.security.auth` — those are JDK and must stay.
2. **Did a security chain lose a matcher?** The lambda conversion is mechanical but the *scoping* of a
   chained `.and()` is easy to misread; compare the resulting `requestMatchers` set by hand.
3. **Did it bump something you pinned on purpose?** A pin that existed for a reason (a CVE fix, a
   dialect quirk) is just a version to a recipe.

## The honest expectation

Think of it as doing the volume, not the migration. On the measured case, the recipe accounts for most
of the 4293 inserted lines, and the remaining twenty-odd commits — spread over four months — are the
abandoned libraries, the security architecture, the auto-configuration wiring, and the runtime failures
that no compiler catches. Plan the schedule around that residue, not around the recipe.
