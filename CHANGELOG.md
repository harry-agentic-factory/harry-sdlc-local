# Changelog

All notable changes to this engine are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the engine uses
[Semantic Versioning](https://semver.org/). The `VERSION` file is the single source of the version; a
release section header is exactly `## [X.Y.Z] - YYYY-MM-DD` (its body is the text of the GitHub Release).

## [Unreleased]

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
