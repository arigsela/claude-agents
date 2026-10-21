#!/usr/bin/env bash
# Codex rubric drafter for /judge-init.
#
# Prints the drafted .judge/rubric.md content to stdout on success, exit 0.
# Never writes .judge/rubric.md itself; the caller (the /judge-init command)
# shows the draft, handles the overwrite check, and writes the file.
#
# Fails loud, unlike judge.sh: every gate/error prints a message to stderr
# and exits 1. There is no in-flight session to protect here.
# Extra codex flags: JUDGE_CODEX_ARGS (word-split), matching judge.sh.
set -uo pipefail

# Prompt/example dir. When run as a plugin hook, CLAUDE_PLUGIN_ROOT points at
# the plugin root (where rubric-init.prompt.md lives). When run directly
# (e.g. the test suite invokes it by path), derive it from the script location.
JUDGE_HOME="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) \
  || { echo "Not inside a git repository." >&2; exit 1; }

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not on PATH, install/auth it first." >&2
  exit 1
fi

PROMPT_TEMPLATE="$JUDGE_HOME/rubric-init.prompt.md"
EXAMPLE_RUBRIC="$JUDGE_HOME/example-rubric.md"
[ -f "$PROMPT_TEMPLATE" ] || { echo "Missing prompt template at $PROMPT_TEMPLATE" >&2; exit 1; }
[ -f "$EXAMPLE_RUBRIC" ] || { echo "Missing example rubric at $EXAMPLE_RUBRIC" >&2; exit 1; }

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rubric-init.XXXXXX") || exit 1
trap 'rm -rf "$WORK_DIR"' EXIT

# Whole-line placeholder replacement via file reads, same technique judge.sh
# uses for {{rubric}}/{{diff}}, immune to the example content containing
# shell or {{-like metacharacters.
awk -v example="$EXAMPLE_RUBRIC" '
  /^\{\{example_rubric\}\}$/ { while ((getline line < example) > 0) print line; close(example); next }
  { print }
' "$PROMPT_TEMPLATE" > "$WORK_DIR/prompt.md"

LAST_MSG="$WORK_DIR/last-message.txt"
cd "$REPO_ROOT" || exit 1
# shellcheck disable=SC2086  # JUDGE_CODEX_ARGS is intentionally word-split
codex exec --sandbox read-only --output-last-message "$LAST_MSG" \
  ${JUDGE_CODEX_ARGS:-} - < "$WORK_DIR/prompt.md" >/dev/null 2>&1
CODEX_STATUS=$?

if [ "$CODEX_STATUS" -ne 0 ] || [ ! -s "$LAST_MSG" ]; then
  echo "Codex produced no output (exit $CODEX_STATUS); try again." >&2
  exit 1
fi

cat "$LAST_MSG"
