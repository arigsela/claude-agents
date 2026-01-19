#!/usr/bin/env bash
# Claude Code Skills CLI
# Marketplace management for Claude Code skills
#
# Usage: ./skill-cli.sh <command> [options]
#
# Commands:
#   list              List installed skills
#   search <query>    Search skills by name/description/tags
#   info <name>       Show detailed skill information
#   add <source>      Install a skill from various sources
#   update [name]     Update a skill or check for updates
#   remove <name>     Remove an installed skill
#   validate [path]   Validate SKILL.md file
#   pack [path]       Create .skill bundle
#   help              Show this help message

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/skill-utils.sh"

# Help text
show_help() {
    cat << 'EOF'
Claude Code Skills CLI - Marketplace management for Claude Code skills

USAGE:
    skill <command> [options]

COMMANDS:
    list [--verbose|-v]           List installed skills
    search <query>                Search skills by name/description/tags
    info <skill-name>             Show detailed skill information
    add <source>[@version]        Install a skill
    update [skill-name]           Update a skill (or all if no name given)
    update --check                Check for available updates
    remove <skill-name>           Remove an installed skill
    validate [path]               Validate SKILL.md (current dir if no path)
    pack [path] [--output|-o dir] Create .skill bundle

INSTALL SOURCES:
    ./path/to/skill               Local directory
    ./skill-name.skill            Bundle file
    github:user/repo/path         GitHub repository
    skill-name                    From configured registry (future)

EXAMPLES:
    skill list
    skill list --verbose
    skill search "code review"
    skill info code-review
    skill add ./my-skill
    skill add ./my-skill.skill
    skill add github:user/repo/skills/my-skill
    skill update code-review
    skill update --check
    skill remove my-skill
    skill validate ./my-skill
    skill pack ./my-skill -o ./bundles

OPTIONS:
    -h, --help      Show this help message
    -v, --verbose   Show detailed output
    --version       Show version information

EOF
}

show_version() {
    echo "Claude Code Skills CLI v1.0.0"
}

# Main command dispatch
main() {
    if [[ $# -eq 0 ]]; then
        show_help
        exit 0
    fi

    local command="$1"
    shift

    # Initialize skills directory
    init_skills_dir

    case "$command" in
        list)
            local verbose="false"
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    -v|--verbose)
                        verbose="true"
                        shift
                        ;;
                    --all)
                        # Future: list from all registries
                        log_warning "--all not yet implemented"
                        shift
                        ;;
                    *)
                        log_error "Unknown option: $1"
                        exit 1
                        ;;
                esac
            done
            list_installed_skills "$verbose"
            ;;

        search)
            if [[ $# -eq 0 ]]; then
                log_error "Search query required"
                echo "Usage: skill search <query>"
                exit 1
            fi
            search_skills "$*"
            ;;

        info)
            if [[ $# -eq 0 ]]; then
                log_error "Skill name required"
                echo "Usage: skill info <skill-name>"
                exit 1
            fi
            show_skill_info "$1"
            ;;

        add|install)
            if [[ $# -eq 0 ]]; then
                log_error "Source required"
                echo "Usage: skill add <source>[@version]"
                exit 1
            fi
            local source="$1"
            local version=""

            # Parse @version suffix
            if [[ "$source" == *"@"* ]]; then
                version="${source##*@}"
                source="${source%@*}"
            fi

            install_skill "$source" "$version"
            ;;

        update)
            if [[ $# -eq 0 ]]; then
                # Update all
                log_info "Checking all skills for updates..."
                check_updates
            elif [[ "$1" == "--check" ]]; then
                check_updates
            else
                update_skill "$1"
            fi
            ;;

        remove|uninstall)
            if [[ $# -eq 0 ]]; then
                log_error "Skill name required"
                echo "Usage: skill remove <skill-name>"
                exit 1
            fi
            remove_skill "$1"
            ;;

        validate)
            local path="${1:-.}"
            validate_skill "$path"
            ;;

        pack|bundle)
            local path="${1:-.}"
            local output_dir="."

            shift || true
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    -o|--output)
                        output_dir="$2"
                        shift 2
                        ;;
                    *)
                        log_error "Unknown option: $1"
                        exit 1
                        ;;
                esac
            done

            pack_skill "$path" "$output_dir"
            ;;

        registry)
            # Future: registry management
            log_warning "Registry commands not yet implemented"
            log_info "Available subcommands: add, remove, list, sync"
            ;;

        help|-h|--help)
            show_help
            ;;

        version|--version)
            show_version
            ;;

        *)
            log_error "Unknown command: $command"
            echo "Run 'skill help' for usage information"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
