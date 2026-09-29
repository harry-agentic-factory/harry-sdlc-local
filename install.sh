#!/usr/bin/env bash
# install.sh -- install the harry-sdlc engine for the current user.
#
#   install.sh vX.Y.Z        install (or switch to) a released version: detached clone at the tag under
#                            $HARRY_SDLC_HOME/vX.Y.Z, refused unless the tag equals "v" + VERSION of the clone
#   install.sh --dev <path>  use a working copy of the engine as the active version (explicit dev mode)
#
# Layout:  $HARRY_SDLC_HOME/{vX.Y.Z/, current -> vX.Y.Z | <dev path>}
#          $CLAUDE_HOME/{agents,commands,workflows,skills,sdlc/harry.md} and <bin dir>/sdlc
#          are symlinks whose value is literally $HARRY_SDLC_HOME/current/...
# Switching or rolling back = moving `current` (atomic rename); links never change after that.
# User state is preserved: projects.json is created only when missing; profile, locks/, agent_runs.log,
# settings.json and any third-party file or link are never read nor written.
#
# Environment: HARRY_SDLC_HOME (default ~/.local/share/harry-sdlc), HARRY_SDLC_REPO (default: the public
# GitHub repository), CLAUDE_HOME (default ~/.claude). Compatible with bash 3.2.
set -euo pipefail
export GIT_TERMINAL_PROMPT=0

SELF="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HSH="${HARRY_SDLC_HOME:-$HOME/.local/share/harry-sdlc}"
REPO="${HARRY_SDLC_REPO:-https://github.com/harry-agentic-factory/harry-sdlc-local}"
CLA="${CLAUDE_HOME:-$HOME/.claude}"
ZSHRC_MARKER="# harry-sdlc-local (sdlc CLI)"

usage() {
  cat >&2 <<'EOF'
usage: install.sh vX.Y.Z          install or switch to a released version (git tag)
       install.sh --dev <path>    use a working copy of the engine (dev mode)
EOF
  exit 2
}
die() { echo "install.sh: $*" >&2; exit 1; }
warn() { echo "install.sh: $*" >&2; }

