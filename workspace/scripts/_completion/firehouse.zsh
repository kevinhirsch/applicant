#compdef firehouse firehouse-backup firehouse-calendar firehouse-contacts firehouse-cookbook firehouse-docs firehouse-gallery firehouse-mail firehouse-mcp firehouse-memory firehouse-notes firehouse-personal firehouse-preset firehouse-research firehouse-sessions firehouse-signature firehouse-skills firehouse-tasks firehouse-theme firehouse-webhook
# Zsh tab-completion for the firehouse umbrella + sub-CLIs.
#
# Drop in any directory on $fpath, e.g.:
#     fpath=(/path/to/firehouse-ui/scripts/_completion $fpath)
#     autoload -U compinit; compinit
#
# Then `firehouse <tab>` completes subcommands; `firehouse mail <tab>`
# completes mail subcommands; `firehouse-mail <tab>` works the same.

_firehouse_scripts_dir() {
    local self="${(%):-%x}"
    while [[ -L "$self" ]]; do self="$(readlink "$self")"; done
    cd "${self:h}/.." && pwd
}

typeset -gA _firehouse_subs

_firehouse_refresh() {
    _firehouse_subs=()
    local dir="$(_firehouse_scripts_dir)"
    local py="$dir/../venv/bin/python"
    [[ -x "$py" ]] || py="$(command -v python3)"
    local f sub help_out commands
    for f in "$dir"/firehouse-*; do
        [[ -x "$f" ]] || continue
        case "$f" in
            *.bak|*.pyc|*.pre-*) continue ;;
        esac
        sub="${${f:t}#firehouse-}"
        help_out=$("$py" "$f" --help 2>/dev/null) || continue
        commands=$(echo "$help_out" | grep -oE '\{[a-z0-9_,-]+\}' | head -1 \
            | tr -d '{}' | tr ',' ' ')
        _firehouse_subs[$sub]="$commands"
    done
}

_firehouse() {
    [[ ${#_firehouse_subs} -eq 0 ]] && _firehouse_refresh

    local cmd="${words[1]}"

    if [[ "$cmd" == "firehouse" ]]; then
        if (( CURRENT == 2 )); then
            local -a subs=(${(k)_firehouse_subs} help)
            _describe 'subcommand' subs
            return
        fi
        local sub="${words[2]}"
        if [[ "$sub" == "help" ]] && (( CURRENT == 3 )); then
            local -a subs=(${(k)_firehouse_subs})
            _describe 'subcommand' subs
            return
        fi
        if (( CURRENT == 3 )); then
            local -a sc=(${(s/ /)_firehouse_subs[$sub]})
            _describe 'command' sc
            return
        fi
        return
    fi

    # firehouse-foo <tab>
    local sub="${cmd#firehouse-}"
    if (( CURRENT == 2 )); then
        local -a sc=(${(s/ /)_firehouse_subs[$sub]})
        _describe 'command' sc
        return
    fi
}

_firehouse "$@"
