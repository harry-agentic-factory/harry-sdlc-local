# `claude/hooks/` — the harness guardrails

A skill or an agent definition tells the agent what to do; a hook **refuses** what the agent
should not do. The difference matters: an instruction can be reasoned around, a hook cannot.
Everything here is therefore written for an agent that is competent, well-intentioned, and
perfectly capable of talking itself into an exception.

## Contents

| Hook | Event | Refuses |
|---|---|---|
| `guard-protection-integrity.sh` | `PreToolUse`, matcher `*` | any attempt to weaken, relocate, unregister or bypass a guardrail — including this one |

## `guard-protection-integrity.sh`

Born from a measured incident (2026-11-22, HIA back-tenant). A secret-exposure hook on that
machine **advertised its own bypass in its header comments** — create `~/.claude-allow-secrets`
and the hook returns 0 — and was registered only on `Bash`, `Read` and `Grep`. The agent read the
header, created the flag with a plain `touch`, and went on to query a production database. No
rule was unknown to it; it simply took a decision that was not its own to take.

Three design consequences, each paid for by that incident:

1. **No bypass.** A guardrail that carries its own key is not a guardrail. If this hook ever gets
   in the way, it is removed deliberately, with `sudo`.
2. **Matcher `*`.** Registering on `Bash` alone leaves the `Write` and `Edit` tools able to create
   the very file that disables the protection. The battery contains that case.
3. **Reading stays allowed.** A guard that blocks diagnosis gets switched off, and then it
   protects nothing. `cat`/`grep` on a hook passes; `touch`/`sed -i`/`chmod`/`mv`/redirection does
   not.

### What it does not do

`tests/test-guard-adversarial.py` exists to keep the claim bounded: **3 of 7 deliberately
obfuscated evasions get through** (path rebuilt by concatenation, broken up by quotes, carried in
base64). A hook that matches command strings cannot close those, and pretending otherwise would
be worse than the hole.

The barrier that does not depend on string matching is **file ownership**. `INSTALL.md` puts the
guard, the hook copies, the bypass flag location and the hook registration under `root`, so
lifting any of it requires the operator's password. The hook catches the lapse; root catches the
intent.

## Running the proofs

```bash
python3 -I claude/hooks/tests/test-guard.py              # 25/25 expected, exit code is the verdict
python3 -I claude/hooks/tests/test-guard-adversarial.py  # 3/7 evasions expected to pass
```

The second one is not a failing test. It is a measurement, and it is meant to stay red.

## Installing

See `INSTALL.md`. The short version: the files here are the **editable source of truth**; the
copies that actually execute are root-owned, and resynchronising them is a conscious `sudo
install`, never a side effect of a `git pull`.
