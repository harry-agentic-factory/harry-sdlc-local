# Run workspace (`sdlc run`, `sdlc doc`, `sdlc.runws`)

A **run** is one execution of an autonomous agent on a story (or a mission). The engine builds an
isolated **run workspace** for it; the agent reads under `in/` and adds under `rw/out/`; the engine then
**publishes** what was added and **removes** the workspace. The agent never knows a path of the data
repository.

```
sdlc run init  -->  workspace (in/ filled, rw/ empty)  -->  agent: sdlc doc read / sdlc doc add
                                                                      |
sdlc run finish <---------------------------------------------------- +
   = checks -> publication (trace runs/<run_uid>/ + round prepended to the story artifact) -> clean
```

Every read and write of the storage goes through a port (`DocumentRepository` + `RunSource`). The CLI
uses the local data repository backend (`DataRepoBackend`); a platform plugs its own backend.

## Commands

```bash
sdlc [--project P] run init <STORY> --agent <role> [--phase <phase>]
sdlc [--project P] run init --mission <id> --agent <role>
sdlc [--project P] run finish <run_uid|root> [--keep]
sdlc [--project P] run clean  <run_uid|root>
sdlc [--project P] run list   [<STORY>] [--mission <id>]

sdlc doc read <key>           [--run <root>]    # raw bytes on stdout
sdlc doc list                 [--run <root>]    # JSON list
sdlc doc add <type> <file|->  [--run <root>]
```

`doc` commands take the run from `--run` or the `SDLC_RUN` environment variable and never resolve a
project: they only need `<root>/in/manifest.json`, `<root>/in/` and `<root>/rw/out/` (they work in a
container where only the run workspace is mounted).

Exit codes: `0` success; `1` refusal (stderr `{"error": "<code>:<detail>"}`) and rejected `finish`
(the JSON result is on stdout, `state: "rejected"`); `2` brain library error (stderr `{"error", "code"}`).
Callers should read `state`, not the exit code.

## Layout

Default location: `<reposRoot or parent of the data repository>/_agentws/<PREFIX>/<STORY|MISSION>/<run_uid>/`
(same root as the `sdlc workspace` bubble, which is unchanged). The library accepts any parent (`root=`).

```
<root>/
├── run.json                  state of the run (schema below)
├── seal.json                 sha256 of in/manifest.json and in/settings.json (never published)
├── in/                       read only for the agent
│   ├── manifest.json         what the run received
│   ├── settings.json         agent bubble (permissions)
│   ├── brain/<path>.md       brain notes at the resolved commit
│   ├── feature/atelier/<name>.md          every root *.md of the epic but _index.md
│   ├── feature/stories/<US>/<doc>.md      every story of the epic, level 1, not journal.md
│   ├── mission/brief.md, mission/sources/<path>.md   (mission run, instead of feature/)
│   ├── repos/<repo>/         reserved (filled by a later clone step)
│   └── repro/                reserved
└── rw/
    ├── code/                 empty (reserved for a later clone step)
    ├── scratch/              agent drafts, never read nor published
    └── out/{docs,sources,git}/
```

Pull is **Markdown only**: `status.json`, `_index.md`, `journal.md`, binaries and story sub-folders
(`repro/`...) are never copied. The core enforces it on the storage keys (below), whatever the backend
returns.

The brain is read **at the resolved commit** (`brainRef` of the project manifest, default `main` then
`master`; `refs/remotes/origin/<ref>` first, then local ref, tag or sha; no fetch), with the exclusions of
the brain library (`.claude/`, `hooks/`, `exclude:` of `brain-map.yaml` read at the commit). A file that is
modified, added or ignored in the brain working copy is never seen.

| Brain situation | Result | Warning |
|---|---|---|
| resolved | notes at the commit, `brain: {ref, commit}` | none |
| not declared or folder missing | `in/brain/` empty | `brain_missing` |
| ref cannot be resolved | `in/brain/` empty, `brain.ref` = requested ref | `brain_ref_unresolved` |
| not a git repository | working copy `*.md` (hidden folders, `node_modules`, `_toDelete`, `_wt`, `_agentws` skipped, same exclusions), `version: null` | `brain_not_git` |
| `brain-map.yaml` invalid (commit or working copy) | `in/brain/` empty | `brain_map_invalid` |

A git failure of the brain library is a refusal (exit 2) raised before anything is written.

## `sdlc run init`

