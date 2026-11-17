# tmux-claude: start, or reattach to, a tmux session running Claude Code in a repo.
# Sourced from ~/.zshrc or ~/.bashrc. Works in zsh and bash.
#
#   tmux-claude <session> [repo] [prompt]
#
#   session  tmux session name, e.g. ifs-665
#   repo     a path, or a folder name under ~/git (default: current directory)
#   prompt   optional first message for Claude, e.g.
#            "Use tmux-orchestrator to spin up agents for the handovers in ~/git/a and ~/git/b"
#
# An existing session is reattached as-is; repo and prompt are ignored.
# When Claude exits, the pane drops to a shell instead of closing the session.

tmux-claude() {
  if [ $# -lt 1 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "usage: tmux-claude <session> [repo] [prompt]"
    echo "  repo: a path or a folder under ~/git (default: current directory)"
    echo "  prompt: optional first message for Claude"
    [ $# -ge 1 ]; return
  fi

  local session="$1" repo="${2:-$PWD}" prompt="${3:-}" dir cmd
  local claude_cmd="${TMUX_CLAUDE_CMD:-claude}"   # overridable for testing

  if tmux has-session -t "=$session" 2>/dev/null; then
    echo "tmux-claude: session '$session' already exists, reattaching"
  else
    if [ -d "$repo" ]; then dir="$repo"
    elif [ -d "$HOME/git/$repo" ]; then dir="$HOME/git/$repo"
    else echo "tmux-claude: no directory '$repo' (also tried ~/git/$repo)" >&2; return 1
    fi
    dir=$(cd "$dir" && pwd)

    cmd="$claude_cmd"
    [ -n "$prompt" ] && cmd="$claude_cmd $(printf '%q' "$prompt")"
    # trailing shell keeps the session alive after Claude exits
    tmux new-session -d -s "$session" -c "$dir" -n claude "$cmd; exec \${SHELL:-/bin/zsh} -l" || return
    echo "tmux-claude: started '$session' in $dir"
  fi

  if [ -n "${TMUX:-}" ]; then
    tmux switch-client -t "=$session"   # already inside tmux: switch instead of nesting
  else
    tmux attach -t "=$session"
  fi
}
