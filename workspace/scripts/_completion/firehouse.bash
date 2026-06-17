#!/usr/bin/env bash
# Tab-completion for the `firehouse` umbrella + every `firehouse-*` CLI.
#
# Source from your shell rc:
#     source /path/to/firehouse-ui/scripts/_completion/firehouse.bash
#
# Or wire it once per machine:
#     sudo install -m 644 firehouse.bash /etc/bash_completion.d/firehouse
#
# What it does:
#   - On the first word after `firehouse`, complete with the list of
#     subcommands (`mail`, `calendar`, ...).
#   - On subsequent words, complete with the subcommand's first-token
#     subcommands (`list`, `show`, ...) which we cache by parsing the
#     tool's own --help output. Updates lazily; refresh by running
#     `_firehouse_refresh_cache`.
#   - Same completion works for the individual `firehouse-foo` scripts.

_firehouse_scripts_dir() {
    # Resolve the scripts/ dir from the script that sources us. We assume
    # the user sourced the file directly out of scripts/_completion/.
    local self="${BASH_SOURCE[0]}"
    while [ -L "$self" ]; do self=$(readlink "$self"); done
    cd "$(dirname "$self")/.." && pwd
}

declare -A _FIREHOUSE_SUBS_CACHE=()

_firehouse_refresh_cache() {
    local dir="$(_firehouse_scripts_dir)"
    _FIREHOUSE_SUBS_CACHE=()
    # Prefer the project venv's Python so deps (bcrypt, sqlalchemy, ...)
    # resolve. Falls back to system `python3` for container installs.
    local py="$dir/../venv/bin/python"
    [ -x "$py" ] || py="$(command -v python3)"
    local f
    for f in "$dir"/firehouse-*; do
        [ -x "$f" ] || continue
        case "$f" in *.bak|*.pyc|*.pre-*) continue ;; esac
        local name="$(basename "$f")"
        local sub="${name#firehouse-}"
        local help_out
        help_out=$("$py" "$f" --help 2>/dev/null) || continue
        local commands
        commands=$(echo "$help_out" | grep -oE '\{[a-z0-9_,-]+\}' | head -1 \
            | tr -d '{}' | tr ',' ' ')
        _FIREHOUSE_SUBS_CACHE[$sub]="$commands"
    done
}

_firehouse_complete() {
    [ ${#_FIREHOUSE_SUBS_CACHE[@]} -eq 0 ] && _firehouse_refresh_cache

    local cur="${COMP_WORDS[COMP_CWORD]}"
    local cmd="${COMP_WORDS[0]}"

    # `firehouse <tab>` → list every subcommand
    if [ "$cmd" = "firehouse" ]; then
        if [ "$COMP_CWORD" -eq 1 ]; then
            local subs="${!_FIREHOUSE_SUBS_CACHE[@]} help"
            COMPREPLY=($(compgen -W "$subs" -- "$cur"))
            return 0
        fi
        # `firehouse foo <tab>` — complete with foo's own subcommands
        local sub="${COMP_WORDS[1]}"
        # `firehouse help <tab>` lists every subcommand
        if [ "$sub" = "help" ] && [ "$COMP_CWORD" -eq 2 ]; then
            COMPREPLY=($(compgen -W "${!_FIREHOUSE_SUBS_CACHE[*]}" -- "$cur"))
            return 0
        fi
        if [ "$COMP_CWORD" -eq 2 ]; then
            COMPREPLY=($(compgen -W "${_FIREHOUSE_SUBS_CACHE[$sub]}" -- "$cur"))
            return 0
        fi
        return 0
    fi

    # Direct `firehouse-foo <tab>` (no umbrella)
    local sub="${cmd#firehouse-}"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=($(compgen -W "${_FIREHOUSE_SUBS_CACHE[$sub]}" -- "$cur"))
        return 0
    fi
}

# Register the completion for every firehouse-* script + the umbrella.
complete -F _firehouse_complete firehouse
for f in "$(_firehouse_scripts_dir)"/firehouse-*; do
    [ -x "$f" ] || continue
    case "$f" in *.bak|*.pyc|*.pre-*) continue ;; esac
    complete -F _firehouse_complete "$(basename "$f")"
done
