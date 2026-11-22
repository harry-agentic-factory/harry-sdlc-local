#!/usr/bin/env bash
# Pre-migration audit: scans a repo for every Spring Boot 2-only marker and prints
# a per-module readiness report. Read-only, no dependency beyond grep/find.
set -euo pipefail

ROOT="${1:-.}"
cd "$ROOT"

# Paths that are not the codebase. Without this the report drowns in build output and in whatever
# scratch directory the repository happens to carry -- measured on a real repo, where a scratchpad
# of saved snippets accounted for a third of the hits and none of the work.
EXCLUDE="${EXCLUDE:-/target/|/\.git/|/node_modules/|/build/|/out/|/scratchpad/|/_toDelete/|/_archive}"

section() { printf '\n== %s ==\n' "$1"; }
filter() { grep -vE "$EXCLUDE" || true; }
hits() { grep -rln --include='*.java' --include='*.xml' --include='*.yml' --include='*.properties' -E "$1" . 2>/dev/null | filter || true; }

section "JDK / parent version"
grep -rn -E "<java.version>|spring-boot-starter-parent" --include=pom.xml . 2>/dev/null | filter || true

section "javax.* imports to migrate (persistence/validation/servlet/transaction/inject/annotation)"
hits '^import javax\.(persistence|validation|servlet|transaction|inject|annotation)'

section "Security 5 markers"
hits 'WebSecurityConfigurerAdapter|EnableGlobalMethodSecurity|antMatchers\(|mvcMatchers\(|authorizeRequests\('

section "Keycloak adapter / legacy spring-security-oauth2 (dead in Boot 3)"
hits 'org\.keycloak\.adapters|keycloak-spring-boot|keycloak-adapter|spring-security-oauth2[^-]'

section "springfox / swagger 2-3 (replace with springdoc)"
hits 'springfox|EnableSwagger'

section "bootstrap.yml (dead bootstrap phase)"
find . -name 'bootstrap.yml' -not -path '*/target/*' || true

section "spring.factories carrying auto-configurations (move to AutoConfiguration.imports)"
grep -rln 'EnableAutoConfiguration' --include='spring.factories' . 2>/dev/null | filter || true

section "Spring Batch 4 markers"
hits 'JobBuilderFactory|StepBuilderFactory|MapJobRepositoryFactoryBean|SimpleJobLauncher|spring\.batch\.job\.names'

section "ItemWriter implementations (write(List) -> write(Chunk))"
hits 'implements ItemWriter|extends .*ItemWriter'

section "Properties renamed in Boot 3 (non-exhaustive quick check)"
hits 'spring\.redis\.|management\.metrics\.export\.|spring\.data\.cassandra\.'

printf '\nDone. Empty sections are ready; each hit above is a migration task.\n'
printf 'Note: this is a text search, so it also flags COMMENTED-OUT code. On a migrated repository\n'
printf 'the residue is usually a dead comment referencing a helper that no longer exists -- delete it\n'
printf 'rather than carrying it, or the next audit reports the same false hit forever.\n'
