# Spring Security 5 → 6 — real before/after

Taken verbatim (condensed) from a production migration (EasyMS secured starter). This is the
exact shape of the change for every `WebSecurityConfigurerAdapter` subclass.

## Before — Boot 2.6 / Security 5

```java
@Configuration
@EnableWebSecurity
@EnableGlobalMethodSecurity(prePostEnabled = true)
@Order(SecurityProperties.BASIC_AUTH_ORDER)
@AllArgsConstructor
public class WebSecurityConfiguration extends WebSecurityConfigurerAdapter {

    private final CORSFilter corsFilter;
    private final RoutesHandler routesHandler;

    @Override
    public void configure(WebSecurity web) {
        web.ignoring()
                .antMatchers(routesHandler.technicalEndPoints())
                .requestMatchers(routesHandler.publicEndpoints());
    }

    @Override
    public void configure(HttpSecurity http) throws Exception {
        http
            .exceptionHandling().authenticationEntryPoint(new Http403ForbiddenEntryPoint()).and()
            .sessionManagement().sessionCreationPolicy(SessionCreationPolicy.NEVER).and()
            .headers().frameOptions().disable().and()
            .addFilterBefore(corsFilter, ChannelProcessingFilter.class);
    }
}
```

Token handling came from the (now dead) Keycloak adapter or `spring-security-oauth2` 2.x.

## After — Boot 3.1 / Security 6

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity                       // replaces @EnableGlobalMethodSecurity(prePostEnabled=true)
@Order(SecurityProperties.BASIC_AUTH_ORDER)
@RequiredArgsConstructor
public class WebSecurityConfiguration {

    private final CORSFilter corsFilter;
    private final RoutesHandler routesHandler;
    private final JwtAuthConverter jwtAuthConverter;   // Converter<Jwt, AbstractAuthenticationToken>

    @Bean
    WebSecurityCustomizer webSecurityCustomizer() {    // replaces configure(WebSecurity)
        return web -> web.ignoring()
                .requestMatchers(routesHandler.technicalEndPoints())
                .requestMatchers(routesHandler.publicEndpoints());
    }

    @Bean
    SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        return http
            .exceptionHandling(e -> e.authenticationEntryPoint(new Http403ForbiddenEntryPoint()))
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .headers(h -> h.frameOptions(HeadersConfigurer.FrameOptionsConfig::disable))
            .addFilterBefore(corsFilter, ChannelProcessingFilter.class)
            .authorizeHttpRequests(auth -> auth
                    .requestMatchers(HttpMethod.GET, "/actuator/**").permitAll()
                    .requestMatchers(routesHandler.technicalEndPoints()).permitAll()
                    .requestMatchers(routesHandler.publicEndpoints()).permitAll()
                    .anyRequest().authenticated())
            .oauth2ResourceServer(rs -> rs.jwt(jwt -> jwt.jwtAuthenticationConverter(jwtAuthConverter)))
            .httpBasic(Customizer.withDefaults())
            .cors(AbstractHttpConfigurer::disable)
            .csrf(AbstractHttpConfigurer::disable)
            .build();
    }
}
```

## Dedicated actuator chain (second `SecurityFilterChain`)

```java
@Bean
SecurityFilterChain actuatorChain(HttpSecurity http) throws Exception {
    http.securityMatchers(m -> m.requestMatchers(EndpointRequest.toAnyEndpoint()));
    http.authorizeHttpRequests(auth -> auth
            .requestMatchers(EndpointRequest.to(HealthEndpoint.class, InfoEndpoint.class)).permitAll()
            .anyRequest().hasRole("ACTUATOR"));
    http.httpBasic(Customizer.withDefaults());
    return http.build();
}
```

Multiple chains are ordered with `@Order`/`@Bean` ordering and scoped with `securityMatchers`;
the catch-all chain must come last.

## The JWT-to-authorities converter (replacing the Keycloak adapter)

```java
@Component
public class JwtAuthConverter implements Converter<Jwt, AbstractAuthenticationToken> {
    // 1) standard scopes: JwtGrantedAuthoritiesConverter -> SCOPE_xxx
    // 2) client roles:    resource_access.<resource-id>.roles
    // 3) (optional)       realm_access.roles
    // NULL-GUARD EVERY LEVEL: service-to-service tokens often carry no resource_access claim
    // at all, and a converter that dereferences before checking NPEs into a 500 on login.
}
```

Properties (resource server):

```yaml
spring.security.oauth2.resourceserver.jwt:
  issuer-uri: https://idp/realms/myrealm
  jwk-set-uri: ${spring.security.oauth2.resourceserver.jwt.issuer-uri}/protocol/openid-connect/certs
```

## Checklist per adapter subclass

- [ ] class no longer extends anything; `configure(HttpSecurity)` → `SecurityFilterChain` bean
- [ ] `configure(WebSecurity)` → `WebSecurityCustomizer` bean
- [ ] `@EnableGlobalMethodSecurity(prePostEnabled=true)` → `@EnableMethodSecurity`
- [ ] `antMatchers`/`mvcMatchers` → `requestMatchers`
- [ ] `authorizeRequests` → `authorizeHttpRequests`, and-chaining → lambda DSL
- [ ] `SessionCreationPolicy.NEVER` reviewed (resource servers want `STATELESS`)
- [ ] Keycloak adapter deps deleted; resource-server starter + converter wired
- [ ] `hasAuthority`/`hasRole` expressions re-checked against what the converter actually emits