# ---- 1. arguments (nothing is written before they are valid) ----------------------------------------
tag_re='^v[0-9]+\.[0-9]+\.[0-9]+$'
mode=""
tag=""
dev=""
if [ $# -eq 1 ] && [[ "$1" =~ $tag_re ]]; then
  mode=release
  tag=$1
elif [ $# -eq 2 ] && [ "$1" = "--dev" ]; then
  [ -d "$2" ] || { echo "install.sh: --dev path '$2' is not a directory" >&2; usage; }
  dev="$(cd -P "$2" && pwd)"
  if [ ! -f "$dev/VERSION" ] || [ ! -f "$dev/bin/sdlc" ] || [ ! -d "$dev/claude" ]; then
    echo "install.sh: --dev path '$dev' is not an engine copy (VERSION, bin/sdlc, claude/)" >&2
    usage
  fi
  mode=dev
else
  usage
fi
case "$HSH" in /*) ;; *) echo "install.sh: HARRY_SDLC_HOME must be an absolute path" >&2; usage ;; esac
case "$CLA" in /*) ;; *) echo "install.sh: CLAUDE_HOME must be an absolute path" >&2; usage ;; esac

# ---- 2./3. the version directory ----------------------------------------------------------------------
STAGE=""
drop_stage() {
  if [ -n "$STAGE" ]; then
    case "$STAGE" in
      "$HSH"/.staging.*) rm -rf "$STAGE" ;;
      *) echo "install.sh: refusing to remove unexpected path '$STAGE'" >&2; exit 1 ;;
    esac
    STAGE=""
  fi
}
trap drop_stage EXIT

stage_clone() {  # clone $tag into $STAGE/src and check it; returns non-zero on refusal
  if ! git clone --quiet --depth 1 --branch "$tag" -c advice.detachedHead=false "$REPO" "$STAGE/src"; then
    warn "clone_failed: cannot clone '$tag' from $REPO"
    return 1
  fi
  if ! git -C "$STAGE/src" rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
    warn "not_a_tag: '$tag' is not a tag of $REPO"
    return 1
  fi
  if git -C "$STAGE/src" symbolic-ref -q HEAD >/dev/null; then
    warn "not_a_tag: '$tag' resolved to a branch of $REPO"
    return 1
  fi
  "$SELF/scripts/check-tag-version.sh" "$tag" "$STAGE/src" || return 1
}

if [ "$mode" = release ]; then
  if [ -e "$HSH/$tag" ]; then
    # Already installed: read-only consistency check, no clone, no fetch, no write inside.
    "$SELF/scripts/check-tag-version.sh" "$tag" "$HSH/$tag" >/dev/null \
      || die "installed $HSH/$tag is inconsistent with its tag"
  else
    mkdir -p "$HSH"
    STAGE="$(mktemp -d "$HSH/.staging.XXXXXX")"
    if ! stage_clone; then
      drop_stage
      die "refused: $tag (nothing changed)"
    fi
    mv "$STAGE/src" "$HSH/$tag"
    rmdir "$STAGE"
    STAGE=""
    echo "installed $tag -> $HSH/$tag"
  fi
  want="$tag"
else
  mkdir -p "$HSH"
  want="$dev"
fi

# ---- 4. switch `current` atomically, only when it changes ---------------------------------------------
current_value="$(readlink "$HSH/current" 2>/dev/null || true)"
if [ "$current_value" != "$want" ]; then
  tmp_link="$HSH/.current.$$"
  ln -sfn "$want" "$tmp_link"
  python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$tmp_link" "$HSH/current"
  echo "current -> $want"
fi
ACTIVE="$HSH/current"

# ---- 5. managed links -----------------------------------------------------------------------------------
mkdir -p "$CLA/agents" "$CLA/commands" "$CLA/workflows" "$CLA/skills" "$CLA/sdlc"

# engine_sdlc_link <link path>: 0 when the link value is <root>/bin/sdlc and <root> (resolved from the link's
# folder when the value is relative) is an engine copy, with VERSION and claude/. A link of a package manager
# (Homebrew: ../Cellar/<formula>/<v>/bin/sdlc) has the same suffix but no such root: it is never managed.
engine_sdlc_link() {
  local value root
  [ -L "$1" ] || return 1
  value="$(readlink "$1")"
  case "$value" in */bin/sdlc) ;; *) return 1 ;; esac
  root="${value%/bin/sdlc}"
  case "$root" in /*) ;; *) root="$(dirname "$1")/$root" ;; esac
  [ -f "$root/VERSION" ] && [ -d "$root/claude" ]
}

# manage_link <link path> <value> <old-mode suffix>
manage_link() {
  local dst=$1 value=$2 suffix=$3 existing
  if [ -L "$dst" ]; then
    existing="$(readlink "$dst")"
    [ "$existing" = "$value" ] && return 0
    if [ "$suffix" = bin/sdlc ] && ! engine_sdlc_link "$dst"; then
      warn "skipped (not managed, not an engine copy): $dst -> $existing"
      return 0
    fi
    case "$existing" in
      *"/$suffix")
        ln -sfn "$value" "$dst"
        echo "migrated $dst"
        ;;
      *) warn "skipped (not managed): $dst" ;;
    esac
  elif [ -e "$dst" ]; then
    warn "skipped (not managed): $dst"
  else
    ln -s "$value" "$dst"
    echo "linked $dst"
  fi
}

link_kind() {  # link_kind <kind> <pattern>: every entry of the active version
  local kind=$1 pattern=$2 src name
  for src in "$ACTIVE/claude/$kind"/$pattern; do
    [ -e "$src" ] || continue
    name="$(basename "$src")"
    manage_link "$CLA/$kind/$name" "$ACTIVE/claude/$kind/$name" "claude/$kind/$name"
  done
}
link_kind agents '*.md'
link_kind commands '*.md'
link_kind workflows '*.js'
link_kind skills '*/'
[ -e "$ACTIVE/claude/sdlc/harry.md" ] \
  && manage_link "$CLA/sdlc/harry.md" "$ACTIVE/claude/sdlc/harry.md" "claude/sdlc/harry.md"

