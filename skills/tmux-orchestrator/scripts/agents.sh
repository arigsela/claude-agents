#!/usr/bin/env bash
# Manage Claude Code agents that run as tmux panes beside an orchestrator session.
# Run "bash agents.sh help" for commands. Written for macOS /bin/bash 3.2 (no associative arrays).
set -euo pipefail

ORCH_PANE="${ORCH_PANE:-${TMUX_PANE:-}}"
AGENT_CMD="${AGENT_CMD:-claude}"   # overridable so the script can be tested without starting Claude
TAB=$'\t'

die() { echo "agents.sh: $*" >&2; exit 1; }

need_orch() {
  command -v tmux >/dev/null || die "tmux is not installed"
  [ -n "$ORCH_PANE" ] || die "not inside tmux and ORCH_PANE is unset. The user starts the orchestrator with: tmux new -A -s <session> -c <dir>, then claude --continue. From outside tmux, pass ORCH_PANE=%<id> (find it with: tmux list-panes -a -F '#{pane_id} #{session_name} #{b:pane_current_path}')."
  tmux display -p -t "$ORCH_PANE" '#{pane_id}' >/dev/null 2>&1 || die "orchestrator pane $ORCH_PANE does not exist"
  ORCH_SESSION=$(tmux display -p -t "$ORCH_PANE" '#{session_name}')
  ORCH_WIN=$(tmux display -p -t "$ORCH_PANE" '#{session_name}:#{window_id}')
}

# pane_id, name, window, command, dead, path for every pane in the session except the orchestrator's
agent_rows() {
  tmux list-panes -s -t "$ORCH_SESSION" \
    -F "#{pane_id}${TAB}#{?@agent,#{@agent},#{b:pane_current_path}}${TAB}#{window_name}${TAB}#{pane_current_command}${TAB}#{pane_dead}${TAB}#{pane_current_path}" |
    awk -F'\t' -v o="$ORCH_PANE" '$1 != o'
}

pane_of() {
  local name="$1" ids count
  case "$name" in
    %*)
      tmux display -p -t "$name" '#{pane_id}' >/dev/null 2>&1 || die "no pane $name"
      [ "$name" != "$ORCH_PANE" ] || die "$name is the orchestrator's own pane"
      echo "$name"; return ;;
  esac
  ids=$(agent_rows | awk -F'\t' -v n="$name" '$2 == n {print $1}')
  [ -n "$ids" ] || die "no agent pane named '$name'. Run: bash agents.sh list"
  count=$(printf '%s\n' "$ids" | grep -c .)
  [ "$count" = 1 ] || die "$count panes are named '$name' ($(echo $ids)). Label one with: bash agents.sh name <pane_id> <new-name>"
  echo "$ids"
}

# One of: dead, shell, trust, permission, working, idle. Read from the bottom of the screen.
pane_state() {
  local id="$1" cmd screen
  [ "$(tmux display -p -t "$id" '#{pane_dead}')" = 1 ] && { echo dead; return; }
  cmd=$(tmux display -p -t "$id" '#{pane_current_command}')
  case "$cmd" in
    zsh|bash|sh|fish|-zsh|-bash|login)
      # a shell with no child process is at its prompt; with a child it is running something
      pgrep -P "$(tmux display -p -t "$id" '#{pane_pid}')" >/dev/null 2>&1 || { echo shell; return; } ;;
  esac
  # visible screen only: scrollback keeps stale spinner lines from earlier redraws
  screen=$(tmux capture-pane -p -J -t "$id" 2>/dev/null | grep -v '^[[:space:]]*$' | tail -n 15 || true)
  if grep -qE "Do you trust|trust this folder|Claude Code'll be able to read" <<<"$screen"; then echo trust; return; fi
  if grep -qE 'Do you want to (proceed|make this edit|create|allow|run)|Esc to cancel|Enter to confirm' <<<"$screen"; then echo permission; return; fi
  # state recorded by agent-state-hook.sh, when the agent's Claude Code has the hooks loaded
  case "$(tmux show -pv -t "$id" @state 2>/dev/null || true)" in
    needs-you) echo permission; return ;;
    done) echo idle; return ;;
    working)
      # an interrupt (Esc) fires no Stop hook, so trust the screen over a stale "working"
      grep -qE 'Interrupted · What should Claude do' <<<"$screen" && { echo idle; return; }
      echo working; return ;;
  esac
  if grep -qE '…[^)]*\([^)]*([0-9]+s|tokens)|esc to interrupt' <<<"$screen"; then echo working
  else echo idle; fi
}

