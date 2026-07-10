# codex-judge

A Codex-as-judge plugin for Claude Code. It runs the [Codex CLI](https://github.com/openai/codex)
as an **adversarial code reviewer** against your working-tree diff and blocks
Claude from stopping until the diff passes a per-repo rubric — plus a `/judge`
command to run the same review on demand.

## What you get

- **Stop hook** (`hooks/judge.sh`): on every stop, judges the diff. Verdict
  `rework` blocks the stop and feeds the findings back to Claude (up to 3
  rounds per session); `approve` lets it stop. Fail-open on any error.
- **`/judge` command**: run the judge manually and see the verdict/rationale.

## Requirements

- **codex CLI** on `PATH`, authenticated. Without it the hook fails-open
  (approves everything) — it never blocks your work on a broken setup.
- **jq** and **git**.

## Activation is opt-in, per repo

The judge only runs in a repo that contains **`.judge/rubric.md`**. Create one
with your review criteria. Optionally add **`.judge/prompt.md`** to override the
default prompt (`prompt.default.md`); use the `{{rubric}}` and `{{diff}}`
placeholders.

```
your-repo/
  .judge/
    rubric.md      # required — your review criteria (opt-in switch)
    prompt.md      # optional — overrides prompt.default.md
```

## Config knobs (env vars)

| Var | Default | Purpose |
|-----|---------|---------|
| `JUDGE_CODEX_ARGS` | — | Extra flags passed to `codex exec` (word-split) |
| `JUDGE_LOG_DIR` | `~/.judge-log` | Verdict log (`verdicts.jsonl`) |

Round cap is 3 rework rounds per session (`MAX_ROUNDS` in `judge.sh`).

## Install

Via the marketplace this plugin ships in:

```
/plugin marketplace add arigsela/claude-agents
/plugin install codex-judge@claude-agents-marketplace
```
