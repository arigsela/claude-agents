#!/usr/bin/env bash
# Claude Code hook: record this session's state on its tmux pane so pane borders and the
# status bar can show who is working, done, or waiting on the user.
#   agent-state-hook.sh prompt|notify|tool|stop   (hook JSON on stdin)
# Prints nothing (UserPromptSubmit output would be added to Claude's context) and always exits 0.

[ -n "${TMUX_PANE:-}" ] || exit 0          # not in tmux: nothing to label
command -v tmux >/dev/null 2>&1 || exit 0

event="${1:-}"
input=$(cat 2>/dev/null || true)
set_opt() { tmux set -p -t "$TMUX_PANE" "$1" "$2" >/dev/null 2>&1 || true; }
get_opt() { tmux show -pv -t "$TMUX_PANE" "$1" 2>/dev/null || true; }
field() { printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null || true; }
now=$(date +%H:%M)

case "$event" in
  prompt)
    # agents.sh send prefixes every message with "Orchestrator:"
    from=you
    case "$(field '.prompt' | head -c 40)" in Orchestrator:*) from=orchestrator ;; esac
    set_opt @state working; set_opt @from "$from"; set_opt @since "$now" ;;
  notify)
    msg="$(field '.message') $(field '.notification_type')"
    if printf '%s' "$msg" | grep -qi 'permission'; then
      set_opt @state needs-you; set_opt @since "$now"
    elif printf '%s' "$msg" | grep -qi 'waiting for your input\|idle'; then
      [ "$(get_opt @state)" = working ] || { set_opt @state done; }
    fi ;;
  tool)
    # a tool ran, so any permission prompt was answered
    [ "$(get_opt @state)" = needs-you ] && { set_opt @state working; set_opt @since "$now"; } ;;
  stop)
    set_opt @state done; set_opt @since "$now" ;;
esac
exit 0
