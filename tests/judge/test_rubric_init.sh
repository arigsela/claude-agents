#!/usr/bin/env bash
# Test suite for ~/.claude/hooks/rubric_init.sh (Codex rubric drafter for /judge-init).
# Uses scratch dirs and a fake `codex` shim on PATH; no live API calls.
# Usage: bash tests/judge/test_rubric_init.sh
# Override JUDGE_INIT_SH to validate the plugin-packaged copy instead of the
# live one, e.g.: JUDGE_INIT_SH=skills/codex-judge/hooks/rubric_init.sh bash ...
set -uo pipefail

JUDGE_INIT_SH="${JUDGE_INIT_SH:-$HOME/.claude/hooks/rubric_init.sh}"
# Resolve to an absolute path now: every test case below cd's into a scratch
# repo before invoking it, so a relative override (e.g. the plugin-packaged
# copy's repo-relative path) would otherwise stop resolving after the cd.
case "$JUDGE_INIT_SH" in
  /*) : ;;
  *) JUDGE_INIT_SH="$(pwd)/$JUDGE_INIT_SH" ;;
esac
PASS=0; FAIL=0

[ -f "$JUDGE_INIT_SH" ] || { echo "FATAL: rubric_init.sh not found at $JUDGE_INIT_SH"; exit 1; }

TESTROOT=$(mktemp -d "${TMPDIR:-/tmp}/rubric-init-tests.XXXXXX")
trap 'rm -rf "$TESTROOT"' EXIT

FAKE_PATH="$TESTROOT/bin:/usr/bin:/bin"
NO_CODEX_PATH="/usr/bin:/bin"

check() { # $1=name $2=condition-result(0=ok)
  if [ "$2" -eq 0 ]; then echo "PASS: $1"; PASS=$((PASS+1))
  else echo "FAIL: $1"; FAIL=$((FAIL+1)); fi
}

make_repo() { # $1=dir-name -> echoes repo path; git-initialized
  local dir="$TESTROOT/$1"
  mkdir -p "$dir"
  git -C "$dir" init -q
  git -C "$dir" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
  echo "$dir"
}

set_output() { printf '%s' "$1" > "$TESTROOT/canned-output.txt"; }
set_codex_exit_code() { printf '%s' "$1" > "$TESTROOT/codex-exit-code.txt"; }
set_codex_empty_output() { : > "$TESTROOT/codex-empty-flag"; }
clear_codex_state() { echo 0 > "$TESTROOT/codex-exit-code.txt"; rm -f "$TESTROOT/codex-empty-flag"; }

# Fake codex: consumes stdin, copies the canned output to --output-last-message
# unless the empty-output flag is set, then exits with the configured code.
mkdir -p "$TESTROOT/bin"
cat > "$TESTROOT/bin/codex" <<SHIM
#!/usr/bin/env bash
OUT=""
while [ \$# -gt 0 ]; do
  case "\$1" in
    --output-last-message) OUT="\$2"; shift 2 ;;
    *) shift ;;
  esac
done
cat > /dev/null
if [ -n "\$OUT" ] && [ ! -f "$TESTROOT/codex-empty-flag" ]; then
  cp "$TESTROOT/canned-output.txt" "\$OUT"
fi
EXIT_CODE=\$(cat "$TESTROOT/codex-exit-code.txt" 2>/dev/null || echo 0)
exit "\$EXIT_CODE"
SHIM
chmod +x "$TESTROOT/bin/codex"
clear_codex_state
set_output '# Rubric

## Correctness
- placeholder'

# ---- T1: not a git repo -> exit 1, clear message on stderr ----
R="$TESTROOT/notgit"; mkdir -p "$R"
ERR=$( cd "$R" && PATH="$FAKE_PATH" bash "$JUDGE_INIT_SH" 2>&1 >/dev/null )
rc=$?
[ "$rc" -eq 1 ] && printf '%s' "$ERR" | grep -q "Not inside a git repository"
check "T1 non-git dir: exit 1 with clear message" $?

# ---- T2: git repo, codex missing -> exit 1, clear message on stderr ----
R=$(make_repo t2)
ERR=$( cd "$R" && PATH="$NO_CODEX_PATH" bash "$JUDGE_INIT_SH" 2>&1 >/dev/null )
rc=$?
[ "$rc" -eq 1 ] && printf '%s' "$ERR" | grep -q "codex CLI not on PATH"
check "T2 missing codex: exit 1 with clear message" $?

# ---- T3: happy path -> exit 0, stdout is exactly the drafted rubric ----
R=$(make_repo t3)
OUT=$( cd "$R" && PATH="$FAKE_PATH" bash "$JUDGE_INIT_SH" 2>/dev/null )
rc=$?
[ "$rc" -eq 0 ] && [ "$OUT" = "$(cat "$TESTROOT/canned-output.txt")" ]
check "T3 happy path: exit 0, stdout is the drafted rubric" $?

# ---- T4: codex exits non-zero -> exit 1, clear message on stderr ----
R=$(make_repo t4)
set_codex_exit_code 1
ERR=$( cd "$R" && PATH="$FAKE_PATH" bash "$JUDGE_INIT_SH" 2>&1 >/dev/null )
rc=$?
[ "$rc" -eq 1 ] && printf '%s' "$ERR" | grep -q "Codex produced no output"
check "T4 codex exits non-zero: exit 1 with clear message" $?
clear_codex_state

# ---- T5: codex exits 0 but writes nothing -> exit 1, clear message on stderr ----
R=$(make_repo t5)
set_codex_empty_output
ERR=$( cd "$R" && PATH="$FAKE_PATH" bash "$JUDGE_INIT_SH" 2>&1 >/dev/null )
rc=$?
[ "$rc" -eq 1 ] && printf '%s' "$ERR" | grep -q "Codex produced no output"
check "T5 codex empty output: exit 1 with clear message" $?
clear_codex_state

echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
