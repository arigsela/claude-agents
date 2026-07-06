# Codex-as-Judge Stop Hook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install a global Claude Code Stop hook that has the Codex CLI judge Claude's working-tree diff against a per-repo rubric, blocking the stop with the judge's rationale on a `rework` verdict.

**Architecture:** A single dual-mode bash script (`~/.claude/hooks/judge.sh`) serves both the Stop hook (exit-2 block contract) and a `/judge` slash command (`--manual` mode). Judging is opt-in per repo via the presence of `.judge/rubric.md`. Every judge failure fails open and logs why to `~/.judge-log/verdicts.jsonl`. Spec: `docs/superpowers/specs/2026-07-06-codex-judge-stop-hook-design.md`.

**Tech Stack:** bash (macOS/BSD-compatible), `jq`, `git`, `codex` CLI (v0.142+, for `exec --sandbox read-only --output-last-message`). Tests use a fake-codex PATH shim — no live API calls except the final smoke test.

## Global Constraints

- Only these paths may be created or modified: `~/.claude/hooks/judge.sh`, `~/.claude/judge/prompt.default.md`, `~/.claude/commands/judge.md`, `~/.claude/settings.json`, `~/.judge-log/` (runtime), and in this repo `tests/judge/test_judge_hook.sh`.
- `~/.claude` is NOT a git repository — tasks touching it have verification steps instead of commit steps. Repo commits happen on branch `feat/codex-judge-stop-hook` in `/Users/arisela/git/claude-agents`.
- Fail-open policy: every judge failure (codex missing, auth error, timeout, unparseable output) must exit 0 and append an error-class line to the log. Exit 2 is reserved exclusively for a parsed `rework` verdict in stop-hook mode.
- Loop guards: hard cap of 3 rework rounds per session; `stop_hook_active=true` with a missing round-counter file → approve (backstop).
- No pinned Codex model — the user's codex default config governs; `JUDGE_CODEX_ARGS` (word-split) passes extra flags; `JUDGE_LOG_DIR` overrides the log directory (needed by tests).
- All shell must work with macOS BSD userland (BSD sed/awk/grep, bash 3.2-safe syntax; `local` only inside functions).
- Existing `~/.claude/settings.json` keys must be preserved exactly — only the `hooks` key is added.

---

### Task 1: Judge prompt template (`prompt.default.md`)

**Files:**
- Create: `~/.claude/judge/prompt.default.md`

**Interfaces:**
- Produces: a template containing literal `{{rubric}}` and `{{diff}}` placeholder lines, each alone on its own line. Task 3's `judge.sh` renders it by whole-line replacement (awk), so the placeholders MUST be the only non-whitespace content on their lines.
- Produces: the judge JSON output contract that Task 3 parses: keys `rationale` (string), `criteria` (object of four 1–5 integers), `verdict` (`"approve"` | `"rework"`).

- [ ] **Step 1: Create the directory and write the template**

```bash
mkdir -p ~/.claude/judge
```

Write `~/.claude/judge/prompt.default.md` with exactly this content:

```
You are a code review judge. You did not write this code. Evaluate the diff
against the rubric. Be adversarial about correctness and security; do not
reward verbosity or unnecessary refactors. Evaluate ONLY the provided diff —
never pre-existing code outside it.

Respond with ONLY a single JSON object: no markdown fences, no prose before
or after it, shaped exactly like this:
{"rationale": "<specific findings, file:line where possible>",
 "criteria": {"correctness": 1-5, "security": 1-5, "tests": 1-5, "scope": 1-5},
 "verdict": "approve" | "rework"}

The rationale key MUST come before the verdict key in your output. Criteria
scores are integers from 1 (worst) to 5 (best). The verdict MUST be "rework"
if any criterion is 2 or lower, or if any security issue exists in the diff.

RUBRIC:
{{rubric}}

DIFF:
{{diff}}
```

- [ ] **Step 2: Verify the placeholders render-ready**

Run:
```bash
grep -cx '{{rubric}}' ~/.claude/judge/prompt.default.md && grep -cx '{{diff}}' ~/.claude/judge/prompt.default.md
```
Expected: `1` printed twice (each placeholder appears exactly once, alone on its line).

No commit — path is outside any git repository.

---

### Task 2: Test suite with fake-codex shim (red)

