# Changelog

All notable changes to this engine are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the engine uses
[Semantic Versioning](https://semver.org/). The `VERSION` file is the single source of the version; a
release section header is exactly `## [X.Y.Z] - YYYY-MM-DD` (its body is the text of the GitHub Release).

## [Unreleased]

## [0.8.1] - 2026-10-01

### Changed

- Persona rule « Écrire pour un humain » (`claude/sdlc/harry.md`, AISDLC-POASSIST-22): every message to the human is
  written in sentences — no arrows as a writing device, no front-matter fields or internal values, no file paths, no
  command names; documents named by their title, finding counts in words, end-of-turn recap of at most 5 lines, never
  about the tooling, register by profile (PO/BA product language; techlead/dev/solo may add technical detail, still in
  sentences), « tu » by default. Includes a before/after reference example. File formats are unchanged.
- The `Sortie` sections of `/scope`, `/refine`, `/spec-func`, `/spec-tech`, `/validate-spec-func`,
  `/validate-spec-tech`, `/validate-feature` and `/process-review` follow that rule (paths and the `sdlc validate-…`
  command only for the techlead/dev/solo profiles, on request); profile switches are no longer announced.

## [0.8.0] - 2026-10-01

### Added

- Gate model « the agent recommends, the human decides » (AISDLC-POASSIST-2): slash commands
  `/validate-spec-func`, `/validate-spec-tech`, `/validate-feature` and `/process-review`. A gate is an agent review
  (`review-spec-func.md`, `review-spec-tech.md`, `review-feature.md`: numbered `B`/`M`/`m`/`S` findings with
  evidence, recommendation and consensus; a targeted re-review is a new version) and a human verdict
  (`review-<gate>-verdict.md`, `draft` until the human signs it, outcome `validated | validated_with_reserves |
  returned | bypassed`), processed point by point and resumable by `/process-review`.
- `harry-archi` review document mode.
- `sdlc validate-feature <EPIC>` and the `feature_validated` status between `spec_validated` and `implemented`
  (skippable, like the other gates): one verdict per role (`po`, `techlead`), the stories move only when both are
  signed.
- `sdlc validate-spec-func|validate-spec-tech|validate-feature --verdict <path>`: the verdict is checked (signed,
  human signer, every finding decided, matching gate, target and review version), then the gate writes a journal
  entry with `git hash-object` refs of the review and the verdict, links them (`review_spec_func`,
  `review_spec_func_verdict`, …) and turns `reserve`/`bypassed` decisions into idempotent `pm` debt items, only when
  the stories move. Optional `gates.signers` allow-list in `sdlc.config.json`. Refusals carry a stable `code`.
- `sdlc status`: `awaiting` hints for the spec gates and a `gates` field with the linked gate documents.
- Routed returns `spec_validated | feature_validated → spec_tech | spec_func` (`sdlc reject`).

### Changed

- **BREAKING** — `validate-func` and `validate-spec` are renamed `validate-spec-func` and `validate-spec-tech`;
  the old names (plus `validate-tech`, `validate-epic`) stay as aliases but, like the new names, **refuse** the
  transition without `--verdict` pointing to a verdict signed by a human (`--review` alone is no longer enough). The
  output `gate` is now `spec_func | spec_tech | feature` (the `validated` key is kept, equal to `advanced`).
- `/spec-func`, `/spec-tech`, `/full-spec`, `/run-story`, the persona, the `loop-engineering` skill and doc and the
  README describe the new gates; `/run-story` runs unattended from `feature_validated` and stops at each gate
  signature.
- Feature gate, role verdicts (AISDLC-POASSIST-14): when `review-feature.md` has a `Rôle` column, each role verdict
  (`po`, `techlead`) decides only the findings of its own role (`po+techlead` findings are decided by both); without
  the column the previous rule applies (every verdict decides every finding).

### Fixed

- Verdict front matter: inline comments (`key: value  # note`) are ignored when the verdict is read.

## [0.7.1] - 2026-09-26

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