clear_hook_state() { tmux set -pu -t "$1" @state 2>/dev/null; tmux set -pu -t "$1" @from 2>/dev/null; tmux set -pu -t "$1" @since 2>/dev/null; true; }

# Pane header banner, background colored by state so each agent's top edge is unmistakable:
# yellow "● aurora · working for orchestrator · 09:14", red "! ... needs you", green "✓ ... done", grey when no state yet
BORDER_FMT='#{?#{==:#{@state},working},#[bg=colour220#,fg=colour16#,bold],#{?#{==:#{@state},needs-you},#[bg=colour196#,fg=colour231#,bold],#{?#{==:#{@state},done},#[bg=colour28#,fg=colour231#,bold],#[bg=colour240#,fg=colour255#,bold]}}} #{?#{==:#{@state},working},● ,#{?#{==:#{@state},needs-you},! ,#{?#{==:#{@state},done},✓ ,}}}#{?@agent,#{@agent},#{b:pane_current_path}}#{?@state, · #{?#{==:#{@state},needs-you},needs you,#{@state}}#{?#{==:#{@state},working}, for #{@from},} · #{@since},} #[default]'
# Border lines take the same state color; the focused pane's frame stays cyan
BORDER_STYLE='#{?#{==:#{@state},working},fg=colour220,#{?#{==:#{@state},needs-you},fg=colour196,#{?#{==:#{@state},done},fg=colour28,fg=colour244}}}'
# Status bar: one symbol per agent pane in every window, on a dark segment so it reads on any status-style.
# ● working (yellow), ! needs you (red), ✓ done (green), ○ no hook data yet (grey)
STATUS_FMT='#[bg=colour235#,fg=colour250] agents #{W:#{P:#{?#{==:#{@agent},orchestrator},,#{?#{==:#{@state},working},#[fg=colour220#,bold]● ,#{?#{==:#{@state},needs-you},#[fg=colour196#,bold]! ,#{?#{==:#{@state},done},#[fg=colour46#,bold]✓ ,#[fg=colour244#,nobold]○ }}}#[nobold]}}}#[default] %H:%M '

orch_name() { tmux show -v -t "$ORCH_SESSION" @orch_name 2>/dev/null || true; }

# Text on Claude's input line, if any. It is either a grey suggestion or the user's draft;
# a capture cannot tell them apart, so callers refuse unless --force.
input_text() {
  { tmux capture-pane -p -J -t "$1" 2>/dev/null | grep -E '^❯' | tail -n 1 | sed -E 's/^❯[[:space:]]*//; s/[[:space:]]+$//'; } || true
}

refuse_if_input() {  # <pane_id> <name> <force>
  local text; text=$(input_text "$1")
  [ -z "$text" ] || [ "$3" = "--force" ] ||
    die "$2's input line shows \"$text\". If that is a grey suggestion, rerun with --force. If it is the user's unsent draft, ask them first."
}

default_prompt() {
  local orch="$1" who="the orchestrator"
  [ -n "$orch" ] && who="the orchestrator session $orch"
  printf '%s' "Read HANDOVER.md in this directory and follow it. Report to $who at every checkpoint: first load SendMessage with ToolSearch (query select:SendMessage) and send the report. If SendMessage is unavailable or fails, print the checkpoint block and wait at your prompt; the orchestrator reads your pane. Never answer permission prompts on the user's behalf."
}

