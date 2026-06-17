#compdef applicant applicant-backup applicant-calendar applicant-contacts applicant-cookbook applicant-docs applicant-gallery applicant-mail applicant-mcp applicant-memory applicant-notes applicant-personal applicant-preset applicant-research applicant-sessions applicant-signature applicant-skills applicant-tasks applicant-theme applicant-webhook
# Zsh tab-completion for the applicant umbrella + sub-CLIs.
#
# Drop in any directory on $fpath, e.g.:
#     fpath=(/path/to/applicant-ui/scripts/_completion $fpath)
#     autoload -U compinit; compinit
#
# Then `applicant <tab>` completes subcommands; `applicant mail <tab>`
# completes mail subcommands; `applicant-mail <tab>` works the same.

_applicant_scripts_dir() {
    local self="${(%):-%x}"
    while [[ -L "$self" ]]; do self="$(readlink "$self")"; done
    cd "${self:h}/.." && pwd
}

typeset -gA _applicant_subs

_applicant_refresh() {
    _applicant_subs=()
    local dir="$(_applicant_scripts_dir)"
    local py="$dir/../venv/bin/python"
    [[ -x "$py" ]] || py="$(command -v python3)"
    local f sub help_out commands
    for f in "$dir"/applicant-*; do
        [[ -x "$f" ]] || continue
        case "$f" in
            *.bak|*.pyc|*.pre-*) continue ;;
        esac
        sub="${${f:t}#applicant-}"
        help_out=$("$py" "$f" --help 2>/dev/null) || continue
        commands=$(echo "$help_out" | grep -oE '\{[a-z0-9_,-]+\}' | head -1 \
            | tr -d '{}' | tr ',' ' ')
        _applicant_subs[$sub]="$commands"
    done
}

_applicant() {
    [[ ${#_applicant_subs} -eq 0 ]] && _applicant_refresh

    local cmd="${words[1]}"

    if [[ "$cmd" == "applicant" ]]; then
        if (( CURRENT == 2 )); then
            local -a subs=(${(k)_applicant_subs} help)
            _describe 'subcommand' subs
            return
        fi
        local sub="${words[2]}"
        if [[ "$sub" == "help" ]] && (( CURRENT == 3 )); then
            local -a subs=(${(k)_applicant_subs})
            _describe 'subcommand' subs
            return
        fi
        if (( CURRENT == 3 )); then
            local -a sc=(${(s/ /)_applicant_subs[$sub]})
            _describe 'command' sc
            return
        fi
        return
    fi

    # applicant-foo <tab>
    local sub="${cmd#applicant-}"
    if (( CURRENT == 2 )); then
        local -a sc=(${(s/ /)_applicant_subs[$sub]})
        _describe 'command' sc
        return
    fi
}

_applicant "$@"
