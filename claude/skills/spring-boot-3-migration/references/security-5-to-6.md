# Spring Security 5 → 6, and life after the Keycloak adapters

Two different jobs live in this file. The **DSL** change is syntax, and a recipe does it. The
**authorization model** change is design, and it is where a migration silently breaks production.

## The DSL

`WebSecurityConfigurerAdapter` is removed. A configuration class exposes one or more
`SecurityFilterChain` beans instead, and every configurer is a lambda — the chained `.and()` style is
gone.

```java
// Boot 2
@Configuration
class SecurityConfig extends WebSecurityConfigurerAdapter {
    @Override protected void configure(HttpSecurity http) throws Exception {
        http.csrf().disable()
            .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.STATELESS)
            .and().authorizeRequests()
                .antMatchers("/api/apps/v1/**").permitAll()
                .anyRequest().authenticated()
            .and().httpBasic().authenticationEntryPoint(entryPoint());
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
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(a -> a
                .requestMatchers("/api/apps/v1/**").permitAll()
                .anyRequest().authenticated())
            .httpBasic(b -> b.authenticationEntryPoint(entryPoint()))
            .exceptionHandling(e -> e.authenticationEntryPoint(entryPoint()))
            .build();
    }
}
```

The renames: `authorizeRequests` → `authorizeHttpRequests`, `antMatchers`/`mvcMatchers` →
`requestMatchers`, `@EnableGlobalMethodSecurity` → `@EnableMethodSecurity`,
`WebSecurityConfigurerAdapter` → a `SecurityFilterChain` bean. `AbstractHttpConfigurer::disable` is the
idiomatic way to write a bare `.disable()`.

**Where the conversion goes wrong**: the scoping of a chained `.and()`. Reading which matchers belonged
to which block in the old fluent form is genuinely ambiguous, and a recipe resolves it one way. After
conversion, **compare the resulting matcher set by hand** — a permitted path that becomes authenticated
(or the reverse) compiles perfectly.

Helpers that disappeared with the adapter are worth noting because consumers used them: an
`antMatchers(String...)` convenience on a routes-handler interface has no equivalent, since
`AntPathRequestMatcher` is now built directly.

## Several filter chains

Multiple chains are supported and ordered by `@Order`; the **first matching** chain wins and the others
never see the request. Give every chain but the last an explicit `securityMatcher`, or the first one
swallows everything.

```java
@Bean @Order(1)
SecurityFilterChain publicChain(HttpSecurity http) throws Exception {
    return http.securityMatcher("/api/apps/v1/**")
               .authorizeHttpRequests(a -> a.anyRequest().permitAll())
               .csrf(AbstractHttpConfigurer::disable)
               .build();
}

@Bean @Order(2)
SecurityFilterChain securedChain(HttpSecurity http) throws Exception {
    return http.authorizeHttpRequests(a -> a.anyRequest().authenticated())
               .oauth2ResourceServer(o -> o.jwt(j -> j.jwtAuthenticationConverter(converter)))
               .build();
}
```

This is the shape to use when a Boot 2 codebase had a `WebSecurityConfigurerAdapter` subclass "with an
exception for one public endpoint": that pattern becomes two chains, not one chain with a permitAll.

## The Keycloak Spring adapters are gone

Deprecated in Keycloak 19, **removed in 22**. There is no successor library. The application becomes a
plain OAuth2 resource server:

```yaml
spring:
  security:
    oauth2:
      resourceserver:
        jwt:
          issuer-uri: https://kc.example/realms/my-realm
          jwk-set-uri: https://kc.example/realms/my-realm/protocol/openid-connect/certs
```

What the adapter used to do silently, and that you now own:

| The adapter did | You now write |
|---|---|
| mapped Keycloak roles to Spring authorities | a `Converter<Jwt, AbstractAuthenticationToken>` |
| provided a principal from the token | the principal attribute, explicitly (`preferred_username`, falling back to `sub`) |
| configured the entry point (401 vs 403) | an `AuthenticationEntryPoint` bean |
| exposed `SimpleKeycloakAccount` / `KeycloakPrincipal` | `JwtAuthenticationToken`, and `getToken().getTokenValue()` for the raw token |
| `KeycloakRestTemplate` / adapter-aware Feign | a Feign interceptor reading the token from the `JwtAuthenticationToken` |