launch_cmd() {  # a single command, so the shell execs it and tmux reports Claude as the pane's command
  printf '%s %s' "$AGENT_CMD" "$(printf '%q' "$1")"
}

cmd_layout() {
  local first
  first=$(tmux list-panes -t "$ORCH_WIN" -F '#{pane_id}' | head -1)
  [ "$first" = "$ORCH_PANE" ] || tmux swap-pane -d -s "$ORCH_PANE" -t "$first"
  tmux set -p -t "$ORCH_PANE" @agent orchestrator
  tmux set -w -t "$ORCH_WIN" pane-border-status top
  tmux set -w -t "$ORCH_WIN" pane-border-format "$BORDER_FMT"
  # thick lines in each agent's state color and a cyan frame on the focused pane.
  # Backgrounds stay the terminal's own: a tmux bg tint on inactive panes clashes with the theme
  # and washes out Claude's text colors.
  tmux set -w -t "$ORCH_WIN" pane-border-lines heavy
  tmux set -w -t "$ORCH_WIN" pane-border-style "$BORDER_STYLE"
  tmux set -w -t "$ORCH_WIN" pane-active-border-style 'fg=colour45'
  tmux set -w -t "$ORCH_WIN" window-style 'bg=default'
  tmux set -w -t "$ORCH_WIN" window-active-style 'bg=default'
  tmux set -t "$ORCH_SESSION" status-right "$STATUS_FMT"
  tmux set -t "$ORCH_SESSION" status-right-length 80
  tmux set -t "$ORCH_SESSION" status-interval 2
  tmux set -w -t "$ORCH_WIN" main-pane-width 50%
  tmux set -w -t "$ORCH_WIN" remain-on-exit on   # a closed agent leaves a dead pane that restart can reuse
  tmux select-layout -t "$ORCH_WIN" main-vertical >/dev/null
  echo "layout: orchestrator left, $(tmux list-panes -t "$ORCH_WIN" | wc -l | tr -d ' ') panes in window $ORCH_WIN"
}

cmd_init() {
  local name="${1:-}"
  [ -n "$name" ] && tmux set -t "$ORCH_SESSION" @orch_name "$name"
  cmd_layout
  echo "session: $ORCH_SESSION  orchestrator pane: $ORCH_PANE  orchestrator name: $(orch_name)"
  echo "user reattaches with: tmux new -A -s $ORCH_SESSION"
}

cmd_spawn() {
  local name="" dir="" tab=0 prompt="" id
  while [ $# -gt 0 ]; do
    case "$1" in
      --tab) tab=1; shift ;;
      --prompt) prompt="$2"; shift 2 ;;
      *) if [ -z "$name" ]; then name="$1"; elif [ -z "$dir" ]; then dir="$1"; else die "unexpected argument: $1"; fi; shift ;;
    esac
  done
  [ -n "$name" ] && [ -n "$dir" ] || die "usage: spawn <name> <dir> [--tab] [--prompt TEXT]"
  dir="${dir/#\~/$HOME}"
  [ -d "$dir" ] || die "no such directory: $dir"
  if agent_rows | awk -F'\t' -v n="$name" '$2 == n {f=1} END {exit !f}'; then die "an agent named '$name' already exists. Use restart, or pick another name."; fi
  [ -n "$prompt" ] || prompt=$(default_prompt "$(orch_name)")
  if [ "$tab" = 1 ]; then
    id=$(tmux new-window -d -t "$ORCH_SESSION:" -n "$name" -c "$dir" -P -F '#{pane_id}' "$(launch_cmd "$prompt")")
    tmux set -w -t "$id" remain-on-exit on
    tmux set -w -t "$id" pane-border-status top
    tmux set -w -t "$id" pane-border-format "$BORDER_FMT"
  else
    tmux set -w -t "$ORCH_WIN" remain-on-exit on
    id=$(tmux split-window -d -h -t "$ORCH_PANE" -c "$dir" -P -F '#{pane_id}' "$(launch_cmd "$prompt")") ||
      die "no room for another pane. Use --tab, or make the terminal bigger."
  fi
  tmux set -p -t "$id" @agent "$name"
  tmux set -p -t "$id" @prompt "$prompt"
  tmux set -p -t "$id" @dir "$dir"
  [ "$tab" = 1 ] || cmd_layout >/dev/null
  echo "spawned $name as $id in $dir"
  echo "A folder Claude has not seen before opens on a trust prompt that only the user may answer. Check with: bash agents.sh status"
}