Returns `{run_uid, root, in, rw, out, code, scratch, settings, manifest, brain: {ref, commit, from, files,
bytes}, warnings}` (absolute paths; `files`/`bytes` = count and size of the brain notes copied; `warnings`
sorted). All validations and reads happen before the first write; the workspace is built in
`<parent>/.<run_uid>.partial/` and renamed, so a run is never half visible. Refusals (nothing created):
`agent_missing`, `agent_invalid`, `scope_invalid` (both or none of story/mission, or an invalid id),
`phase_invalid`, `story_unknown:<id>`, `mission_unknown:<id>`.

**`run_uid`** = `^\d{8}-\d{6}-[0-9a-f]{6}$`: UTC `%Y%m%d-%H%M%S` + 3 random bytes. A supplied uid
(library) is checked (`run_uid_invalid`) and refused when the workspace or the trace exists (`run_exists`).

### `run.json`

Exactly these 14 keys (`RUN_JSON_KEYS`); a reader tolerates extra keys (a platform may add some).

```json
{
  "schema_version": 1, "run_uid": "20260926-101500-0a1b2c", "agent": "reviewer", "phase": "reviewer",
  "feature": "DEMO-E", "story": "DEMO-E-1", "mission": null, "ticket": null,
  "created_at": "2026-09-26T10:15:00Z", "finished_at": null, "state": "open", "reasons": [],
  "published": [], "engine": {"name": "harry-sdlc", "version": "0.7.0"}
}
```

`state` in `open | published | rejected | failed | timeout`; `phase` defaults to the agent role; `feature`
and `story` are `null` for a mission, `mission` is `null` for a story; `published` = `[{type, round, path}]`
with `path` = storage key `runs/<uid>/out/docs/<type>.md`.

### `in/manifest.json`

```json
{
  "schema_version": 1, "run_uid": "20260926-101500-0a1b2c",
  "scope": {"feature": "DEMO-E", "story": "DEMO-E-1", "mission": null},
  "files": [
    {"key": "brain/adr/0001.md", "version": "<blob sha>", "sha256": "...", "size": 20, "origin": "adr/0001.md"},
    {"key": "feature/atelier/prd.md", "version": "<commit sha>", "sha256": "...", "size": 21, "origin": "DEMO-E/prd.md"}
  ],
  "brain": {"ref": "main", "commit": "<commit sha>"},
  "dirty": []
}
```

- File entry = exactly `{key, version, sha256, size, origin}`: `key` = path relative to `in/` (extension
  included), `version` = opaque string or `null`, `sha256` of the bytes written, `origin` = path relative to
  the source repository (a storage object key on a platform). Sorted by `key`.
- Data repository version = sha of the last commit touching the file at `HEAD`; untracked or modified
  against `HEAD` ⇒ `null` and the key is listed in `dirty`. Brain version = git blob at `brain.commit`.
- Neighbour entry (added by a later clone step, never produced here): `{key: "repos/<repo>", commit, role}`.
- `scope` lets `doc read spec-tech` know the story of the run where `run.json` is not mounted.

### `in/settings.json` (bubble)

```json
{"permissions": {
  "additionalDirectories": ["<A>/in", "<A>/rw"],
  "allow": ["<allow of the role in the project manifest>"],
  "deny": ["<shared deny of the project manifest>", "Edit(/<A>/in/**)", "Write(/<A>/in/**)"]
}}
```

`A` = the workspace root, or `agent_root` (library: the root as the agent sees it, e.g. `/work`). With `A`
absolute the rules read `Edit(//abs/in/**)`: in the Claude Code rule syntax `//` starts an absolute path.
`allow` is omitted when the role has none. Neither the data repository nor the brain is in the file.

## `sdlc doc read | list | add`

A key is resolved **only among the file entries of the manifest** (never a free path, so no traversal).
Candidates in order, the first one present wins, otherwise `unknown_key:<k>; available: <keys>`:

1. reserved keys: `prd`, `refine` ⇒ `feature/atelier/<k>.md`; `brief` ⇒ `mission/brief.md`;
2. reserved prefixes: `atelier/<n>` ⇒ `feature/atelier/<n>.md`; `brain/<p>` ⇒ `brain/<p>.md`;
   `mission/<p>` ⇒ `mission/<p>.md`; `repro/…`, `repos/…` ⇒ steps 5-6 only;
3. `<doc>` without `/` ⇒ `feature/stories/<story of the run>/<doc>.md`;
4. `<US>/<doc>` (first segment not reserved) ⇒ `feature/stories/<US>/<doc>.md`;
5. `<k>.md`; 6. `<k>` as is (raw manifest key, e.g. `repro/steps.md`).