### The converter trap that 403s every user

A Keycloak access token carries roles in **two independent places**:

```json
{
  "realm_access":   { "roles": ["HIA_ADMIN_CLIENT"] },
  "resource_access": { "my-client": { "roles": ["reader"] } }
}
```

`realm_access.roles` are **realm** roles, global to the realm. `resource_access.<clientId>.roles` are
**client** roles, scoped to one OIDC client. Most published converters — including the one shipped by
more than one SDK — read **only** `resource_access`. If your users' roles are realm roles, that
converter grants nothing and the application answers **403 to everyone**, with a perfectly healthy
startup.

Measured before migrating, on a real platform: every front-end and service-account client carried
**realm** roles only, and one service account carried no role at all (its authorization came from
custom claims). Reading `resource_access` alone would have locked out the entire platform.

So, before writing or adopting a converter, **look at a real token** from the real identity provider:

```bash
# the claims of a token actually minted by the platform
curl -s -X POST "$ISSUER/protocol/openid-connect/token" -d grant_type=password \
     -d client_id=… -d username=… --data-urlencode "password=@-" < /dev/null \
  | jq -r .access_token | cut -d. -f2 | base64 -d 2>/dev/null | jq '{realm_access, resource_access}'
```

Then read both, with the client id as a property so the behaviour is explicit:

```java
public AbstractAuthenticationToken convert(Jwt jwt) {
    Set<String> roles = new LinkedHashSet<>(realmRoles(jwt));   // realm_access.roles
    roles.addAll(clientRoles(jwt));                             // resource_access.<id>.roles, if configured
    List<GrantedAuthority> authorities = mapping.permissionsFor(roles).stream()
            .map(SimpleGrantedAuthority::new).map(GrantedAuthority.class::cast).toList();
    return new JwtAuthenticationToken(jwt, authorities, principalOf(jwt));
}
```

Null-guard **every** claim level: `realm_access` absent, `roles` absent, `resource_access` present but
without your client. A service-account token legitimately has none of them.

### Keep the status codes you had

An adapter that answered **401** on an anonymous call and an SDK default of
`Http403ForbiddenEntryPoint` are not the same contract, and clients notice. Decide explicitly:

```java
@Bean
@ConditionalOnMissingBean
AuthenticationEntryPoint authenticationEntryPoint() {
    return new HttpStatusEntryPoint(HttpStatus.UNAUTHORIZED);
}
```

### Freeze the authorization semantics before you migrate

The permissions a known token yields are the one thing a compiler cannot check. Assert them as a test,
on a realistic token, **before** removing the old layer:

```java
assertThat(converter.convert(tokenWithRealmRoles("HIA_ADMIN_CLIENT", "HIA_PLATFORM_ADMIN"))
        .getAuthorities()).extracting(GrantedAuthority::getAuthority)
        .containsExactlyInAnyOrder("PERM_GET_CLIENT", "PERM_MODIFY_CLIENT", /* … */);
```

And beware of an oracle that reads a **log line** emitted by the layer you are replacing: once removed,
it prints nothing, the assertion sees an empty set and — depending on how it is written — passes. An
oracle must fail when deprived of its source; check that it does.

## Other removals you will meet

- `spring-security-oauth2` (the old `org.springframework.security.oauth` project) and its
  `@EnableResourceServer`: gone, no equivalent, delete the annotation.
- `org.springframework.security.jwt.{Jwt,JwtHelper}`: gone with it. `JwtHelper.decode(token)` did **not**
  verify the signature, so the faithful replacement is `JWTParser.parse(token).getJWTClaimsSet()`
  (Nimbus) — same semantics, same absence of verification. Say so in a comment, or the next reader will
  "fix" it into a verifying parse.
- `UnauthorizedClientException` and the other legacy OAuth2 exceptions: if an exception handler mapped
  them, the mapping is now dead code — check what status the path actually returns today before
  assuming it was a 401.