cmd_name() {
  [ $# = 2 ] || die "usage: name <pane_id> <name>"
  local id; id=$(pane_of "$1")
  tmux set -p -t "$id" @agent "$2"
  echo "$id is now '$2'"
}

cmd_gather() {  # pull agent panes from other windows into the orchestrator's window
  local id win moved=0
  while IFS="$TAB" read -r id _ win _ _ _; do
    [ "$(tmux display -p -t "$id" '#{session_name}:#{window_id}')" = "$ORCH_WIN" ] && continue
    tmux join-pane -d -s "$id" -t "$ORCH_PANE" 2>/dev/null || { echo "no room for $id ($win); left as a tab"; continue; }
    tmux set -p -t "$id" @agent "$(tmux display -p -t "$id" '#{?@agent,#{@agent},#{b:pane_current_path}}')"
    moved=$((moved + 1))
  done < <(agent_rows)
  echo "moved $moved pane(s) into the orchestrator window"
  cmd_layout
}

cmd_list() {
  local id name win cmd dead path detail
  printf '%-22s %-5s %-14s %-11s %-24s %s\n' NAME PANE WINDOW STATE DETAIL DIR
  while IFS="$TAB" read -r id name win cmd dead path; do
    # hook detail: who sent the current request and since when
    detail=$(tmux display -p -t "$id" '#{?@state,#{@state}#{?#{==:#{@state},working}, for #{@from},} since #{@since},no hooks}')
    printf '%-22s %-5s %-14s %-11s %-24s %s\n' "$name" "$id" "$win" "$(pane_state "$id")" "$detail" "${path/#$HOME/~}"
  done < <(agent_rows)
}

cmd_peek() {
  local id lines="${2:-40}"
  id=$(pane_of "${1:?usage: peek <name> [lines]}")
  tmux capture-pane -p -J -t "$id" -S "-$((lines * 2))" | grep -v '^[[:space:]]*$' | tail -n "$lines"
}

cmd_send() {
  local name="${1:?usage: send <name> [--force] <message>}" force="" id st msg
  shift; [ "${1:-}" = "--force" ] && { force=--force; shift; }
  [ $# -gt 0 ] || die "usage: send <name> [--force] <message>"
  id=$(pane_of "$name"); st=$(pane_state "$id")
  case "$st" in
    trust|permission) die "$name is at a $st prompt. That answer belongs to the user: tell them, or run 'bash agents.sh focus $name' to put their keyboard there." ;;
    shell|dead) die "$name is not running Claude ($st). Run: bash agents.sh restart $name" ;;
  esac
  refuse_if_input "$id" "$name" "$force"
  # One line, prefixed so the agent knows the source and Claude never reads it as a / or ! command
  msg="Orchestrator: $(printf '%s' "$*" | tr '\n' ' ')"
  case "$msg" in *';') msg="$msg " ;; esac
  tmux send-keys -t "$id" -l -- "$msg"
  sleep 0.5   # a separate Enter, so Claude does not swallow it as part of a paste
  tmux send-keys -t "$id" Enter
  sleep 1
  echo "sent to $name ($st before sending). Bottom of its pane now:"
  tmux capture-pane -p -J -t "$id" -S -15 | grep -v '^[[:space:]]*$' | tail -n 6
}

