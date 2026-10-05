# Brain — `sdlc brain` and the `sdlc.brain` library

A **brain** is a git repository (or a sub-folder of one) holding the knowledge notes of a project.
Git is its only source of truth and its only versioning: the engine **reads a commit** and, for
`normalize`, **proposes** a change on a new branch. Nothing is ever read from the working copy, the
index or `git status`; nothing is pushed; no hosting API is called.

## Note model

- **Note** = a regular `*.md` file tracked at the commit being read, under the brain folder, not
  excluded. An untracked, ignored or modified-but-uncommitted file is never a note.
- **Exclusions** (always added, never replaced): defaults `.claude/**`, `hooks/**`, plus the
  `exclude:` list of the mapping, plus `--exclude` (repeatable). An entry ending with `/` is a folder
  (`<entry>**`).
- **Only required header**: `category`, in a front matter block (first line exactly `---`, up to the
  next `---` line). Nothing else is imposed. Title = first `# ` heading of the body; version = git.
- **Categories** and derived **reader profile** (never written in the note):

| category | reader profile |
|---|---|
| `usage` | `mixte` |
| `produit` | `fonctionnel` |
| `archi`, `repo`, `config`, `cicd`, `recette`, `exploit`, `observ` | `technique` |

The order of this list (`CATEGORIES`) is the display order: `usage` first.

- Front matter reading tolerates a UTF-8 BOM and CRLF line endings. An opening `---` without a
  closing line, a duplicated `category` key or a block that is not valid UTF-8 is
  `frontmatter_unreadable`.

## Deduction rules and matcher

`normalize` deduces `category` from the note path. Evaluated list = **project rules first**, then the
engine defaults (extension, never replacement); **the first matching rule wins**. Engine defaults,
in order:

| pattern | category |
|---|---|
| `README.md`, `CLAUDE.md` | `usage` |
| `per-repo/**`, `repos/**` | `repo` |
| `**/architecture*.md`, `adr/**` | `archi` |
| `**/config*/**`, `**/config-management*.md` | `config` |
| `**/ci-cd*`, `**/cicd*` | `cicd` |
| `e2e/**`, `**/recette*.md` | `recette` |
| `**/kubernetes*`, `**/deploy*/**` | `exploit` (after `cicd`, which wins) |
| `**/observ*`, `**/monitoring*` | `observ` |
| `produit/**`, `product/**` | `produit` |

**Matcher** (engine-defined, independent of `fnmatch`/`pathlib`): pattern and path are split on `/`;
the pattern must cover the **whole** path (relative to the brain root); `**` = 0..n whole segments;
`*` = 0..n characters inside one segment (never crosses `/`); `?` = one character other than `/`;
`[` and `{` are literal. Examples: `**/ci-cd*` matches `ci-cd.md` and `deployments/ci-cd.md`;
`per-repo/*` does not match `per-repo/x/y.md`; `per-repo/**` does.

## `brain-map.yaml`

Project rules live **in the brain repository** (`brain-map.yaml` at the brain root, read at the
commit), or in an explicit `--map <file>` on disk. Restricted YAML (stdlib only):

```yaml
# comments are allowed
rules:
  - "misc/**": produit        # "<glob>": <category>  (glob bare or quoted)
  - per-repo/**: repo
exclude:
  - drafts/                   # folder
  - "**/scratch-*.md"
```

Only the top-level keys `rules:` and `exclude:` (each at most once), space indentation, list items
`- ...`. Anything else (nested mappings, flow style, tabs, other keys) is rejected with
`mapping_unsupported` (`brain-map.yaml:<line>: <excerpt>`); an unknown category with
`mapping_invalid_category` (`<glob>: <category>`). Both exit with code 2.

## Commands

All commands take `--repo <brain>` (a git work tree or a sub-folder of one: paths are then relative
to that folder, found with `git rev-parse --show-prefix`). Refs are resolved by `resolve_brain_ref`
(below), without any fetch. Every command reports the resolved commit (full sha).

| command | what it does |
|---|---|
| `normalize [--map] [--base] [--branch] [--dry-run] [--report f.md] [--exclude]*` | Adds deduced `category` headers on a **new** branch (default `brain/normalize-<YYYYMMDD-HHMM>`, base default `main` then `master`). |
| `lint [--ref HEAD] [--map] [--exclude]* [--strict] [--format json\|text]` | Checks the notes of one commit. |
| `snapshot --ref <ref> --out <dir> [--map] [--exclude]*` | Writes the exact notes of the commit + `manifest.json` + `links.json`. `<dir>` must be empty or absent. |
| `diff --repo R <refA> <refB>` / `diff --manifests <a.json> <b.json>` | File by file comparison; the manifest mode needs no git. |
| `history <note> [--ref HEAD]` | `git log --follow` of one note, newest first. |

