#!/usr/bin/env bash
# Codex-as-judge Stop hook for Claude Code.
#
# Stop-hook mode (default): expects Claude Code hook JSON on stdin.
#   exit 0 -> allow the stop; exit 2 -> block, stderr goes back to Claude.
# Manual mode (--manual): same pipeline, prints the verdict, always exits 0.
#
# Opt-in per repo: judging only runs when the repo root has .judge/rubric.md.
# Fail-open: every judge failure allows the stop and logs an error class to
# $JUDGE_LOG_DIR/verdicts.jsonl (default ~/.judge-log).
# Extra codex flags: JUDGE_CODEX_ARGS (word-split). Round cap: 3 per session.
set -uo pipefail

MAX_ROUNDS=3
# Prompt template dir. When run as a plugin hook, CLAUDE_PLUGIN_ROOT points at
# the plugin root (where prompt.default.md lives). When run directly (e.g. the
# test suite invokes judge.sh by path), derive it from the script location.
JUDGE_HOME="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_DIR="${JUDGE_LOG_DIR:-${HOME}/.judge-log}"
LOG_FILE="${LOG_DIR}/verdicts.jsonl"

MODE="stop-hook"
[ "${1:-}" = "--manual" ] && MODE="manual"

say() { if [ "$MODE" = "manual" ]; then echo "$*"; fi; }

REPO_ROOT=""
SESSION_ID="manual-$$"

log_event() { # $1=verdict $2=round $3=rationale $4=criteria(json) $5=duration_s
  mkdir -p "$LOG_DIR" 2>/dev/null
  jq -cn \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg repo "$REPO_ROOT" --arg session "$SESSION_ID" --arg mode "$MODE" \
    --arg verdict "$1" --argjson round "${2:-0}" --arg rationale "$3" \
    --argjson criteria "${4:-null}" --argjson duration_s "${5:-0}" \
    '{ts:$ts,repo:$repo,session:$session,mode:$mode,verdict:$verdict,
      round:$round,rationale:$rationale,criteria:$criteria,duration_s:$duration_s}' \
    >> "$LOG_FILE" 2>/dev/null
}

# --- gates ------------------------------------------------------------------
command -v jq >/dev/null 2>&1 || exit 0   # only parse dependency; fail open
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) \
  || { say "Not inside a git repository; nothing to judge."; exit 0; }
if [ ! -f "$REPO_ROOT/.judge/rubric.md" ]; then
  say "Repo has not opted in (no .judge/rubric.md); nothing to judge."
  exit 0
fi

STOP_ACTIVE="false"
if [ "$MODE" = "stop-hook" ]; then
  INPUT=$(cat)
  SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null) || SESSION_ID="unknown"
  STOP_ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null) || STOP_ACTIVE="false"
fi

COUNT_FILE="/tmp/judge-rounds-${SESSION_ID}"
ROUNDS=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
case "$ROUNDS" in ''|*[!0-9]*) ROUNDS=0 ;; esac

if [ "$MODE" = "stop-hook" ]; then
  # Backstop: continuation stop but our round counter is gone/unreadable.
  # Approve rather than risk an unbounded block loop.
  if [ "$STOP_ACTIVE" = "true" ] && [ ! -f "$COUNT_FILE" ]; then
    log_event backstop_approve "$ROUNDS" "stop_hook_active with no round counter" null 0
    exit 0
  fi
  if [ "$ROUNDS" -ge "$MAX_ROUNDS" ]; then
    log_event escalate "$ROUNDS" "round cap reached; escalating to human review" null 0
    rm -f "$COUNT_FILE"
    exit 0
  fi
fi

# --- diff ---------------------------------------------------------------------
cd "$REPO_ROOT" || exit 0
git add -N . 2>/dev/null   # intent-to-add so brand-new files appear in the diff
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  DIFF_BASE=HEAD
else
  DIFF_BASE=$(git hash-object -t tree /dev/null)   # unborn HEAD: empty tree
fi
DIFF=$(git diff "$DIFF_BASE" 2>/dev/null || true)
if [ -z "$DIFF" ]; then
  say "Working tree matches ${DIFF_BASE}; nothing to judge."
  rm -f "$COUNT_FILE"
  exit 0
fi

