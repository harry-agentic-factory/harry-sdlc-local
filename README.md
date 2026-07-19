# harry-sdlc-local — engine SDLC agentique local « Harry »

**Engine réutilisable, project-agnostic.** Opère sur des repos **data** séparés (`<projet>-sdlc-local`)
qui stockent les tickets (`.md` + `status.json`). Un moteur, plusieurs jeux de données (HIA, Talenteo…).

> PRD / modèle conceptuel : [`docs/PRD.md`](docs/PRD.md). Objectif à terme : migration vers
> `harry-sdlc-ai-factory` (gates→HITL, agents→heavy drivers, `run-ticket`→`TicketWorkflow`).

## Les 4 couches (rappel)
1. **Méthode/lifecycle** · 2. **Mémoire/état** (repo data) · 3. **Chef interactif** (Harry, session) ·
4. **Fleet + orchestration** (agents + Workflow). Agents à contextes **isolés** → mémoire + coordination
**externalisées** (couches 2 & 4), sinon le lifecycle tourne dans le vide.

## Contenu
```
VERSION                    # version d'engine (semver)
install.sh · Makefile      # make install  → symlink dans ~/.claude
claude/
  agents/      reviewer, deployer, recetteur, fixer, e2e-author, nonreg-runner, demo
  commands/    harry, scope, refine, spec-func, spec-tech, ticket
  workflows/   run-ticket.js (gates) · run-ticket-full-auto.js (env d'intégration)
  sdlc/        harry.md (persona)
tooling/
  sdlc/        state-machine, DAG, workspace, board, service, cli, mcp_server, migrations/
  cockpit/     board + Inbox HITL (FastAPI + page)
  tests/       27 tests (déterministe, offline)
docs/PRD.md
```

## Installer / tester
```bash
make install         # symlink claude/* -> ~/.claude ; crée la commande globale `sdlc` (dans un dir du PATH)
make test            # pytest du cœur déterministe
```
`make install` pose une commande **`sdlc`** appelable de partout (dans `/usr/local/bin`, `/opt/homebrew/bin`
ou `~/.local/bin` selon ton PATH). Ensuite :
```bash
sdlc projects                        # projets enregistrés
sdlc --project HIA get HIA-APPS-1     # réhydrate un ticket
sdlc init-project TAL --path … --repos a,b   # nouveau projet
sdlc migrate --project HIA           # migrer la data
```
(Le registre `~/.claude/sdlc/projects.json` mappe `<PREFIX>` → repo data.) Workflows :
`Workflow({scriptPath:'~/.claude/workflows/run-ticket*.js', args:{…}})`.

## Versioning & migration de la data
L'engine est versionné (`VERSION`). Chaque repo data porte `schemaVersion` (dans `sdlc.config.json`).
Un upgrade peut migrer la data : `make migrate PROJECT=HIA` (applique `tooling/sdlc/migrations/`, bumpe
`schemaVersion`). Data git-trackée → un mauvais upgrade se `git revert`. Baseline = `0.1.0` (0 migration).

## Nouveau projet (ex. Talenteo)
1. Créer `talenteo-sdlc-local/` (repo data) avec `sdlc.config.json` (`prefix: TAL`, ses repos, escalation).
2. L'enregistrer dans `~/.claude/sdlc/projects.json`. **L'engine ne change pas.**