**`normalize` guarantees.** Refused before any write (exit 2): an invalid branch name
(`branch_invalid`), `main`, `master` or the branch pointed by `origin/HEAD` (`branch_protected`), an
existing branch (`branch_exists`). The commit is built with plumbing only: new blobs
(`hash-object -w --no-filters`), a temporary index, `commit-tree -p <base>`, then
`update-ref refs/heads/<branch> <sha> ""` (creation only). No worktree, no checkout: the working copy,
the repository index and the current branch are out of reach, and no filter, hook or
`core.autocrlf` can alter bytes. Front matter merge:

- no block: `---`, `category: <c>`, `---` inserted at the top (after the BOM, if any);
- block without `category`: `category: <c>` added as its last line, other keys and order kept;
- valid `category`: untouched (`already`); invalid or unreadable: untouched (`invalid`);
- no matching rule: untouched (`undecidable`, for a human decision).

The inserted lines use the file end of line (the one of its first line). Everything after the front
matter is kept **byte for byte**. `commit-tree` needs a git identity (`user.name`/`user.email`) in
the brain; without it the command fails with `git_failed` and no ref is created.

### Exit codes and error codes

- **0** success, including `lint` with warnings only;
- **1** `lint` found errors (or warnings with `--strict`) — only `lint` returns 1;
- **2** library error (stderr: `{"error": "<message>", "code": "<code>"}`) and argparse usage errors.

Error codes: `brain_not_found`, `brain_not_git`, `brain_ref_unresolved`, `note_not_found`,
`mapping_unsupported`, `mapping_invalid_category`, `mapping_not_found`, `manifest_invalid`,
`out_not_empty`, `branch_invalid`, `branch_protected`, `branch_exists`, `git_failed`.
Lint codes: `missing_category`, `invalid_category`, `frontmatter_unreadable`.

## JSON contracts (stable for 0.7.x: keys may be added, never renamed or removed)

**Links** (`links.json`, `lint.warnings`, `normalize.broken_links`) — one algorithm:

```json
[{"from": "per-repo/a.md", "to": "per-repo/missing.md", "target": "missing.md",
  "kind": "md-link", "line": 5, "resolved": false}]
```

- `kind`: `md-link` (`[x](path.md)` and `[ref]: path.md`), `external` (`http(s)://`, `mailto:`;
  `resolved` = `null`), `path-mention` (a `*.md` path written in text or inline code).
- Fenced code blocks are skipped: no link of any kind is extracted inside a ```` ``` ```` or `~~~`
  block (CommonMark: opening fence indented by at most 3 spaces, at least 3 characters; closing fence
  of the same character and at least as long; an unclosed block runs to the end of the file). Inline
  code is still scanned, 4-space indented blocks are not skipped, line numbers are unchanged.
- Ignored: anchor-only targets (`#...`), targets not ending with `.md` once `#...`/`?...` are removed
  (images, scripts), image links. Targets are URL-decoded before resolution.
- `target` = the target as written; `line` = 1-based line in the full file (front matter included);
  `to` = normalised path relative to the brain root (`md-link`: relative to the note folder;
  `path-mention`: relative to the note folder, falling back to the brain root), then a leading
  `../<brain-repo-name>/` is removed (folder name, top-level name or `remote.origin.url` name).
  A target outside the brain keeps its `../` and is broken.
- `resolved` = `to` is a note of the same commit. **Broken link** = non `external` and
  `resolved == false`; in `lint.warnings` and `normalize.broken_links` it is
  `{from, to, target, kind, line}`. Sorted by `from`, then line and column; every occurrence counts.

**`lint`**: `{commit, notes, errors: [{path, code}], warnings: [...]}` (`notes` = count).
`--format text`: `error <path>: <code>` / `warning <from>:<line>: broken <kind> -> <target>` lines,
then `lint: <n> notes, <e> errors, <w> warnings (<commit>)`.

**`manifest.json`**: `{repo_ref, commit, date, files: [{path, category, blob, last_commit, date}]}` —
`blob` = git blob sha; `last_commit`/`date` = last commit <= `commit` touching the file
(`git log -1`); `category` = front matter value or `null`; root `date` = committer date of `commit`
(ISO 8601). `snapshot` prints `{repo_ref, commit, out, files, links, broken_links}` (counts).

**`diff`**: `{from, to, files: [{path, status, old_path?}]}` sorted by `path`; `status` ∈ `added`,
`modified`, `deleted`, `renamed`, `unchanged`; `old_path` only for `renamed`. Both modes use the same
`diff_files`: same path + same blob = `unchanged`, same path + other blob = `modified`, a deleted
and an added file with the **same blob** = `renamed`. A rename **with** modification is therefore
`deleted` + `added` (the manifest mode cannot do better, and both modes must agree).

