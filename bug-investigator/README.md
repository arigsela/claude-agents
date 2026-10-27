# bug-investigator

A composite GitHub Action that investigates a bug issue with Claude and posts one comment whose
every link has been checked by a script. Design: `docs/superpowers/specs/2026-10-27-bug-investigator-design.md`.

**How it works** (one job per mode, then a separate `post` job)

1. **Gather** (script): the ticket; full mode adds merged PRs of the last 14 days with their review
   discussion and when each went live, the deploy timeline from the deploy repo's
   `code-configmap.yaml` history, past `bug` issues with the PRs that fixed them, the docs index
   (files and rule IDs) and telemetry pointers. Issues and PRs labelled `rehearsal` are left out.
2. **Investigate** (`anthropics/claude-code-action`, pinned): Claude follows the method in
   `prompt.md` and returns findings matching `findings.schema.json`.
3. **Verify** (script): every evidence item is checked (commit exists, PR/issue exists, file line
   and quote, doc quote verbatim, Loki/Prometheus query re-run in its window). Failures are dropped
   and listed; unsupported hypotheses become `untested`; `likely_cause` without a supported
   hypothesis and `not_a_bug` without a verified docs rule become `unclear`. Secrets are scrubbed.
4. **Render** (script): `comment-<mode>.md` with GitHub and Grafana Explore links and a footer
   (mode, model, turns, duration, cost, "verified N of M evidence links", run link). It includes a
   collapsed **"How the agent worked"** trail (`trail.py`, saved as `trail-<mode>.json`): the agent's
   one-sentence narration before each tool call (the prompt asks it to think out loud), then the tool,
   a compact input (repo-relative path, pattern, command, LogQL/PromQL and window) and a compact result
   (`74 lines`, `5 log lines`, `no results`, `error: …`, `⛔ blocked: …`). Counts only: never file
   contents or log lines. Grafana queries link to Explore and file reads to the blob at the
   investigated SHA; capped at 40 lines.
5. **Post** (separate job, `issues: write`): edits this mode's earlier comment (hidden marker) or
   creates one, and adds the `investigated` label. Nothing else writes.

**Modes.** `full` sees everything above plus Grafana. `n8n` is the baseline a ticket-to-LLM flow
gets: the ticket and the code at HEAD (shallow checkout, `docs/` removed), Read/Grep/Glob only.
Its findings go through the same verify step.

## Use

See `examples/taskboard-investigate.yml` (labels `bug` and `compare`, `workflow_dispatch` re-runs):

```yaml
- uses: actions/checkout@<sha>
  with: {fetch-depth: 0, persist-credentials: false}   # 1 for n8n mode
- uses: arigsela/claude-agents/bug-investigator@<commit-sha>
  with:
    mode: full
    issue-number: ${{ github.event.issue.number }}
    grafana-token: ${{ secrets.GRAFANA_TOKEN }}
    anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

Inputs: `mode`, `issue-number`, `app-repo` (default: this repo), `deploy-repo`
(`arigsela/kubernetes`), `deploy-path` (`base-apps/taskboard`), `grafana-url`, `grafana-token`,
`anthropic-api-key`, `model` (`claude-sonnet-5-5`), `max-turns` (40), `namespace` (`taskboard`);
`command: post` with `comment-dir` for the post job. Outputs: `work-dir`, `findings-file`,
`comment-file`.

## What keeps the agent in bounds

The Grafana Viewer token can read every namespace, and claude-code-action passes the whole process
environment to Claude. So:

| Layer | What it does |
|---|---|
| Job token | The investigate job is read-only (`contents`, `issues`, `pull-requests: read`); only the `post` job can write, and only from the rendered artifact. Checkout uses `persist-credentials: false`. |
| Grafana token | Never in an environment variable: written to a 0600 file under `$RUNNER_TEMP`, read by mcp-grafana through `GRAFANA_SERVICE_ACCOUNT_TOKEN_FILE` and by verify. The self-test fails the run if any variable holds it. Deleted at the end. |
| mcp-grafana 2.1.1 (pinned binary, sha256 checked) | `--enabled-tools loki,prometheus --disable-write --disable-api --disable-rendering`, and `--loki-enforced-matchers 'namespace="taskboard"'`: the server ANDs that matcher into every Loki selector, so Loki stays scoped even if everything else failed. |
| PreToolUse hook (`run.py hook`, `scope.py`) | Grafana: only `query_loki_logs`, `query_loki_stats`, `query_prometheus`, and the label-list tools with a scoped matcher; fixed datasource uids; every LogQL stream selector needs `namespace="taskboard"` exactly; every PromQL selector needs it or a `taskboard_` metric name; unknown syntax is rejected. Bash: one read-only `git log/show/blame/diff` or `gh pr/issue view/list/diff` at a time, no shell operators, no paths outside the checkouts, no `--output`/`--no-index`/`--contents`. Read/Grep/Glob: inside the checkouts (symlinks resolved). Any hook error blocks. |
| Self-test | Before Claude starts, the exact hook command must block an unscoped query, a foreign namespace, `env` and `/etc/passwd`, and allow a scoped query. |
| Claude settings | `blockReadsOutsideWorkingDirectories`, Read denies for the action directory and `$RUNNER_TEMP`, an explicit tool allowlist, no Write/Edit/Web/Task. The app repo's own `.claude/settings*.json` and `.mcp.json` are removed first; the action's code is made read-only. |
| Verify | Runs the same `scope.check_query` before every Grafana HTTP call; out-of-scope evidence is dropped. |

## Adapters (the hand-over to Monday and Datadog)

| Adapter | Here (PoC) | Monday / Datadog |
|---|---|---|
| `tickets` (`tickets.py`) | `gh issue view/list`, `closedByPullRequestsReferences`, issue comment (edit by marker), label | Monday GraphQL: `items` (name, column values, updates) for the ticket and past bugs in a "Done" group; `create_update` / `edit_update` for the comment. Monday webhooks cannot send an auth header, so trigger through a small relay that checks the challenge and calls `workflow_dispatch`. |
| `telemetry` for the agent | mcp-grafana (Loki, Prometheus) | Datadog MCP server, `core` and `error-tracking` toolsets; the hook checks `service:`/`env:` scoping instead of `namespace=`. |
| `telemetry` for verify (`grafana.py`) | `POST /api/ds/query`, Explore links | `POST /api/v2/logs/events/search`, `/api/v2/spans/events/search`, metrics `query` API; Datadog log/trace explorer links. |
| `code` | two checkouts + `gh` | their backend and frontend repos + `gh` (same). |

## Local runs

```bash
uv run --project bug-investigator pytest          # all tests (fake gh, real local git, fake Grafana)
python3 -I bug-investigator/run.py hook --root "$PWD" <<< '{"tool_name":"mcp__grafana__query_prometheus","tool_input":{"datasourceUid":"PBFA97CFB590B2093","expr":"up","endTime":"now"}}'; echo $?   # 2
python3 -I bug-investigator/run.py verify --mode full --findings f.json --repo o/r --issue 1 --app-dir . --out v.json
python3 -I bug-investigator/run.py render --mode full --findings v.json --out comment.md
```

Runtime is the runner's `python3` (3.10+), standard library only, plus `git` and `gh`.
