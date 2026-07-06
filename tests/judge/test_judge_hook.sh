#!/usr/bin/env bash
# Test suite for ~/.claude/hooks/judge.sh (Codex-as-judge Stop hook).
# Uses scratch git repos and a fake `codex` shim on PATH — no live API calls.
# Usage: bash tests/judge/test_judge_hook.sh
set -uo pipefail

JUDGE_SH="${JUDGE_SH:-$HOME/.claude/hooks/judge.sh}"
PASS=0; FAIL=0

[ -f "$JUDGE_SH" ] || { echo "FATAL: judge.sh not found at $JUDGE_SH"; exit 1; }

TESTROOT=$(mktemp -d "${TMPDIR:-/tmp}/judge-tests.XXXXXX")
trap 'rm -rf "$TESTROOT"; rm -f /tmp/judge-rounds-jt-*' EXIT

export JUDGE_LOG_DIR="$TESTROOT/judge-log"
LOG="$JUDGE_LOG_DIR/verdicts.jsonl"

# PATH with the fake codex first; PATH with no codex at all (system dirs only).
FAKE_PATH="$TESTROOT/bin:/usr/bin:/bin"
NO_CODEX_PATH="/usr/bin:/bin"

hook_json() { # $1=session_id $2=stop_hook_active(default false)
  printf '{"session_id":"%s","stop_hook_active":%s}' "$1" "${2:-false}"
}

make_repo() { # $1=dir-name -> echoes repo path; opted-in, one commit, clean tree
  local dir="$TESTROOT/$1"
  mkdir -p "$dir/.judge"
  git -C "$dir" init -q
  git -C "$dir" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
  printf '# Test rubric\n- security: reject any hardcoded secret\n' > "$dir/.judge/rubric.md"
  git -C "$dir" add .judge/rubric.md
  git -C "$dir" -c user.email=t@t -c user.name=t commit -q -m rubric
  echo "$dir"
}

set_verdict() { # $1=content the fake codex writes to --output-last-message
  printf '%s' "$1" > "$TESTROOT/canned-verdict.txt"
}

# Fake codex: consumes stdin, copies the canned verdict to the last-message file.
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
[ -n "\$OUT" ] && cp "$TESTROOT/canned-verdict.txt" "\$OUT"
exit 0
SHIM
chmod +x "$TESTROOT/bin/codex"

check() { # $1=name $2=condition-result(0=ok)
  if [ "$2" -eq 0 ]; then echo "PASS: $1"; PASS=$((PASS+1))
  else echo "FAIL: $1"; FAIL=$((FAIL+1)); fi
}

last_log_verdict() { tail -1 "$LOG" 2>/dev/null | /usr/bin/jq -r '.verdict // "none"'; }

# ---- T1: repo without .judge/rubric.md -> instant exit 0, nothing logged ----
R=$TESTROOT/plain; mkdir -p "$R"; git -C "$R" init -q
( cd "$R" && hook_json jt-t1 | PATH="$FAKE_PATH" bash "$JUDGE_SH" )
rc=$?; [ "$rc" -eq 0 ] && [ ! -s "$LOG" ]; check "T1 not-opted-in repo exits 0 silently" $?

# ---- T2: opted-in repo, clean tree (empty diff) -> exit 0 ----
R=$(make_repo t2)
( cd "$R" && hook_json jt-t2 | PATH="$FAKE_PATH" bash "$JUDGE_SH" )
check "T2 empty diff exits 0" $?

# ---- T3: dirty diff + approve verdict -> exit 0, logged, counter cleared ----
R=$(make_repo t3); echo "x = 1" > "$R/app.py"
echo 1 > /tmp/judge-rounds-jt-t3
set_verdict '{"rationale":"clean change","criteria":{"correctness":5,"security":5,"tests":4,"scope":5},"verdict":"approve"}'
( cd "$R" && hook_json jt-t3 | PATH="$FAKE_PATH" bash "$JUDGE_SH" )
rc=$?; [ "$rc" -eq 0 ] && [ "$(last_log_verdict)" = "approve" ] && [ ! -f /tmp/judge-rounds-jt-t3 ]
check "T3 approve: exit 0, logged, counter cleared" $?

