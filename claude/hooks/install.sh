#!/bin/bash
# Installs the guardrail layer so that the AGENT CANNOT LIFT IT.
#
#   sudo bash claude/hooks/install.sh
#
# Must run as root, and that is the whole point: the executing copies, the bypass flag
# location and the hook registration all end up owned by root, out of reach of the account
# the agent runs as. The files in this repository stay the editable source of truth.
#
# Idempotent: re-run it after editing a hook here to resynchronise the root copies.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  cat >&2 <<'EOF'
This installer must run as root:

    sudo bash claude/hooks/install.sh

Running it as your own account would put the guardrails back under an account the agent
can write to, which defeats their purpose. Nothing has been changed.
EOF
  exit 1
fi

HOOKS_SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OWNER=${SUDO_USER:-$(stat -f %Su "$HOOKS_SRC")}

LIB=/usr/local/lib/claude-guard
FLAG_DIR=/etc/claude
LOG_DIR=/var/log/claude-guard
MANAGED_DIR="/Library/Application Support/ClaudeCode"
MANAGED="$MANAGED_DIR/managed-settings.json"

# The secret-exposure hook still lives in its original repository on this machine; take it
# along if it is there, so both hooks execute from root-owned copies.
SECRET_HOOK_SRC=${SECRET_HOOK_SRC:-/Users/anisbessa/dev/workspace/talenteo/talenteo-brain/hooks/claude/block-secret-exposure.sh}

echo "== 1. root-owned locations =="
install -d -o root -g wheel -m 755 "$LIB" "$FLAG_DIR"
install -d -o root -g staff -m 775 "$LOG_DIR"      # group-writable: the guard logs refusals
install -d -o root -g wheel -m 755 "$MANAGED_DIR"

echo "== 2. the integrity guard =="
install -o root -g wheel -m 755 "$HOOKS_SRC/guard-protection-integrity.sh" "$LIB/"

REGISTER_SECRET_HOOK=false
if [ -f "$SECRET_HOOK_SRC" ]; then
  echo "== 3. the secret-exposure hook, with its bypass moved under root =="
  install -o root -g wheel -m 755 "$SECRET_HOOK_SRC" "$LIB/block-secret-exposure.sh"
  # $HOME is the agent's own directory: a flag there is a door with the key taped to it.
  perl -0pi -e 's{\$HOME/\.claude-allow-secrets}{/etc/claude/allow-secrets}g' \
      "$LIB/block-secret-exposure.sh"
  perl -0pi -e 's{^# Bypass: create .*$}{# Bypass: root only -- sudo touch /etc/claude/allow-secrets}m' \
      "$LIB/block-secret-exposure.sh"
  perl -0pi -e 's{^# Remove the file when done.*$}{# Remove it when done -- sudo rm /etc/claude/allow-secrets}m' \
      "$LIB/block-secret-exposure.sh"
  if grep -q 'HOME/\.claude-allow-secrets' "$LIB/block-secret-exposure.sh"; then
    echo "   REFUSED: the bypass still points at \$HOME after rewriting. Check the hook by hand." >&2
    exit 1
  fi
  grep -n "allow-secrets" "$LIB/block-secret-exposure.sh" | sed 's/^/   /'
  REGISTER_SECRET_HOOK=true
else
  echo "== 3. secret-exposure hook not found at $SECRET_HOOK_SRC -- skipped =="
fi

echo "== 4. registration in the managed settings (the agent cannot edit these) =="
SECRET_ENTRY=""
if [ "$REGISTER_SECRET_HOOK" = true ]; then
  SECRET_ENTRY=',
      {
        "matcher": "Bash|Read|Grep",
        "hooks": [
          { "type": "command", "command": "/usr/local/lib/claude-guard/block-secret-exposure.sh" }
        ]
      }'
fi

cat > "$MANAGED" <<JSON
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": "/usr/local/lib/claude-guard/guard-protection-integrity.sh" }
        ]
      }${SECRET_ENTRY}
    ]
  },
  "permissions": {
    "deny": [
      "Write(//Users/${OWNER}/.claude/**)",
      "Edit(//Users/${OWNER}/.claude/**)",
      "Write(//usr/local/lib/claude-guard/**)",
      "Edit(//usr/local/lib/claude-guard/**)",
      "Write(//etc/claude/**)",
      "Edit(//etc/claude/**)",
      "Bash(sudo:*)"
    ]
  }
}
JSON
chown root:wheel "$MANAGED"
chmod 644 "$MANAGED"
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$MANAGED" \
  && echo "   managed-settings.json is valid JSON"

echo "== 5. proof =="
sudo -u "$OWNER" python3 -I "$HOOKS_SRC/tests/test-guard.py" | tail -2
echo "   -- what the guard cannot do, measured:"
sudo -u "$OWNER" python3 -I "$HOOKS_SRC/tests/test-guard-adversarial.py" | tail -4 | sed 's/^/   /'

echo "   -- the flag is out of the account's reach (an error here is the expected result):"
if sudo -u "$OWNER" touch "$FLAG_DIR/allow-secrets" 2>/dev/null; then
  echo "   REFUSED: $OWNER could create the bypass flag. The install did not take." >&2
  rm -f "$FLAG_DIR/allow-secrets"
  exit 1
fi
echo "   confirmed: $OWNER cannot create $FLAG_DIR/allow-secrets"

echo "   -- the guard is read-only for the account:"
if sudo -u "$OWNER" sh -c "echo x >> $LIB/guard-protection-integrity.sh" 2>/dev/null; then
  echo "   REFUSED: $OWNER could append to the guard. The install did not take." >&2
  exit 1
fi
echo "   confirmed: $OWNER cannot write $LIB/guard-protection-integrity.sh"

cat <<EOF

== installed ==

Lifting the protection now costs you a password, and nothing less:

    sudo touch /etc/claude/allow-secrets    # off
    sudo rm    /etc/claude/allow-secrets    # on again

Refused attempts are logged:  tail -f $LOG_DIR/integrity.log

Two things left for you, in an interactive session:
  1. Claude Code may ask you to approve the managed settings on first launch. Approve once.
  2. Remove the now-duplicated PreToolUse entry for block-secret-exposure.sh from
     ~/.claude/settings.json, so the hook does not run twice. That file stays yours.
EOF