**Files:**
- Create: `tests/judge/test_judge_hook.sh` (in `/Users/arisela/git/claude-agents`)

**Interfaces:**
- Consumes: `~/.claude/judge/prompt.default.md` from Task 1.
- Consumes (not yet existing — that is the point of red): `~/.claude/hooks/judge.sh` with the contract: stop-hook mode reads `{"session_id":..., "stop_hook_active":...}` on stdin, exits 0/2; `--manual` mode prints verdict, always exits 0; honors `JUDGE_LOG_DIR`; appends JSONL events with a `verdict` field in {`approve`,`rework`,`escalate`,`backstop_approve`,`judge_error`}; round counter at `/tmp/judge-rounds-<session_id>`.
- Produces: `bash tests/judge/test_judge_hook.sh` exiting 0 with `RESULT: 10 passed, 0 failed` once Task 3 lands.

- [ ] **Step 1: Write the test suite**

Write `tests/judge/test_judge_hook.sh` with exactly this content:

```bash
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
```

- [ ] **Step 2: Run the suite to verify it fails for the right reason**

Run: `bash tests/judge/test_judge_hook.sh`
Expected: `FATAL: judge.sh not found at /Users/arisela/.claude/hooks/judge.sh`, exit 1.

- [ ] **Step 3: Commit the red suite**

```bash
cd /Users/arisela/git/claude-agents
git add tests/judge/test_judge_hook.sh
git commit -m "test: red suite for codex judge stop hook (fake-codex shim)"
```

---

### Task 3: Implement `judge.sh` (green)

**Files:**
- Create: `~/.claude/hooks/judge.sh`
- Test: `tests/judge/test_judge_hook.sh` (from Task 2)

**Interfaces:**
- Consumes: `~/.claude/judge/prompt.default.md` (Task 1); Claude Code Stop-hook stdin JSON (`session_id`, `stop_hook_active`); `<repo>/.judge/rubric.md` (opt-in switch, Codex-authored); optional `<repo>/.judge/prompt.md` override.
- Produces: the exact contract Task 2's suite asserts (exit codes, log events, counter file). Task 4's `/judge` command runs `bash ~/.claude/hooks/judge.sh --manual`.

- [ ] **Step 1: Write the script**

```bash
mkdir -p ~/.claude/hooks
```

Write `~/.claude/hooks/judge.sh` with exactly this content:

```bash
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
JUDGE_HOME="${HOME}/.claude/judge"
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
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x ~/.claude/hooks/judge.sh`

- [ ] **Step 3: Run the suite to verify green**

Run: `bash tests/judge/test_judge_hook.sh`
Expected: `PASS:` lines T1–T10, then `RESULT: 10 passed, 0 failed`, exit 0.
If any test fails, fix `judge.sh` (not the test) until green.

- [ ] **Step 4: Commit (test suite unchanged — record green state)**

```bash
cd /Users/arisela/git/claude-agents
git commit --allow-empty -m "feat: judge.sh green against test suite (script lives in ~/.claude/hooks)"
```

---

### Task 4: Wire the Stop hook and the `/judge` command

**Files:**
- Modify: `~/.claude/settings.json`
- Create: `~/.claude/commands/judge.md`

**Interfaces:**
- Consumes: `~/.claude/hooks/judge.sh` (Task 3).
- Produces: Stop hook registered globally (fires in every session; instant no-op outside opted-in repos); `/judge` slash command available in every project.