`doc read` writes the raw bytes (nothing added). `doc list` returns `[{key, path, version}]` sorted by
`key`, `key` being the shortest form (`prd`, `atelier/<n>`, `<US>/<doc>`, `brain/<p>`, `brief`,
`mission/sources/<p>`, else the raw key), `path` the key under `in/`.

`doc add <type> <file|->` writes `rw/out/docs/<type>.md` once (`O_EXCL`): a second add of the same type is
refused (`doc_exists:<type>`) and the first document is untouched. Types (`DOC_TYPES`): `review`,
`acceptance`, `demo`, `deploy`, `implement`, `nonreg`, `findings`, `report` (else `type_invalid`, the message
lists them). Returns `{added, path, sha256}`. `implement` added here is the output of an autonomous run
(a round); the living `implement.md` of the interactive command is not changed by the engine.

## `sdlc run finish`

All or nothing: **every check runs before the first publication write**.

| Check | Reason (sorted, workspace kept, `state: rejected`) |
|---|---|
| `in/manifest.json` / `in/settings.json` differ from `seal.json` | `in_modified:manifest.json`, `in_modified:settings.json` |
| file under `in/` added, removed, changed, or any symbolic link (neighbour subtrees `repos/<repo>/` excluded: delegated to their git check; a `repos/<x>/` without neighbour entry is "added") | `in_modified:<path relative to in/>` |
| anything under `rw/out/` other than a regular `docs/<type>.md` or the content of `sources/`, including **any** file under `git/` and any symbolic link | `unexpected_file:<path relative to rw/out/>` |
| document larger than 1 MiB (`DOC_MAX_BYTES` = 1 048 576) | `too_large:docs/<type>.md` |

Warnings (published anyway): `no_recap` (a document without a line starting with `## recap`, case
insensitive: `sdlc status` would show no recap for it) and `sources_not_published` (`rw/out/sources/` is not
empty; published by a later step). `rw/scratch/` and `rw/code/` are never walked.

Publication (backend `put`, add-only): each document sorted by type ⇒ `runs/<uid>/out/docs/<type>.md`
(returns its `round`), then `runs/<uid>/manifest.json` (copy of `in/manifest.json`), then
`runs/<uid>/run.json` **last** (end marker); only then the workspace `run.json` is set to its final state and
the workspace removed (`--keep` keeps it). A crash before the last `put` leaves the workspace `open` and a
second `finish` replays everything idempotently. A second `finish` after a final trace returns
`{run_uid, already: <state>}` with exit 0 and writes nothing.

Returns `{run_uid, state, published: [{type, round, path}], warnings}` (+ `reasons` when rejected).
Library only: `run_finish(..., outcome="failed" | "timeout")` runs the same checks, publishes the same way
and sets the final state to the outcome.

### Rounds

One rule: `round` = rank for `(story, else ticket, else mission) × kind`, numbered by the backend in `put`.
Header of a round (one line):

```
<!-- round <N> · run <run_uid> · agent <role> · <YYYY-MM-DDTHH:MM:SSZ> -->
```

matched by `ROUND_HEADER_RE = ^<!-- round (\d+) · run (\d{8}-\d{6}-[0-9a-f]{6}) · agent ([a-z][a-z0-9-]*) · (\S+) -->$`.

Local backend: story ⇒ `max(N of the header lines of <type>.md of the story) + 1` (no header, missing file
or plain stub ⇒ 1; content without header counts 0 rounds). The new document is **prepended**:
`header + "\n" + doc (+ "\n" if missing) + ("\n" if old content) + old content`, the old bytes kept byte for
byte, and the artifact is linked to the story (as `sdlc link`). A header line whose run group is the same
uid means "already rendered" (replay). Mission ⇒ 1 + number of final traces of the same mission that
published this type; no aggregated file.

## `sdlc run clean` and `sdlc run list`

- `clean <run_uid|root>` removes the workspace without publishing anything (`{run_uid, cleaned: true}`);
  unknown ⇒ `run_unknown`. A path is removed only when it holds a `run.json` whose `run_uid` is its name.
- `list [<STORY>] [--mission <id>]` = workspaces ∪ traces `runs/*/run.json` (a trace wins over a kept
  workspace of the same run), filtered on `story`/`mission` of `run.json`, sorted by `run_uid`:
  `[{run_uid, story, mission, agent, state, created_at, root}]` (`root` = `null` for a trace without
  workspace). Bubble entries (`.claude/`, `scratch/`, `README.md`) and `.partial` folders are ignored.