# --- prompt -------------------------------------------------------------------
PROMPT_TEMPLATE="$REPO_ROOT/.judge/prompt.md"
[ -f "$PROMPT_TEMPLATE" ] || PROMPT_TEMPLATE="$JUDGE_HOME/prompt.default.md"
if [ ! -f "$PROMPT_TEMPLATE" ]; then
  log_event judge_error "$ROUNDS" "no prompt template at $PROMPT_TEMPLATE" null 0
  say "Judge error: no prompt template found (fail-open)."
  exit 0
fi

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/judge.XXXXXX") || exit 0
trap 'rm -rf "$WORK_DIR"' EXIT
printf '%s\n' "$DIFF" > "$WORK_DIR/diff.patch"
# Whole-line placeholder replacement via file reads — immune to diff content
# containing sed/bash metacharacters, and to ARG_MAX limits.
awk -v rubric="$REPO_ROOT/.judge/rubric.md" -v diff="$WORK_DIR/diff.patch" '
  /^\{\{rubric\}\}$/ { while ((getline line < rubric) > 0) print line; close(rubric); next }
  /^\{\{diff\}\}$/   { while ((getline line < diff) > 0) print line; close(diff); next }
  { print }
' "$PROMPT_TEMPLATE" > "$WORK_DIR/prompt.md"

# --- judge --------------------------------------------------------------------
if ! command -v codex >/dev/null 2>&1; then
  log_event judge_error "$ROUNDS" "codex CLI not on PATH" null 0
  say "Judge error: codex CLI not on PATH (fail-open)."
  exit 0
fi

LAST_MSG="$WORK_DIR/last-message.txt"
START=$SECONDS
# shellcheck disable=SC2086  # JUDGE_CODEX_ARGS is intentionally word-split
codex exec --sandbox read-only --output-last-message "$LAST_MSG" \
  ${JUDGE_CODEX_ARGS:-} - < "$WORK_DIR/prompt.md" >/dev/null 2>&1
CODEX_STATUS=$?
DURATION=$((SECONDS - START))

extract_json() { # tolerant: raw JSON, or JSON wrapped in fences/prose
  jq -c . "$1" 2>/dev/null && return 0
  local start end
  start=$(grep -n '{' "$1" | head -1 | cut -d: -f1)
  end=$(grep -n '}' "$1" | tail -1 | cut -d: -f1)
  { [ -n "$start" ] && [ -n "$end" ]; } || return 1
  sed -n "${start},${end}p" "$1" \
    | sed -e '1s/^[^{]*//' -e '$s/\(.*\)}[^}]*$/\1}/' \
    | jq -c . 2>/dev/null
}

VERDICT_JSON=$(extract_json "$LAST_MSG" 2>/dev/null || true)
VERDICT=$(printf '%s' "$VERDICT_JSON" | jq -r '.verdict // empty' 2>/dev/null || true)
RATIONALE=$(printf '%s' "$VERDICT_JSON" | jq -r '.rationale // ""' 2>/dev/null || true)
CRITERIA=$(printf '%s' "$VERDICT_JSON" | jq -c '.criteria // null' 2>/dev/null || echo null)
[ -n "$CRITERIA" ] || CRITERIA=null

case "$VERDICT" in
  approve)
    log_event approve "$ROUNDS" "$RATIONALE" "$CRITERIA" "$DURATION"
    rm -f "$COUNT_FILE"
    say "Judge verdict: APPROVE"
    say "$RATIONALE"
    exit 0
    ;;
  rework)
    NEXT=$((ROUNDS + 1))
    log_event rework "$NEXT" "$RATIONALE" "$CRITERIA" "$DURATION"
    if [ "$MODE" = "manual" ]; then
      say "Judge verdict: REWORK (round $NEXT/$MAX_ROUNDS would apply in hook mode)"
      say "$RATIONALE"
      exit 0
    fi
    echo "$NEXT" > "$COUNT_FILE"
    echo "Codex judge verdict: REWORK (round $NEXT/$MAX_ROUNDS). Address these findings, then finish: $RATIONALE" >&2
    exit 2
    ;;
  *)
    log_event judge_error "$ROUNDS" "unparseable verdict (codex exit $CODEX_STATUS)" null "$DURATION"
    say "Judge error: could not parse verdict (fail-open). See $LOG_FILE"
    exit 0
    ;;
esac
