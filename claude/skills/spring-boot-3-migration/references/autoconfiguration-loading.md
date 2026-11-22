# How a starter is loaded in Boot 3

This is the change that fails **silently**. Nothing throws, nothing logs a warning: the
auto-configuration simply never applies, and the application starts without the behaviour the starter
was supposed to bring.

## The registration file moved

```
# Boot 2 — remove this file
src/main/resources/META-INF/spring.factories

    org.springframework.boot.autoconfigure.EnableAutoConfiguration=\
      com.acme.AcmeAutoConfiguration,\
      com.acme.OtherAutoConfiguration
```

```
# Boot 3 — one fully qualified class name per line, no key, no backslashes
src/main/resources/META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports

    com.acme.AcmeAutoConfiguration
    com.acme.OtherAutoConfiguration
```

The file name is long and exact. A typo in it behaves identically to the file being absent.

Measured on a real SDK: one commit deleted a 3-line `spring.factories` and added the `.imports` file to
**four** starters. `spring.factories` still exists in Boot 3 for other extension points, so its
presence in a repository proves nothing — grep for the `EnableAutoConfiguration` key specifically.

```bash
# anything still registering an auto-configuration the Boot 2 way
grep -rl "EnableAutoConfiguration" --include=spring.factories .
# and every starter that should have the new file
find . -name "*AutoConfiguration.java" -path "*/main/*" | sed 's#/src/main/.*##' | sort -u
```

## `@Configuration` becomes `@AutoConfiguration`

```java
@AutoConfiguration(before = {EasyMsAutoConfiguration.class})
@EnableConfigurationProperties(AcmeProperties.class)
public class AcmeAutoConfiguration { … }
```

`@AutoConfiguration` is `@Configuration(proxyBeanMethods = false)` plus the ordering metadata, and it
carries `before` / `after` directly — the separate `@AutoConfigureBefore` / `@AutoConfigureAfter`
annotations still work and are equivalent.

An auto-configuration class must **not** be picked up by component scanning. If it sits in a package
the application scans, it is applied as an ordinary `@Configuration`, out of order, and all the
conditional logic that assumed auto-configuration timing breaks. Keep it in its own package, outside
the scanned tree.

## The trap: `@ConditionalOnMissingBean` between two auto-configurations

**`@ConditionalOnMissingBean` only sees beans registered earlier.** Within a single configuration class
that is intuitive; across two auto-configurations it depends entirely on the order in which they are
applied, which is unspecified unless you declare it.

Two starters each defining `jwtAuthConverter` "only if absent" give you, depending on order:

- a `BeanDefinitionOverrideException` at startup, or
- worse, **the wrong one wins**, silently, and the application runs with the authorization mapping of
  the starter you meant to override.

Measured: substituting one SDK's JWT converter with a project-specific one produced exactly this, and
it was caught **only** by booting a witness application that consumed both starters. No unit test, no
slice test and no compilation step can see it — the condition is evaluated against a live bean registry.

The fix is to declare the order explicitly:

```java
@AutoConfiguration(before = SdkSecuredAutoConfiguration.class)
public class ProjectSecurityAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean
    Converter<Jwt, AbstractAuthenticationToken> jwtAuthConverter(…) { … }
}
```

And the way to **detect** it is a witness: a minimal application that depends on the starter(s), exposes
one endpoint per behaviour you care about, and is actually started in the build or in a local stack. A
witness is the cheapest test that exists for a starter, and the only one that covers wiring.

## Making a starter substitutable at all

If you ship a starter that others will extend, every bean they might need to replace has to be
`@ConditionalOnMissingBean` — including the ones that look like implementation details. The two that
consumers most often need to override, from experience:

- the **authentication entry point**, because 401-versus-403 is a public contract;
- the **JWT converter / authority mapping**, because the authorization model belongs to the application.

A bean hardcoded in a starter cannot be replaced without forking, and that is discovered at the worst
moment — after the parent bump, when everything else already compiles.

## Checklist for a migrated starter

- [ ] `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports` exists and
      lists every auto-configuration class, one per line;
- [ ] no `EnableAutoConfiguration` key left in any `spring.factories`;
- [ ] `@AutoConfiguration` on those classes, with `before`/`after` where order matters;
- [ ] the auto-configuration package is outside any scanned package;
- [ ] every overridable bean is `@ConditionalOnMissingBean`;
- [ ] a witness application consumes the starter and is **booted** by something automated;
- [ ] the consumer-facing breakages are written down: deleted helpers, moved packages, removed test base
      classes. See the consumer-impact table in `../SKILL.md` — that list is what your users will hit
      first, and it never appears in a release note.
