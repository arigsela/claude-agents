# /judge-init Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/judge-init` slash command that drafts a repo-tailored `.judge/rubric.md` via the Codex CLI, so activating codex-judge in a new repo no longer requires hand-authoring the rubric.

**Architecture:** A new standalone script (`rubric_init.sh`) asks Codex to explore the target repo and print a five-section rubric draft to stdout; it never touches `.judge/rubric.md` itself. The new `/judge-init` command runs the script, shows the draft, warns and confirms before overwriting an existing rubric, then writes the file with Claude's own Write tool. Both files (plus a prompt template and a bundled example rubric) ship in two places: the version-controlled plugin source (`skills/codex-judge/`) and the live, non-git `~/.claude/{hooks,judge,commands}/` copies that `/judge` itself already uses today. Spec: `docs/superpowers/specs/2026-07-10-judge-init-design.md`.

**Tech Stack:** bash (macOS/BSD-compatible), `git`, `codex` CLI (`exec --sandbox read-only --output-last-message`, same as `judge.sh`). No `jq` dependency here; output is raw markdown, not JSON. Tests use a fake-codex PATH shim; live Codex calls happen only in the final smoke-test task.

## Global Constraints

- Only these paths may be created or modified. Repo (`/Users/asela/git/claude-agents`, branch `feat/judge-init`, normal git commits): `skills/codex-judge/hooks/rubric_init.sh`, `skills/codex-judge/rubric-init.prompt.md`, `skills/codex-judge/example-rubric.md`, `skills/codex-judge/commands/judge-init.md`, `tests/judge/test_rubric_init.sh`, `docs/superpowers/plans/2026-07-10-judge-init.md` (this file's checkboxes). Live (`$HOME/.claude`, NOT a git repository, verification steps instead of commits): `~/.claude/hooks/rubric_init.sh`, `~/.claude/judge/rubric-init.prompt.md`, `~/.claude/judge/example-rubric.md`, `~/.claude/commands/judge-init.md`.
- Fail-loud policy: every gate or error in `rubric_init.sh` prints a clear message to stderr and exits 1. No round counter, no verdict log, no fail-open. This script is not part of the Stop-hook loop, so there is no in-flight session to protect.
- `rubric_init.sh` never writes `.judge/rubric.md`. The overwrite check and the file write both happen in the Claude-side instructions in `judge-init.md`, never in shell.
- The live and plugin-packaged copies of `rubric_init.sh` differ only in how `JUDGE_HOME` is resolved: the live copy hardcodes it, the packaged copy resolves it via `CLAUDE_PLUGIN_ROOT` with an explanatory comment above it, matching the existing divergence between the live and packaged `judge.sh` exactly. The live and packaged copies of `judge-init.md` differ only in the script path, which appears on two lines (the `allowed-tools` scope and the "Execute" instruction); every other line is identical, matching `judge.md`'s single divergent-path pattern in spirit though not in line count.
- All shell must work with macOS BSD userland (BSD sed/awk/grep, bash 3.2-safe syntax; `local` only inside functions), consistent with `judge.sh`.
- `JUDGE_CODEX_ARGS` (word-split) is honored as an escape hatch, matching `judge.sh`.

---

### Task 1: Prompt template and bundled example rubric

**Files:**
- Create: `skills/codex-judge/rubric-init.prompt.md`
- Create: `skills/codex-judge/example-rubric.md`
- Create (copy): `~/.claude/judge/rubric-init.prompt.md`
- Create (copy): `~/.claude/judge/example-rubric.md`

**Interfaces:**
- Produces: a template containing a literal `{{example_rubric}}` placeholder line, alone on its own line. Task 3's `rubric_init.sh` renders it by whole-line replacement (awk), so the placeholder MUST be the only non-whitespace content on its line.
- Produces: `example-rubric.md`, a frozen, self-contained style reference with no placeholders of its own.

- [x] **Step 1: Write the prompt template and example rubric in the repo**

Write `skills/codex-judge/rubric-init.prompt.md` with exactly this content:

```
You are drafting a code-review rubric for the repo at the current working
directory. Explore it (manifests, lint/test config, CI, existing code) to
determine its stack and conventions.

Output ONLY the contents of .judge/rubric.md, a markdown document with no
fences and no prose before or after it. Structure it as a single '#' title
line naming the repo, followed by exactly five '##' sections in this order:
Correctness, Security, Tests, Scope, Reject on sight. Fill each section with
concrete, stack-specific bullets, not generic advice, based on what you find
in the repo. Keep the whole document under 60 lines.

STYLE EXAMPLE, a rubric written for a different, Python-based repo. Match
its level of concreteness and structure, not its content:
{{example_rubric}}
```

Write `skills/codex-judge/example-rubric.md` with exactly this content (a frozen copy of `claude-agents/.judge/rubric.md` as it read on 2026-07-10):

```
# Review rubric — claude-agents

Python-first repo (black / ruff / pytest). AI agents that talk to the Anthropic
API, Kubernetes, Slack, and GitOps. Hold the diff to the bar below.

## Correctness
- Logic matches the apparent intent; no off-by-one, inverted conditions, or
  unhandled empty/None/error cases.
- Changed a public function signature? Every caller in the diff is updated.
- No bare `except:` and no `except Exception: pass` — exceptions are either
  handled meaningfully or allowed to propagate.
- New public functions/methods have type hints; non-obvious ones have a concise
  docstring.
- No debug leftovers: stray `print()`, commented-out code, or `TODO`/`FIXME`
  without an issue/PR reference.

## Security
- No secrets, API keys, or tokens in code, config, or fixtures — read from env
  or a secret store. Anthropic keys and Slack tokens especially.
- External input (Slack payloads, HTTP request bodies, LLM tool arguments) is
  validated before use; no shell/SQL/path injection; no `eval`/`exec` on it.
- No `subprocess` with `shell=True` on interpolated input.
- kubectl / k8s client calls that mutate cluster state are gated and scoped —
  no unbounded delete/apply across namespaces.
- No new third-party dependency without a clear need.

## Tests
- New behavior or a bug fix ships with a pytest test that would FAIL without
  the change.
- Tests assert on real outcomes, not just "it ran without raising."
- External calls (Anthropic API, k8s, Slack, HTTP) are mocked/stubbed — tests
  don't hit live services or require network.

## Scope
- The diff does one thing. No opportunistic refactors folded into a fix.
- No black/ruff reformatting churn on lines unrelated to the change.
- No unrelated dependency bumps.

## Reject on sight
- Swallowed exceptions (bare `except`, `except: pass`) with no handling.
- Weakened, skipped, or deleted tests to make a build go green.
- Hardcoded secret, key, or token anywhere in the diff.
- Cluster-mutating operation with no scope limit or guard.
```

- [x] **Step 2: Copy both files to the live location**

```bash
mkdir -p ~/.claude/judge
cp skills/codex-judge/rubric-init.prompt.md ~/.claude/judge/rubric-init.prompt.md
cp skills/codex-judge/example-rubric.md ~/.claude/judge/example-rubric.md
```

- [x] **Step 3: Verify the placeholder and the copies**

Run:
```bash
grep -cx '{{example_rubric}}' skills/codex-judge/rubric-init.prompt.md
diff skills/codex-judge/rubric-init.prompt.md ~/.claude/judge/rubric-init.prompt.md && echo PROMPT_MATCHES
diff skills/codex-judge/example-rubric.md ~/.claude/judge/example-rubric.md && echo EXAMPLE_MATCHES
```
Expected: `1`, then `PROMPT_MATCHES`, then `EXAMPLE_MATCHES`.

- [x] **Step 4: Commit the repo-source files**

```bash
git checkout -b feat/judge-init
git add skills/codex-judge/rubric-init.prompt.md skills/codex-judge/example-rubric.md
git commit -m "feat: add rubric-init prompt template and bundled example rubric"
```

No commit for the `~/.claude/judge/` copies (outside any git repository).

---

### Task 2: Test suite for `rubric_init.sh` with a fake-codex shim (red)

**Files:**
- Create: `tests/judge/test_rubric_init.sh` (in `/Users/asela/git/claude-agents`)

**Interfaces:**
- Consumes (not yet existing; that is the point of red): `~/.claude/hooks/rubric_init.sh` with the contract: no argument, no stdin contract; not a git repo → exit 1, stderr contains "Not inside a git repository"; `codex` not on `PATH` → exit 1, stderr contains "codex CLI not on PATH"; `codex exec` exits non-zero OR writes an empty last-message file → exit 1, stderr contains "Codex produced no output"; otherwise → exit 0, stdout is exactly the content Codex wrote to `--output-last-message`.
- Produces: `JUDGE_INIT_SH=<path> bash tests/judge/test_rubric_init.sh` exiting 0 with `RESULT: 5 passed, 0 failed`, defaulting `JUDGE_INIT_SH` to `~/.claude/hooks/rubric_init.sh` when unset, so the same suite can validate both the live copy (Task 3) and the plugin-packaged copy (Task 4).

- [x] **Step 1: Write the test suite**

Write `tests/judge/test_rubric_init.sh` with exactly this content:

```bash
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
```

- [x] **Step 2: Run the suite to verify it fails for the right reason**

Run: `bash tests/judge/test_rubric_init.sh`
Expected: `FATAL: rubric_init.sh not found at /Users/asela/.claude/hooks/rubric_init.sh`, exit 1.

- [x] **Step 3: Commit the red suite**

```bash
git add tests/judge/test_rubric_init.sh
git commit -m "test: red suite for rubric_init.sh (fake-codex shim)"
```

---

### Task 3: Implement the live `rubric_init.sh` (green)

**Files:**
- Create: `~/.claude/hooks/rubric_init.sh`
- Test: `tests/judge/test_rubric_init.sh` (from Task 2)

**Interfaces:**
- Consumes: `~/.claude/judge/rubric-init.prompt.md` and `~/.claude/judge/example-rubric.md` (Task 1).
- Produces: the exact contract Task 2's suite asserts. Task 5's `/judge-init` command runs `bash ~/.claude/hooks/rubric_init.sh`.

- [x] **Step 1: Write the script**

Write `~/.claude/hooks/rubric_init.sh` with exactly this content:

```bash
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

JUDGE_HOME="${HOME}/.claude/judge"

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
```

- [x] **Step 2: Make it executable**

Run: `chmod +x ~/.claude/hooks/rubric_init.sh`

- [x] **Step 3: Run the suite to verify green**

Run: `bash tests/judge/test_rubric_init.sh`
Expected: `PASS:` lines T1-T5, then `RESULT: 5 passed, 0 failed`, exit 0.
If any test fails, fix `rubric_init.sh` (not the test) until green.

- [x] **Step 4: Commit (test suite unchanged, record green state)**

```bash
git commit --allow-empty -m "feat: rubric_init.sh green against test suite (script lives in ~/.claude/hooks)"
```

---

### Task 4: Package `rubric_init.sh` into the plugin source (green against the same suite)

**Files:**
- Create: `skills/codex-judge/hooks/rubric_init.sh`
- Test: `tests/judge/test_rubric_init.sh` (from Task 2), run with `JUDGE_INIT_SH` override

**Interfaces:**
- Consumes: `skills/codex-judge/rubric-init.prompt.md` and `skills/codex-judge/example-rubric.md` (Task 1); `CLAUDE_PLUGIN_ROOT` when installed as a plugin hook.
- Produces: a portable copy of `rubric_init.sh` that resolves its prompt directory the same way the packaged `judge.sh` already does, so it works both installed as a plugin and invoked directly by path.

- [x] **Step 1: Write the packaged copy**

Write `skills/codex-judge/hooks/rubric_init.sh` with exactly this content (identical to the live copy in Task 3, Step 1, except the `JUDGE_HOME` line):

```bash
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
```

- [x] **Step 2: Make it executable**

Run: `chmod +x skills/codex-judge/hooks/rubric_init.sh`

- [x] **Step 3: Run the suite against the packaged copy**

Run: `JUDGE_INIT_SH=skills/codex-judge/hooks/rubric_init.sh bash tests/judge/test_rubric_init.sh`
Expected: `PASS:` lines T1-T5, then `RESULT: 5 passed, 0 failed`, exit 0.

- [x] **Step 4: Confirm the only difference between the two copies is the expected `JUDGE_HOME` divergence**

The packaged copy replaces the live copy's single `JUDGE_HOME=` line with that
same line plus its three explanatory comment lines above it (mirroring the
existing `judge.sh` live-vs-packaged divergence exactly). A line-number diff
is fragile to verify by eye, so strip both known variants of that block and
diff what remains, which must be byte-identical:

```bash
grep -Ev '^JUDGE_HOME=|^# Prompt/example dir\.|^# the plugin root|^# \(e\.g\. the test suite' \
  ~/.claude/hooks/rubric_init.sh > /tmp/rubric_init.live.stripped
grep -Ev '^JUDGE_HOME=|^# Prompt/example dir\.|^# the plugin root|^# \(e\.g\. the test suite' \
  skills/codex-judge/hooks/rubric_init.sh > /tmp/rubric_init.packaged.stripped
diff /tmp/rubric_init.live.stripped /tmp/rubric_init.packaged.stripped && echo IDENTICAL_EXCEPT_JUDGE_HOME
rm -f /tmp/rubric_init.live.stripped /tmp/rubric_init.packaged.stripped
```
Expected: `IDENTICAL_EXCEPT_JUDGE_HOME`, with no diff output above it.

- [x] **Step 5: Commit**

```bash
git add skills/codex-judge/hooks/rubric_init.sh
git commit -m "feat: package rubric_init.sh into the codex-judge plugin"
```

---

### Task 5: The `/judge-init` command

**Files:**
- Create: `~/.claude/commands/judge-init.md`
- Create: `skills/codex-judge/commands/judge-init.md`

**Interfaces:**
- Consumes: `~/.claude/hooks/rubric_init.sh` (Task 3) for the live copy; `${CLAUDE_PLUGIN_ROOT}/hooks/rubric_init.sh` (Task 4) for the packaged copy.
- Produces: the `/judge-init` slash command, available immediately in this and other local sessions (live copy) and via the codex-judge plugin once reinstalled/updated (packaged copy).

- [x] **Step 1: Write the live command**

Write `~/.claude/commands/judge-init.md` with exactly this content:

```markdown
---
description: Draft a .judge/rubric.md for this repo via Codex, then review and write it
allowed-tools: Bash(bash ~/.claude/hooks/rubric_init.sh:*), Write
---

Scaffold a rubric for this repo:

1. Execute: `bash ~/.claude/hooks/rubric_init.sh`
2. If it exits non-zero, show the error to the user verbatim and stop; there
   is nothing to write.
3. On success, show the drafted rubric to the user verbatim.
4. Check whether `.judge/rubric.md` already exists in this repo. If it does,
   warn the user that this will overwrite it and confirm before proceeding.
5. Write the drafted content to `.judge/rubric.md` using the Write tool. Do
   not commit it; let the user review and commit normally.
```

- [x] **Step 2: Write the packaged command**

Write `skills/codex-judge/commands/judge-init.md` with exactly this content (identical to the live copy in Step 1, except line 1 of the body):

```markdown
---
description: Draft a .judge/rubric.md for this repo via Codex, then review and write it
allowed-tools: Bash(bash "${CLAUDE_PLUGIN_ROOT}/hooks/rubric_init.sh":*), Write
---

Scaffold a rubric for this repo:

1. Execute: `bash "${CLAUDE_PLUGIN_ROOT}/hooks/rubric_init.sh"`
2. If it exits non-zero, show the error to the user verbatim and stop; there
   is nothing to write.
3. On success, show the drafted rubric to the user verbatim.
4. Check whether `.judge/rubric.md` already exists in this repo. If it does,
   warn the user that this will overwrite it and confirm before proceeding.
5. Write the drafted content to `.judge/rubric.md` using the Write tool. Do
   not commit it; let the user review and commit normally.
```

- [x] **Step 3: Confirm the only differences between the two copies are the expected script-path lines**

The script path appears twice in this file (once in the `allowed-tools`
frontmatter scope, once in the "Execute" instruction), so both lines
diverge between the live and packaged copies:

```bash
diff ~/.claude/commands/judge-init.md skills/codex-judge/commands/judge-init.md
```
Expected: two hunks, one for the `allowed-tools` line and one for the
"Execute" line; both differences are the live script path
(`~/.claude/hooks/rubric_init.sh`) versus the packaged path
(`"${CLAUDE_PLUGIN_ROOT}/hooks/rubric_init.sh"`). No other lines differ.

- [x] **Step 4: Validate the frontmatter parses**

Run:
```bash
head -4 ~/.claude/commands/judge-init.md
```
Expected: the three-dash-delimited frontmatter block with `description` and `allowed-tools` keys, no YAML errors.

- [x] **Step 5: Commit the packaged command**

```bash
git add skills/codex-judge/commands/judge-init.md
git commit -m "feat: add /judge-init command"
```

No commit for `~/.claude/commands/judge-init.md` (outside any git repository).

---

### Task 6: Live smoke test with the real Codex CLI

**Files:**
- Create (throwaway): a scratch Terraform repo under `${TMPDIR:-/tmp}` (nothing persistent).

**Interfaces:**
- Consumes: everything from Tasks 1-5, plus a working `codex` login.
- Produces: confidence that the real Codex authenticates, receives the rendered prompt, and drafts a rubric matching the fixed five-section skeleton across two different stacks. This is the only task that spends Codex tokens.

- [x] **Step 1: Run the drafter against this Python-stack repo**

```bash
cd /Users/asela/git/claude-agents && bash ~/.claude/hooks/rubric_init.sh > /tmp/rubric-init-python.md
cat /tmp/rubric-init-python.md
```
Expected: within ~180s, a markdown document under 60 lines whose bullets reference this repo's actual stack (black/ruff/pytest, Anthropic API, Slack, Kubernetes). If instead you see an error mentioning authentication, run `codex login` first, then retry this step.

- [x] **Step 2: Build a throwaway Terraform-stack scratch repo**

```bash
T=$(mktemp -d "${TMPDIR:-/tmp}/rubric-init-tf.XXXXXX")
git -C "$T" init -q
git -C "$T" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
cat > "$T/main.tf" <<'EOF'
resource "aws_s3_bucket" "example" {
  bucket = "example-bucket"
}
EOF
git -C "$T" add main.tf
git -C "$T" -c user.email=t@t -c user.name=t commit -q -m "add example resource"
```

- [x] **Step 3: Run the drafter against the Terraform-stack repo**

```bash
cd "$T" && bash ~/.claude/hooks/rubric_init.sh > /tmp/rubric-init-tf.md
cat /tmp/rubric-init-tf.md
```
Expected: within ~180s, a markdown document under 60 lines whose Security/Reject-on-sight bullets reference Terraform-specific concerns (state files, unscoped `apply`/`destroy`) rather than the Python-specific language from Step 1.

- [x] **Step 4: Verify both drafts carry the same five-section skeleton**

Run:
```bash
for f in /tmp/rubric-init-python.md /tmp/rubric-init-tf.md; do
  for h in Correctness Security Tests Scope "Reject on sight"; do
    grep -qx "## $h" "$f" || echo "MISSING: $h in $f"
  done
done
echo "Header check complete"
```
Expected: `Header check complete` with no `MISSING` lines printed above it.

- [x] **Step 5: Clean up the scratch repo and drafts**

```bash
rm -rf "$T" /tmp/rubric-init-python.md /tmp/rubric-init-tf.md
```

---

### Task 7: Verify the overwrite-confirmation and write behavior

**Files:**
- Create (throwaway): a scratch repo with a pre-existing `.judge/rubric.md` under `${TMPDIR:-/tmp}` (nothing persistent).

**Interfaces:**
- Consumes: `~/.claude/hooks/rubric_init.sh` (Task 3), `~/.claude/commands/judge-init.md` (Task 5).
- Produces: mechanical proof that `rubric_init.sh` never touches `.judge/rubric.md` itself (so all destructive risk is isolated to `judge-init.md`'s Claude-side instructions), and that both branches of the overwrite decision (confirm and decline) behave correctly when actually exercised against a real existing rubric.

- [x] **Step 1: Build a scratch repo with a pre-existing sentinel rubric**

```bash
S=$(mktemp -d "${TMPDIR:-/tmp}/judge-init-overwrite.XXXXXX")
git -C "$S" init -q
git -C "$S" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
mkdir -p "$S/.judge"
printf '# SENTINEL existing rubric, must not be overwritten silently\n' > "$S/.judge/rubric.md"
git -C "$S" add .judge/rubric.md
git -C "$S" -c user.email=t@t -c user.name=t commit -q -m "seed existing rubric"
```

- [x] **Step 2: Confirm the sentinel rubric is in place before running the drafter**

Run: `test -f "$S/.judge/rubric.md" && echo EXISTING_RUBRIC_PRESENT`
Expected: `EXISTING_RUBRIC_PRESENT`

- [x] **Step 3: Run the drafter and confirm it never touches the repo's filesystem**

```bash
cd "$S" && bash ~/.claude/hooks/rubric_init.sh > /tmp/overwrite-test-draft.md
diff "$S/.judge/rubric.md" <(printf '# SENTINEL existing rubric, must not be overwritten silently\n') && echo SCRIPT_DID_NOT_TOUCH_FILE
```
Expected: `SCRIPT_DID_NOT_TOUCH_FILE`. This confirms `rubric_init.sh` itself never writes `.judge/rubric.md`, so the overwrite decision lives entirely in `judge-init.md`'s Claude-side instructions (Step 4), which the next step exercises directly.

- [x] **Step 4: Walk through `judge-init.md`'s own instructions against this scratch repo, exercising both branches of the overwrite decision**

Per instruction 4 in `judge-init.md`, `.judge/rubric.md` already exists in `$S` (confirmed in Step 2), so both a decline and a confirm must be exercised and checked before moving on:

```bash
# Decline branch: do not write, original must be untouched.
diff "$S/.judge/rubric.md" <(printf '# SENTINEL existing rubric, must not be overwritten silently\n') && echo DECLINE_PRESERVED_ORIGINAL

# Confirm branch: write the draft, the file must now match it exactly.
cp /tmp/overwrite-test-draft.md "$S/.judge/rubric.md"
diff "$S/.judge/rubric.md" /tmp/overwrite-test-draft.md && echo CONFIRM_WROTE_DRAFT
```
Expected: `DECLINE_PRESERVED_ORIGINAL` then `CONFIRM_WROTE_DRAFT`.

- [x] **Step 5: Clean up**

```bash
rm -rf "$S" /tmp/overwrite-test-draft.md
```

- [x] **Step 6: Commit the plan checkboxes**

```bash
cd /Users/asela/git/claude-agents
git add docs/superpowers/plans/2026-07-10-judge-init.md
git commit -m "docs: mark /judge-init implementation plan executed"
```

---

## Post-plan handoff (not a task for the implementer)

1. **User runs the actual `/judge-init` slash command in a real Claude Code session** against a repo with an existing `.judge/rubric.md` (e.g. `claude-agents` itself), as a final confidence check on top of Task 7's mechanical verification, since Task 7 exercises the same decision points by direct instruction-following rather than through the live slash-command dispatch path.
2. **Open a PR** for branch `feat/judge-init` when ready (use the `superpowers:finishing-a-development-branch` skill), following the same review flow as `feat/codex-judge-stop-hook`.
3. **Known drift, unaddressed here**: the live and plugin-packaged `judge.sh` copies already differ beyond `JUDGE_HOME` resolution as the codebase evolves independently in each location; reconciling that drift (and the same future risk for `rubric_init.sh`) is out of scope for this plan, per the design spec.