cmd_restart() {
  local name="${1:?usage: restart <name> [--fresh]}" fresh="${2:-}" id st prompt dir
  id=$(pane_of "$name"); st=$(pane_state "$id")
  dir=$(tmux show -pv -t "$id" @dir 2>/dev/null || true)
  [ -n "$dir" ] || dir=$(tmux display -p -t "$id" '#{pane_current_path}')
  prompt=$(tmux show -pv -t "$id" @prompt 2>/dev/null || true)
  [ -n "$prompt" ] || prompt=$(default_prompt "$(orch_name)")
  case "$st" in shell|dead) clear_hook_state "$id" ;; esac
  case "$st" in
    shell)
      if [ "$fresh" = "--fresh" ]; then tmux send-keys -t "$id" -l -- "$AGENT_CMD $(printf '%q' "$prompt")"
      else tmux send-keys -t "$id" -l -- "$AGENT_CMD --continue"; fi
      tmux send-keys -t "$id" Enter ;;
    dead)
      if [ "$fresh" = "--fresh" ]; then tmux respawn-pane -t "$id" -c "$dir" "$(launch_cmd "$prompt")"
      else tmux respawn-pane -t "$id" -c "$dir" "$AGENT_CMD --continue"; fi ;;
    *) die "$name is still running Claude ($st). Stop it first: bash agents.sh stop $name" ;;
  esac
  echo "restarted $name in $id ($([ "$fresh" = "--fresh" ] && echo 'new conversation from its launch prompt' || echo 'claude --continue'))"
}

cmd_focus() {
  local id; id=$(pane_of "${1:?usage: focus <name>}")
  tmux select-window -t "$id"; tmux select-pane -t "$id"
  echo "user's keyboard is now in $1. Ctrl-b then z zooms it; Ctrl-b then an arrow key moves back."
}

cmd_break() {
  local name="${1:?usage: break <name>}" id; id=$(pane_of "$name")
  tmux break-pane -d -s "$id" -n "$name"
  echo "$name moved to its own tab"
}

cmd_stop() {
  local target="${1:?usage: stop <name>|--all [--force]}" force="${2:-}" id name st rows
  if [ "$target" = "--all" ]; then rows=$(agent_rows | cut -f1,2); else id=$(pane_of "$target"); rows="$id$TAB$target"; fi
  while IFS="$TAB" read -r id name; do
    [ -n "$id" ] || continue
    st=$(pane_state "$id")
    case "$st" in
      shell|dead) echo "$name: already stopped ($st)"; continue ;;
      trust|permission) echo "$name: skipped, waiting on a $st prompt the user must answer"; continue ;;
      working) [ "$force" = "--force" ] || { echo "$name: skipped, still working (add --force to stop anyway)"; continue; } ;;
    esac
    if [ -n "$(input_text "$id")" ] && [ "$force" != "--force" ]; then
      echo "$name: skipped, its input line has text (suggestion or the user's draft); peek it, then stop $name --force"; continue
    fi
    tmux send-keys -t "$id" -l -- "/exit"; sleep 0.5; tmux send-keys -t "$id" Enter
    echo "$name: sent /exit"
  done <<<"$rows"
}

cmd_kill() {
  local id; id=$(pane_of "${1:?usage: kill <name>}")
  [ "$(pane_state "$id")" = shell ] || [ "$(pane_state "$id")" = dead ] || die "$1 is still running Claude. Run 'bash agents.sh stop $1' first."
  tmux kill-pane -t "$id"; echo "closed $1's pane"
}

snapshot() {
  local id name
  agent_rows | cut -f1,2 | while IFS="$TAB" read -r id name; do printf '%s\t%s\t%s\n' "$id" "$name" "$(pane_state "$id")"; done
}