**`history`**: `[{commit, date, author, message, path}]`, newest first; `path` = file name at that
commit (renames followed); `author` = name only; `message` = subject. No history = `note_not_found`.

**`normalize`**: `{commit_base, branch, commit, counts, deduced: [{path, category, rule}], already,
invalid, undecidable, broken_links}`; `counts` = distribution of `deduced` only (zero categories
omitted); lists sorted by `path`; `branch`/`commit` = `null` on `--dry-run` or when nothing is
deduced. `--report f.md` writes the same content as Markdown (distribution, deduced, already
classified, invalid, undecidable, broken links — every section present, even empty), ready to paste
in a merge request.

## `brainRef` in the project manifest

Optional key of `sdlc.config.json`: `brainRef` (branch, tag or sha). `sdlc config` (not `--raw`) adds
`brainRef` (the retained ref), `brainCommit` (resolved sha) and `brainRefFrom`
(`origin` | `local` | `tag` | `sha`). Resolution order, **without fetch**:
`refs/remotes/origin/<ref>`, `refs/heads/<ref>`, `refs/tags/<ref>` (annotated tags peeled), then any
revision (`<ref>^{commit}`); `HEAD` resolves locally. Key absent: `main`, then `master`. Unresolvable
ref: `brainCommit` = `null` + stderr warning `{"warning": "brain_ref_unresolved", ...}`; brain
outside git: same with `brain_not_git`; exit code 0 in both cases. No `brain` in the manifest: the
three keys are `null`.

## Library API (`import sdlc.brain`)

Side-effect free (no print, no exit); `repo` is the brain folder path.

```python
CATEGORIES, READER_PROFILE, DEFAULT_EXCLUDES, DEFAULT_RULES
BrainError(code, message)            # BrainNotGit ("brain_not_git"), BrainRefUnresolved ("brain_ref_unresolved")
ResolvedRef(ref, commit, source)     # source: origin | local | tag | sha
Note(path, blob, mode)
resolve_brain_ref(repo, ref=None) -> ResolvedRef
list_notes(repo, commit, *, excludes=(), map_path=None) -> list[Note]          # sorted by path
read_notes(repo, commit, paths) -> dict[str, bytes]                            # one cat-file --batch
effective_excludes(repo, commit, *, excludes=(), map_path=None) -> tuple[str, ...]
extract_links(repo, commit, *, excludes=(), map_path=None) -> list[dict]       # links.json
lint(repo, ref=None, *, excludes=(), map_path=None, strict=False) -> dict      # + "exit" (0/1); ref None = HEAD
build_manifest(repo, ref, *, excludes=(), map_path=None) -> dict
snapshot(repo, ref, out, *, excludes=(), map_path=None) -> dict
diff_refs(repo, ref_a, ref_b) -> dict ; diff_manifests(a, b) -> dict
history(repo, path, ref=None) -> list[dict]
normalize(repo, *, base=None, branch=None, map_path=None, excludes=(), dry_run=False, now=None) -> dict
parse_frontmatter(data) -> Frontmatter ; match_glob(pattern, path) -> bool
is_excluded(path, excludes) -> bool ; parse_mapping(data) -> Mapping(rules, excludes)
```

Notes for callers:

- A caller reading a brain **outside git** (working copy fallback) reads `brain-map.yaml` itself and
  applies `parse_mapping` + `is_excluded(path, DEFAULT_EXCLUDES + mapping.excludes)`; the library
  itself only reads commits.
- On a partial clone (`--filter=blob:none`), `cat-file` lazily fetches missing blobs (native git
  behaviour); a failure surfaces as `git_failed`.
- A platform exposing `history` may rename `message` to `subject` and `path` to `path_at_commit`,
  and may drop `unchanged` entries of `diff`: these mappings belong to the caller.

## Lint in CI (any host)

The command is the contract: exit code 1 blocks. A shallow clone is enough (`lint` reads `HEAD`).

```bash
pip install "harry-sdlc @ git+<engine-repo-url>@<tag>#subdirectory=tooling"
sdlc brain lint --repo . --ref HEAD --format text
```

GitHub Actions:

```yaml
jobs:
  brain-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install "harry-sdlc @ git+<engine-repo-url>@<tag>#subdirectory=tooling"
      - run: sdlc brain lint --repo . --ref HEAD --format text
```

GitLab CI:

```yaml
brain-lint:
  image: python:3.11
  script:
    - pip install "harry-sdlc @ git+<engine-repo-url>@<tag>#subdirectory=tooling"
    - sdlc brain lint --repo . --ref HEAD --format text
```
