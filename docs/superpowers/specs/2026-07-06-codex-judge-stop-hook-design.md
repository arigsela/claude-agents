# Codex-as-Judge Stop Hook — Design

**Date:** 2026-07-06
**Status:** Approved
**Owner (harness):** Claude Code — all `~/.claude` resources
**Owner (judgment content):** Codex CLI — per-repo `.judge/rubric.md`

## Problem

Claude Code declares work "done" without independent review. We want an
LLM-as-judge loop where a different model family (Codex CLI) grades Claude's
diff against a versioned rubric at the moment Claude tries to stop, and a
`rework` verdict blocks the stop and feeds the rationale back into Claude's
context so it self-corrects before finishing. This is the local calibration
lab for a future GitHub Actions required check.

## Architecture

Claude Code (generator) finishes a turn → Stop hook fires → `judge.sh` gates,
diffs, and asks Codex for a verdict:

```
Stop event ──▶ judge.sh
               │ gate: repo has .judge/rubric.md?  ──no──▶ exit 0 (instant)
               │ gate: rounds < 3?  ──no──▶ log "escalate", exit 0
               │ diff: git add -N . && git diff HEAD  ──empty──▶ exit 0
               │ prompt: rubric + diff → temp file (no bash substitution)
               ▼
       codex exec --sandbox read-only --output-last-message <tmpfile>
               │
               ▼ parse verdict JSON from last-message file
        approve ──▶ log, clear round counter, exit 0
        rework  ──▶ log, rounds+1, rationale → stderr, exit 2  (Claude continues)
        error   ──▶ log "judge_error", exit 0  (fail open, visibly)
```

Opt-in is per repo: the hook exits instantly unless the repo root contains
`.judge/rubric.md`. Cross-family judging is preserved — Claude never authors
the rubric its own work is graded against.

## Components

| Path | Owner | Responsibility |
|---|---|---|
| `~/.claude/hooks/judge.sh` | Claude | Dual-mode script. Stop-hook mode: reads hook JSON on stdin, exit-2 block contract. `--manual` mode: same pipeline, prints verdict human-readably, always exits 0. |
| `~/.claude/judge/prompt.default.md` | Claude | Prompt template owning the JSON contract (`{{rubric}}`/`{{diff}}` placeholders). A repo's `.judge/prompt.md` overrides it if present (none planned for v1). |
| `~/.claude/settings.json` | Claude | Adds `hooks.Stop` → `bash ~/.claude/hooks/judge.sh`, timeout 180s. No other changes. |
| `~/.claude/commands/judge.md` | Claude | `/judge` slash command → runs `judge.sh --manual` for on-demand mid-task verdicts. |
| `~/.judge-log/verdicts.jsonl` | Claude (runtime) | One JSON line per invocation: timestamp, repo, session id, round, verdict, criteria scores, rationale, duration, error class on failures. |
| `<repo>/.judge/rubric.md` | Codex | Opt-in switch + repo-tailored criteria (correctness, security, tests, scope), under ~60 lines. Codex authors it for `claude-agents` and for the `~/git/kubernetes` test repo. |

## Judge output contract

The prompt template instructs the judge to respond with ONLY a single JSON
object, no markdown fences, no prose:

```json
{"rationale": "<specific findings, file:line where possible>",
 "criteria": {"correctness": 5, "security": 4, "tests": 4, "scope": 5},
 "verdict": "approve"}
```

- Criteria scores are integers 1–5; `rationale` must precede `verdict`.
- `verdict` is `rework` if any criterion ≤ 2 or any security issue exists.
- The judge evaluates only the provided diff, never pre-existing code, and
  must not reward verbosity or unnecessary refactors.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Activation | Opt-in per repo via `.judge/rubric.md` presence | Hook is installed globally but costs nothing in repos that haven't opted in; no Codex call in chat-only sessions. |
| Rubric authorship | Codex, for all repos including the test repo | Keeps judgment content fully cross-family; Claude never writes the rubric grading its own diffs. |
| Judge model | Codex CLI default config; `JUDGE_CODEX_ARGS` env var as escape hatch | Tune model/effort in `~/.codex/config.toml`, not the hook. |
| Diff baseline | `git diff HEAD` (after `git add -N .` to capture new files) | Simple; acceptable that pre-session manual edits get judged. Session-start snapshots deferred. |
| Script structure | Single dual-mode `judge.sh` | `/judge` manual runs and the Stop hook share one code path, so manual calibration exactly matches automatic behavior. |
| Loop guards | Hard cap of 3 rework rounds per session (counter file keyed by session id in `/tmp`). Continuation stops (`stop_hook_active=true`) ARE re-judged — that is the rework loop working; the round counter alone decides when to stop. `stop_hook_active` serves only as a backstop: if true while the counter file is missing or unreadable, approve rather than risk an unbounded loop. | Converts judge/generator disagreement loops into a logged `escalate` + graceful approve. |
| Failure policy | Fail open on every judge error (codex missing, auth, timeout, unparseable output), always logging the error class | A judge outage degrades to normal Claude Code behavior; the log makes silent-dead-judge impossible to miss. |
| Verdict parsing | `codex exec --output-last-message <file>`, parsed with `jq` | Survives multi-line/pretty-printed JSON; no fragile stdout grepping. |
| Prompt assembly | Temp file + stdin redirect | Avoids bash `${var//}` metacharacter bugs and ARG_MAX limits on large diffs. |
| Hook timeout | 180s | Codex on a large diff can exceed the originally proposed 120s; timeout kill fails open. |

## Edge cases

- Not a git repo → exit 0.
- Unborn HEAD (fresh repo, no commits) → diff against the empty tree object.
- Empty diff → exit 0, no Codex call.
- `jq` missing → fail open (it is the only parse dependency; verified present).
- Intent-to-add entries left behind by `git add -N` are harmless (they mark
  new files tracked-with-no-content and do not stage content).
- Round counter files are per-session-id in `/tmp`; uniqueness of session ids
  makes them self-expiring, cleared on approve.

## Testing

1. **Unit sanity (Claude runs):** synthetic hook JSON piped into `judge.sh`
   in a scratch git repo — (a) no `.judge/` → instant exit 0; (b) empty diff
   → exit 0; (c) seeded bad diff (fake hardcoded secret) → `rework`, exit 2,
   rationale on stderr; (d) codex off PATH → fail open, `judge_error` logged.
2. **Loop-guard test (Claude runs):** pre-set round counter to 3 → graceful
   `escalate` approve.
3. **Live end-to-end (user runs):** in `~/git/kubernetes` after Codex drops
   its rubric — ask Claude to hardcode a fake secret in a chart value; expect
   Stop hook → Codex `rework` → Claude self-corrects → `approve`.
4. **Calibration (user, ~2 weeks):** review `~/.judge-log/verdicts.jsonl`
   against personal review judgment before promoting the pattern to a
   required CI check.

## Out of scope (v1)

Codex's rubric content, the GHA/CI variant, SubagentStop judging,
session-start diff snapshots, per-repo prompt overrides, and any automatic
escalation channel beyond the `escalate` log entry.