Note: `sdlc worktree-clean` removes the whole `_agentws/<PREFIX>/<STORY>/` folder, open run workspaces
included (they are throwaway; traces live in the data repository).

## Storage keys (port)

| Storage key | Path under `in/` | Local data repository |
|---|---|---|
| `features/<E>/atelier/<name>.md` | `feature/atelier/<name>.md` | `<data>/<E>/<name>.md` (root `*.md` but `_index.md`) |
| `features/<E>/stories/<US>/<doc>.md` | `feature/stories/<US>/<doc>.md` | `<data>/<E>/stories/<US>/<doc>.md` (level 1, not `journal.md`) |
| `missions/<M>/brief.md`, `missions/<M>/sources/<p>.md` | `mission/brief.md`, `mission/sources/<p>.md` | `<data>/missions/<M>/…` (`sources/` recursive) |
| `project/brain/@<commit>/<p>.md` | `brain/<p>.md` | brain repository at the commit; fallback `project/brain/@worktree/<p>.md` |
| `runs/<uid>/run.json`, `runs/<uid>/manifest.json`, `runs/<uid>/out/docs/<type>.md` | (publication) | `<data>/runs/<uid>/…` |

Nothing is committed: the data repository is left modified, as when an agent writes it. Git is used read
only on it (`rev-parse`, `ls-files`, `diff`, `log`, with `--no-optional-locks`).

## Library API (`sdlc.runws`, stable for 0.7.x: keys and parameters may be added only)

```python
from sdlc.runws import run_init, run_finish, run_clean, run_list, doc_read, doc_list, doc_add

run_init(project=None, *, agent, story=None, mission=None, phase=None, root=None, backend=None,
         run_uid=None, agent_root=None) -> dict
run_finish(run, *, backend=None, keep=False, outcome=None) -> dict     # run = run_uid | workspace path
run_clean(run, *, backend=None) -> dict
run_list(project=None, *, story=None, mission=None, backend=None) -> list[dict]
doc_read(key, *, run=None) -> bytes
doc_list(*, run=None) -> list[dict]
doc_add(type, content: bytes, *, run=None) -> dict
# also: DocumentRepository, RunSource, Entry, Scope, BrainPin, DataRepoBackend, RunError,
#       DOC_TYPES, RUN_STATES, RUN_JSON_KEYS, RUN_UID_RE, ROUND_HEADER_RE, SCHEMA_VERSION, DOC_MAX_BYTES
```

- `backend=None` ⇒ `DataRepoBackend.from_project(project)`; `root=None` ⇒ `backend.default_root(<id>)`.
  A backend without workspace discovery (`default_root`, `find_workspace`, `iter_workspaces`) needs
  `root=` for init and a workspace path for finish/clean (`root_required`).
- No function prints or exits; errors are `RunError` with `str(e) == "<code>:<detail>"`
  (e.g. `story_unknown:DEMO-E-99`).

Port:

```python
class DocumentRepository(Protocol):
    def get(self, key, version=None) -> bytes: ...          # KeyError when absent
    def list(self, prefix) -> list[Entry]: ...              # Entry = {key, version, sha256, size, origin}, sorted
    def versions(self, key) -> list[str]: ...               # newest first, [] when unknown
    def put(self, key, content, meta) -> dict: ...          # {key, version} (+ round for a run document)

class RunSource(Protocol):
    def locate(self, *, story, mission) -> Scope: ...       # Scope(feature, story, mission)
    def brain(self) -> BrainPin: ...                        # BrainPin(ref, commit, source, prefix, files_hint, warnings)
    def bubble(self, agent) -> dict: ...                    # {"allow": [...], "deny": [...]}
```

`put` is add-only: same bytes on an existing key ⇒ no-op, other bytes ⇒ `put_conflict`. `meta` of a run
document = `{category: "artifact", kind, run_uid, agent, phase, feature, story, mission, ticket, at}`; of
`manifest.json` / `run.json` = `{category: "run_meta", run_uid}`. `list("runs/")` returns the
`runs/<uid>/run.json` of the traces.

## Example (throwaway project `DEMO`)

```bash
out=$(sdlc --project DEMO run init DEMO-E-1 --agent reviewer)
export SDLC_RUN=$(echo "$out" | jq -r .root)
sdlc doc read spec-tech                     # the story spec
printf '## Recap\nOK\n' | sdlc doc add review -
sdlc --project DEMO run finish "$(echo "$out" | jq -r .run_uid)"
sdlc --project DEMO status DEMO-E-1         # review recap = OK
```