cmd_watch() {  # block until an agent needs attention; run it in the background to get notified
  local timeout=1800 interval=10 prev cur changes start
  while [ $# -gt 0 ]; do
    case "$1" in --timeout) timeout="$2"; shift 2 ;; --interval) interval="$2"; shift 2 ;; *) die "unknown option $1" ;; esac
  done
  prev=$(snapshot); start=$(date +%s)
  while :; do
    sleep "$interval"
    cur=$(snapshot)
    changes=$(awk -F'\t' '
      NR == FNR { p[$1] = $3; n[$1] = $2; next }
      { seen[$1] = 1
        if (!($1 in p)) print $2 ": new pane (" $3 ")"
        else if (p[$1] != $3 && $3 ~ /^(idle|permission|trust|shell|dead)$/) print $2 ": " p[$1] " -> " $3 }
      END { for (i in p) if (!(i in seen)) print n[i] ": pane closed" }' \
      <(printf '%s\n' "$prev") <(printf '%s\n' "$cur"))
    if [ -n "$changes" ]; then echo "$changes"; return 0; fi
    prev="$cur"
    [ $(( $(date +%s) - start )) -lt "$timeout" ] || { echo "no agent changed state in ${timeout}s"; return 0; }
  done
}

cmd_doctor() {
  local orch_path dup
  echo "session $ORCH_SESSION, orchestrator pane $ORCH_PANE, recorded orchestrator name: $(orch_name)"
  [ -n "$(orch_name)" ] || echo "WARN: no orchestrator name recorded. Get it from ListAgents ('This session is <name>') and run: bash agents.sh init <name>"
  orch_path=$(tmux display -p -t "$ORCH_PANE" '#{pane_current_path}')
  dup=$(agent_rows | awk -F'\t' -v p="$orch_path" '$6 == p && $4 !~ /^-?(zsh|bash|sh|fish)$/ {print $2 " (" $1 ")"}')
  [ -z "$dup" ] || echo "WARN: another Claude runs in the orchestrator's directory: $dup. Two orchestrators will contradict each other; ask the user which one owns coordination."
  cmd_list
}

usage() {
  cat <<'EOF'
bash agents.sh <command>   (inside the orchestrator's tmux pane; from outside set ORCH_PANE=%<id>)

  init [orch-name]              label the orchestrator pane, record its SendMessage name, lay out panes
  spawn <name> <dir> [--tab] [--prompt TEXT]
                                start a Claude agent as a pane (or tab); default prompt follows HANDOVER.md
  list | status                 every agent: name, pane, window, state (working/idle/permission/trust/shell/dead)
  peek <name> [lines]           last lines of an agent's screen (default 40)
  send <name> [--force] <message>
                                type a one-line message into an idle or working agent and submit it;
                                refuses if the input line has text unless --force
  watch [--timeout S] [--interval S]
                                block until an agent changes to idle/permission/trust/shell/dead (run in background)
  focus <name>                  move the user's keyboard to that pane (for prompts only the user may answer)
  restart <name> [--fresh]      relaunch Claude in a stopped pane (claude --continue, or the launch prompt)
  stop <name>|--all [--force]   send /exit (skips agents at prompts; skips working agents without --force)
  kill <name>                   close a stopped agent's pane
  name <pane_id> <name>         label an existing pane
  gather                        pull agent tabs into the orchestrator window as panes
  break <name>                  move an agent pane out to its own tab
  layout                        orchestrator left half, agents stacked right, names on borders
  doctor                        check setup: orchestrator name, duplicate orchestrator, agent states
EOF
}

main() {
  local cmd="${1:-help}"; shift || true
  case "$cmd" in help|-h|--help) usage; return ;; esac
  need_orch
  case "$cmd" in
    init) cmd_init "$@" ;; spawn) cmd_spawn "$@" ;; list|status) cmd_list ;; peek) cmd_peek "$@" ;;
    send) cmd_send "$@" ;; watch) cmd_watch "$@" ;; focus) cmd_focus "$@" ;; restart) cmd_restart "$@" ;;
    stop) cmd_stop "$@" ;; kill) cmd_kill "$@" ;; name) cmd_name "$@" ;; gather) cmd_gather ;;
    break) cmd_break "$@" ;; layout) cmd_layout ;; doctor) cmd_doctor ;;
    *) usage; die "unknown command: $cmd" ;;
  esac
}

main "$@"