- [ ] **Step 1: Back up and rewrite settings.json**

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak-judge
```

Write `~/.claude/settings.json` with exactly this content (existing keys preserved verbatim, only `hooks` added):

```json
{
  "enabledPlugins": {
    "superpowers@claude-plugins-official": true
  },
  "tui": "fullscreen",
  "voice": {
    "enabled": true,
    "mode": "hold"
  },
  "skipDangerousModePermissionPrompt": true,
  "theme": "dark",
  "voiceEnabled": true,
  "model": "claude-fable-5[1m]",
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$HOME/.claude/hooks/judge.sh\"",
            "timeout": 180
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Validate the JSON and confirm nothing else changed**

Run:
```bash
jq . ~/.claude/settings.json >/dev/null && echo VALID
diff <(jq 'del(.hooks)' ~/.claude/settings.json) <(jq . ~/.claude/settings.json.bak-judge) && echo "KEYS PRESERVED"
```
Expected: `VALID` then `KEYS PRESERVED`.

- [ ] **Step 3: Write the /judge command**

```bash
mkdir -p ~/.claude/commands
```

Write `~/.claude/commands/judge.md` with exactly this content:

```markdown
---
description: Run the Codex judge on the current working-tree diff (manual mode)
allowed-tools: Bash(bash:*)
---

Run the Codex judge manually and report its verdict:

1. Execute: `bash ~/.claude/hooks/judge.sh --manual`
2. Show the verdict and rationale to the user verbatim.
3. If the verdict is REWORK, address each finding in the rationale, then run
   the judge again. Stop after the judge approves or after 3 rework rounds —
   if still failing, summarize the unresolved findings for the user instead.
```

- [ ] **Step 4: Smoke-check manual mode in a non-opted-in repo**

Run: `cd /Users/arisela/git/claude-agents && bash ~/.claude/hooks/judge.sh --manual`
Expected: `Repo has not opted in (no .judge/rubric.md); nothing to judge.`, exit 0.

No commit — all paths outside any git repository.

---

### Task 5: Live smoke test with the real Codex CLI

**Files:**
- Create (throwaway): a scratch repo under the session scratchpad — nothing persistent.

**Interfaces:**
- Consumes: everything from Tasks 1–4, plus a working `codex` login.
- Produces: confidence that the real judge authenticates, receives the rendered prompt, and returns contract-conforming JSON. This is the only step that spends Codex tokens.

- [ ] **Step 1: Build a scratch repo with a seeded security defect**

```bash
S=$(mktemp -d "${TMPDIR:-/tmp}/judge-live.XXXXXX")
git -C "$S" init -q
git -C "$S" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
mkdir -p "$S/.judge"
cat > "$S/.judge/rubric.md" <<'EOF'
# Rubric (live smoke test)
- correctness: code must be syntactically valid and do what it claims
- security: NO hardcoded secrets, tokens, or credentials of any kind
- tests: changed behavior should touch tests where a test suite exists
- scope: minimal diff, no dead code, no unrelated refactors
EOF
git -C "$S" add .judge && git -C "$S" -c user.email=t@t -c user.name=t commit -q -m rubric
printf 'AWS_SECRET_ACCESS_KEY = "AKIAFAKEFAKEFAKEFAKE"\n' > "$S/deploy.py"
```

- [ ] **Step 2: Run the judge manually against the real Codex**

Run: `cd "$S" && bash ~/.claude/hooks/judge.sh --manual`
Expected: within ~180s, `Judge verdict: REWORK ...` and a rationale naming the hardcoded credential in `deploy.py` (approximately line 1). If instead you see `Judge error: could not parse verdict`, inspect `tail -1 ~/.judge-log/verdicts.jsonl` — an auth failure means the user must run `codex login` (surface this and stop).

- [ ] **Step 3: Verify the log entry and clean up**

Run:
```bash
tail -1 ~/.judge-log/verdicts.jsonl | jq '{verdict, criteria, duration_s}'
rm -rf "$S"
```
Expected: `"verdict": "rework"`, a criteria object with `security` ≤ 2, and a plausible duration.

- [ ] **Step 4: Commit the plan checkboxes and finish the branch**

```bash
cd /Users/arisela/git/claude-agents
git add docs/superpowers/plans/2026-07-06-codex-judge-stop-hook.md
git commit -m "docs: mark codex judge implementation plan executed"
```

---

## Post-plan handoff (not tasks for the implementer)

1. **Codex authors the rubrics** — `.judge/rubric.md` in `/Users/arisela/git/claude-agents` and `/Users/arisela/git/kubernetes`, per the brief in the design spec (four criteria, ~60 lines, opt-in switch semantics). Until then, the hook is a global no-op.
2. **User runs the live end-to-end test** in `~/git/kubernetes`: ask Claude to hardcode a fake secret in a chart value and watch Stop → REWORK → self-correct → APPROVE. Note: the Stop hook takes effect in Claude Code sessions started after Task 4.
3. **User calibrates for ~2 weeks** via `~/.judge-log/verdicts.jsonl` before promoting the pattern to a CI required check.
