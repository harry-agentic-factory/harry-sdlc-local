#!/usr/bin/env bash
# Installe l'engine harry-sdlc-local dans ~/.claude (SYMLINKS vers la source versionnée).
# Idempotent. Ne touche PAS aux autres fichiers de ~/.claude (commands/agents tiers, profile, projects.json).
set -euo pipefail
ENG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLA="${CLAUDE_HOME:-$HOME/.claude}"
mkdir -p "$CLA"/agents "$CLA"/commands "$CLA"/workflows "$CLA"/sdlc

link() { ln -sfn "$1" "$2"; echo "  $(basename "$2") -> $1"; }

echo "Install harry-sdlc-local $(cat "$ENG/VERSION") -> $CLA"
for f in "$ENG"/claude/agents/*.md;    do link "$f" "$CLA/agents/$(basename "$f")";    done
for f in "$ENG"/claude/commands/*.md;  do link "$f" "$CLA/commands/$(basename "$f")";  done
for f in "$ENG"/claude/workflows/*.js; do link "$f" "$CLA/workflows/$(basename "$f")"; done
link "$ENG/claude/sdlc/harry.md" "$CLA/sdlc/harry.md"

# état par-utilisateur (jamais écrasé) : profil + registre projets
[ -f "$CLA/sdlc/profile" ] || printf 'dev\n' > "$CLA/sdlc/profile"
[ -f "$CLA/sdlc/projects.json" ] || printf '{\n  "projects": {}\n}\n' > "$CLA/sdlc/projects.json"

# commande `sdlc` (CLI de l'engine) — dans un dir DÉJÀ dans le PATH (pas de modif shell si possible)
chmod +x "$ENG/bin/sdlc"
target=""
for d in /usr/local/bin /opt/homebrew/bin "$HOME/.local/bin"; do
  case ":${PATH:-}:" in *":$d:"*) [ -w "$d" ] && { target="$d"; break; } ;; esac
done
if [ -z "$target" ]; then          # aucun dir du PATH inscriptible -> fallback ~/.local/bin + hint
  target="$HOME/.local/bin"; mkdir -p "$target"
  case ":${PATH:-}:" in *":$target:"*) : ;; *)
    RC="${ZDOTDIR:-$HOME}/.zshrc"
    grep -qF "harry-sdlc-local (sdlc CLI)" "$RC" 2>/dev/null || \
      printf '\n# harry-sdlc-local (sdlc CLI)\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
    echo "  PATH ajouté à $RC — 'source $RC' ou nouveau terminal." ;;
  esac
fi
ln -sfn "$ENG/bin/sdlc" "$target/sdlc"
echo "  sdlc -> $target/sdlc"

echo "OK. (profil + projects.json préservés)"