# ---- T4: rework verdict -> exit 2, rationale on stderr, counter incremented ----
R=$(make_repo t4); echo 'API_KEY = "sk-fake123"' > "$R/config.py"
set_verdict '{"rationale":"hardcoded secret in config.py:1","criteria":{"correctness":4,"security":1,"tests":3,"scope":4},"verdict":"rework"}'
ERR=$( cd "$R" && hook_json jt-t4 | PATH="$FAKE_PATH" bash "$JUDGE_SH" 2>&1 >/dev/null )
rc=$?
[ "$rc" -eq 2 ] && printf '%s' "$ERR" | grep -q "hardcoded secret" \
  && [ "$(cat /tmp/judge-rounds-jt-t4)" = "1" ] && [ "$(last_log_verdict)" = "rework" ]
check "T4 rework: exit 2, rationale on stderr, counter=1" $?

# ---- T5: round counter at cap -> escalate, exit 0, counter cleared ----
R=$(make_repo t5); echo "y = 2" > "$R/app.py"
echo 3 > /tmp/judge-rounds-jt-t5
( cd "$R" && hook_json jt-t5 true | PATH="$FAKE_PATH" bash "$JUDGE_SH" )
rc=$?; [ "$rc" -eq 0 ] && [ "$(last_log_verdict)" = "escalate" ] && [ ! -f /tmp/judge-rounds-jt-t5 ]
check "T5 round cap: escalate, exit 0, counter cleared" $?

# ---- T6: codex not on PATH -> fail open, judge_error logged ----
R=$(make_repo t6); echo "z = 3" > "$R/app.py"
( cd "$R" && hook_json jt-t6 | PATH="$NO_CODEX_PATH" bash "$JUDGE_SH" )
rc=$?; [ "$rc" -eq 0 ] && [ "$(last_log_verdict)" = "judge_error" ]
check "T6 missing codex: fail open, judge_error logged" $?

# ---- T7: garbage judge output -> fail open, judge_error logged ----
R=$(make_repo t7); echo "w = 4" > "$R/app.py"
set_verdict 'I think this change looks fine to me!'
( cd "$R" && hook_json jt-t7 | PATH="$FAKE_PATH" bash "$JUDGE_SH" )
rc=$?; [ "$rc" -eq 0 ] && [ "$(last_log_verdict)" = "judge_error" ]
check "T7 garbage output: fail open, judge_error logged" $?

# ---- T8: fenced/prose-wrapped JSON still parses -> rework, exit 2 ----
R=$(make_repo t8); echo 'TOKEN = "abc"' > "$R/s.py"
set_verdict 'Here is my assessment:
```json
{"rationale":"secret at s.py:1","criteria":{"correctness":4,"security":2,"tests":3,"scope":4},"verdict":"rework"}
```
Hope that helps.'
( cd "$R" && hook_json jt-t8 | PATH="$FAKE_PATH" bash "$JUDGE_SH" 2>/dev/null )
rc=$?; [ "$rc" -eq 2 ] && [ "$(last_log_verdict)" = "rework" ]
check "T8 fenced JSON parsed: rework, exit 2" $?
rm -f /tmp/judge-rounds-jt-t8

# ---- T9: stop_hook_active with no counter file -> backstop approve, no codex call ----
R=$(make_repo t9); echo "v = 5" > "$R/app.py"
set_verdict '{"rationale":"should never be read","criteria":{"correctness":1,"security":1,"tests":1,"scope":1},"verdict":"rework"}'
( cd "$R" && hook_json jt-t9 true | PATH="$FAKE_PATH" bash "$JUDGE_SH" )
rc=$?; [ "$rc" -eq 0 ] && [ "$(last_log_verdict)" = "backstop_approve" ]
check "T9 stop_hook_active + no counter: backstop approve" $?

# ---- T10: manual mode -> prints verdict, exits 0, no counter written ----
R=$(make_repo t10); echo "u = 6" > "$R/app.py"
set_verdict '{"rationale":"all good","criteria":{"correctness":5,"security":5,"tests":4,"scope":5},"verdict":"approve"}'
OUT=$( cd "$R" && PATH="$FAKE_PATH" bash "$JUDGE_SH" --manual )
rc=$?; [ "$rc" -eq 0 ] && printf '%s' "$OUT" | grep -q "APPROVE"
check "T10 manual mode prints APPROVE, exit 0" $?

echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
