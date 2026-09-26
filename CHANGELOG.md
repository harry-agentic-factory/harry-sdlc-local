# Changelog

All notable changes to this engine are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the engine uses
[Semantic Versioning](https://semver.org/). The `VERSION` file is the single source of the version; a
release section header is exactly `## [X.Y.Z] - YYYY-MM-DD` (its body is the text of the GitHub Release).

## [Unreleased]

### Added

- Persona rule « Écrire un document vivant » (`claude/sdlc/harry.md`): optimistic locking for sessions and
  sub-agents writing a living document of the data repository (`git hash-object` on read, re-check before
  writing, Edit/Write only, `conflict` block on divergence); the 15 commands and agents that write such a
  document point to it (AISDLC-RUNWS-13).

### Changed

- Local rendering of a round into `<STORY>/<type>.md` is a compare-and-swap: re-read just before the atomic
  rename, redone on the latest bytes if the file changed underneath (at most 3 times), then `put_conflict`
  with the run left replayable (AISDLC-RUNWS-13).
- `run-ticket` (off mode): the prompts that write a living document remind the rule, and a result with
  `conflict` stops the workflow with `doc_conflict` and the observed `status_now`, without transition. Run
  workspace mode is unchanged (AISDLC-RUNWS-13).

## [0.7.0] - 2026-09-26

### Added

- Run workspace of an autonomous agent: `sdlc run init/finish/clean/list`, `sdlc doc read/list/add` and the
  `sdlc.runws` library API (AISDLC-RUNWS-1).
- Code runs: `sdlc clone`, `run-ticket.js` in run workspace mode and the per-project `runWorkspace` flag
  (opt-in, absent means unchanged behaviour) (AISDLC-RUNWS-2).
- Brain tooling: `sdlc brain normalize|lint|snapshot|diff|history`, the `brainRef` manifest key and the
  `sdlc.brain` library API (AISDLC-RUNWS-10).
- Packaging and release: the `harry-sdlc` Python package (no dependency, `py.typed`), `sdlc --version`
  (`X.Y.Z (release)` or `X.Y.Z-dev+<sha>[.dirty] (dev: <path>)`), installation on a git tag under
  `HARRY_SDLC_HOME` with an atomic `current` link, the `ci` and `release` GitHub workflows and the release
  scripts (`scripts/`) (AISDLC-RUNWS-3).

### Changed

- `install.sh` requires an argument: a release tag `vX.Y.Z` or `--dev <path>`; every link it manages goes
  through `HARRY_SDLC_HOME/current`. `make install` is the dev mode on the current copy.

### Fixed

- `engine_version()` reports the exact version once packaged (it silently returned `0.1.0` outside a
  working copy).
- `run-ticket` deploys through the project manifest (PR #53).
- Brain links: nothing is extracted inside fenced code blocks (```` ``` ```` / `~~~`) any more; inline code
  is still scanned (AISDLC-RUNWS-10).