# Old-mode links (value ending with /claude/<kind>/<name>) whose name is not in the active version: reported.
for kind in agents commands workflows skills sdlc; do
  for l in "$CLA/$kind"/*; do
    [ -L "$l" ] || continue
    name="$(basename "$l")"
    value="$(readlink "$l")"
    case "$value" in "$ACTIVE"/*) continue ;; esac
    case "$value" in
      *"/claude/$kind/$name")
        if [ ! -e "$ACTIVE/claude/$kind/$name" ]; then
          warn "stale (not in $want): $l"
        fi
        ;;
    esac
  done
done

# ---- 6. the sdlc command ----------------------------------------------------------------------------------
in_path() { case ":${PATH:-}:" in *":$1:"*) return 0 ;; esac; return 1; }
bin_candidates="/usr/local/bin /opt/homebrew/bin $HOME/.local/bin"
bin_dir=""
foreign=" "
for d in $bin_candidates; do  # a directory of the PATH already holding a managed sdlc link
  in_path "$d" || continue
  if engine_sdlc_link "$d/sdlc"; then bin_dir=$d; break; fi
done
if [ -z "$bin_dir" ]; then  # else the first writable directory of the PATH without a foreign sdlc
  for d in $bin_candidates; do
    if [ -e "$d/sdlc" ] || [ -L "$d/sdlc" ]; then
      if in_path "$d"; then
        warn "skipped (not managed, not an engine copy): $d/sdlc"
        foreign="$foreign $d "
      fi
      continue
    fi
    if in_path "$d" && [ -d "$d" ] && [ -w "$d" ]; then bin_dir=$d; break; fi
  done
fi
if [ -z "$bin_dir" ]; then  # else ~/.local/bin, added to the PATH of zsh once
  bin_dir="$HOME/.local/bin"
  mkdir -p "$bin_dir"
  if ! in_path "$bin_dir"; then
    rc="${ZDOTDIR:-$HOME}/.zshrc"
    if ! grep -qF "$ZSHRC_MARKER" "$rc" 2>/dev/null; then
      printf '\n%s\nexport PATH="$HOME/.local/bin:$PATH"\n' "$ZSHRC_MARKER" >> "$rc"
      echo "PATH line added to $rc (open a new terminal or source it)"
    fi
  fi
fi
case "$foreign" in
  *" $bin_dir "*) ;;  # foreign sdlc already reported, left intact
  *) manage_link "$bin_dir/sdlc" "$ACTIVE/bin/sdlc" "bin/sdlc" ;;
esac
# the tracker command (issue tracker <-> SDLC bridge) lives next to sdlc
manage_link "$bin_dir/tracker" "$ACTIVE/bin/tracker" "bin/tracker"

# ---- 7. orphans: links through current whose target no longer exists (links only, never recursive) -------
for kind in agents commands workflows skills sdlc; do
  for l in "$CLA/$kind"/*; do
    [ -L "$l" ] || continue
    case "$(readlink "$l")" in
      "$ACTIVE"/*)
        if [ ! -e "$l" ]; then
          rm "$l"
          echo "removed orphan $l"
        fi
        ;;
    esac
  done
done

# ---- 8. per-user state ------------------------------------------------------------------------------------
[ -e "$CLA/sdlc/projects.json" ] || printf '{\n  "projects": {}\n}\n' > "$CLA/sdlc/projects.json"

# ---- 9. active version -------------------------------------------------------------------------------------
PYTHONDONTWRITEBYTECODE=1 "$ACTIVE/bin/sdlc" --version
