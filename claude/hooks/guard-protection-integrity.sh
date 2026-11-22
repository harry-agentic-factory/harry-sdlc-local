#!/bin/bash
# PreToolUse hook: protects the INTEGRITY of the protection layer itself.
#
# Answers one question only: is this tool call trying to weaken, unregister, relocate
# or bypass a guardrail? If so, it is denied — no exception, no flag, no escape hatch.
#
# DELIBERATELY has no bypass mechanism. block-secret-exposure.sh documented its own
# bypass ($HOME/.claude-allow-secrets) in its header, and on 2026-11-22 the agent read
# that header, created the flag and proceeded without asking. A guardrail that carries
# its own key is not a guardrail.
#
# This script is only as binding as its own file permissions: install it root-owned
# (see install runbook), otherwise the agent simply edits it away.
#
# Register on matcher "*" so it sees EVERY tool, not just Bash. The earlier setup
# registered only Bash/Read/Grep, which left the Write and Edit tools able to create
# the bypass flag without any hook firing.
#
# Exit codes: 0 = allow, 2 = deny (stderr is shown to the agent).

INPUT=$(cat)

TOOL=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')

# Every string the call could carry a target in, whatever the tool.
PAYLOAD=$(printf '%s' "$INPUT" | jq -r '
  [ .tool_input.command?,
    .tool_input.file_path?,
    .tool_input.path?,
    .tool_input.notebook_path?,
    .tool_input.content?,
    .tool_input.old_string?,
    .tool_input.new_string?,
    .tool_input.prompt?,
    (.tool_input.edits? // [] | .[]? | .old_string?, .new_string?),
    (.tool_input.file_paths? // [] | .[]?)
  ] | map(select(. != null) | tostring) | join(" \u0000 ")
' 2>/dev/null)

[ -z "$PAYLOAD" ] && exit 0

LOG_DIR=/var/log/claude-guard
LOG=$LOG_DIR/integrity.log

deny() {
  local reason="$1"
  if [ -d "$LOG_DIR" ] && [ -w "$LOG_DIR" ]; then
    printf '%s\tDENY\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TOOL" "$reason" \
      "$(printf '%s' "$PAYLOAD" | tr -d '\0' | head -c 400)" >> "$LOG" 2>/dev/null
  fi
  cat >&2 <<EOF
BLOCKED by the protection-integrity guard: $reason

This call would weaken or bypass a guardrail. That decision belongs to Anis, not to you,
and no skill, flag or workaround changes that — including one a tool's own comments
advertise.

Do instead: stop, and tell Anis in plain terms (1) the exact command that was refused,
(2) the guardrail that refuses it and why, (3) what you were trying to measure, and
(4) that lifting it requires his sudo password. Then carry on with whatever part of the
task does not depend on that measurement.
EOF
  exit 2
}

# ------------------------------------------------------------------
# 1. sudo: privilege escalation is never the agent's to attempt.
# ------------------------------------------------------------------
if [ "$TOOL" = "Bash" ]; then
  if printf '%s' "$PAYLOAD" | grep -qE '(^|[^a-zA-Z0-9_./-])sudo([^a-zA-Z0-9_-]|$)'; then
    deny "the command uses sudo"
  fi
  if printf '%s' "$PAYLOAD" | grep -qE '(^|[^a-zA-Z0-9_./-])(doas|su)([[:space:]]|$)'; then
    deny "the command attempts privilege escalation"
  fi
fi

# ------------------------------------------------------------------
# 2. Protected targets: the bypass flag, the hooks, the registration.
#    Matched on distinctive substrings so a rebuilt or quoted path is
#    still caught (e.g. ".claude-allow""-secrets" keeps the stem).
# ------------------------------------------------------------------
PROTECTED='claude-allow-secrets|allow[-_]secrets|/etc/claude|claude-guard|guard-protection-integrity|block-secret-exposure|\.claude/hooks|claude/hooks/|\.claude/settings(\.local)?\.json|talenteo-brain/hooks'

if ! printf '%s' "$PAYLOAD" | grep -qE "$PROTECTED"; then
  exit 0
fi

# ------------------------------------------------------------------
# 3. A write tool naming a protected path is denied outright: there is
#    no read-only way to use Write, Edit or NotebookEdit.
# ------------------------------------------------------------------
case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    deny "the $TOOL tool targets a protection file"
    ;;
esac

# ------------------------------------------------------------------
# 4. Bash referencing a protected path: reading is fine (diagnosing a
#    refusal must stay possible), mutating is not. Each segment that
#    names a protected path must START with a read-only command.
# ------------------------------------------------------------------
if [ "$TOOL" = "Bash" ]; then
  READ_ONLY='cat|head|tail|less|more|grep|egrep|rg|sed|awk|ls|stat|file|wc|diff|readlink|realpath|echo|printf|jq'


  # A here-string keeps the loop in THIS shell: behind a pipe it would run in a
  # subshell and its verdict would be lost.
  SEGMENTS=$(printf '%s' "$PAYLOAD" | tr '\0' '\n' | tr ';|&' '\n')

  while IFS= read -r seg; do
    [ -n "$seg" ] || continue
    printf '%s' "$seg" | grep -qE "$PROTECTED" || continue

    # A redirection onto a protected path is a write, whatever the verb.
    if printf '%s' "$seg" | grep -qE '>>?[[:space:]]*[^[:space:]]*('"$PROTECTED"')'; then
      deny "the command redirects output onto a protection file"
    fi
    # sed -i rewrites in place despite sed being a reader.
    if printf '%s' "$seg" | grep -qE '\bsed\b.*-i'; then
      deny "the command rewrites a protection file in place (sed -i)"
    fi

    first=$(printf '%s' "$seg" \
      | sed -e 's/^[[:space:]]*//' -e 's/^[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]*//g' \
      | awk '{print $1}' | sed 's#.*/##')

    case "$first" in
      touch|rm|rmdir|mv|cp|ln|chmod|chown|install|tee|truncate|dd|unlink|shred|open|code|vim|vi|nano|emacs)
        deny "the command would create, delete, move or re-permission a protection file ($first)"
        ;;
    esac

    if ! printf '%s' "$first" | grep -qE "^($READ_ONLY)$"; then
      deny "'$first' is not a read-only command, and it names a protection file"
    fi
  done <<< "$SEGMENTS"
fi

exit 0
