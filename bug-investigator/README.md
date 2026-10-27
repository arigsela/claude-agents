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

6. **Fix** (full mode only, input `fix`, default on): when the *verified* verdict is `likely_cause`
   and there is a verified code location (`likely_cause.code_verified`, or a supported hypothesis
   citing verified `file` evidence), a second Claude step in the same read-only job edits the app
   checkout (`fix_prompt.md`, `fix.schema.json`): the smallest change that restores the documented
   rule plus one regression test. `fix-check` (no Claude) turns the changes into `fix.patch` and
   writes `fix-full.json` (`proposed` / `skipped` / `rejected` with the reason); the comment shows
   "Proposed fix" or "No fix proposed: <reason>".
7. **Propose** (separate `propose` job: `contents`, `pull-requests`, `issues: write`; no Claude):
   re-checks the patch, applies it on `bug-investigator/issue-<N>` (from the investigated commit),
   re-checks what was applied, commits as `github-actions[bot]`, force-pushes, opens the PR (label
   `bug-investigator`) or, on a re-run, edits the open one, and posts or edits one short comment
   ("🛠 Proposed fix: #PR …"). It starts **no CI**: the reviewer reads the diff, then runs CI from
   Actions → ci → Run workflow on the branch. Nothing merges automatically.

**Fix safety.** Claude never holds a write token, and no code it writes runs on the runner:

| Check | Where |
|---|---|
| The Grafana token file and the deploy checkout are deleted after verify; fix-prep refuses to start if the token file or a Grafana token variable exists | action step, `fix.secrets_gone` |
| Tests run only through `run-tests.sh`: a copy of the tree without `.git`, mounted read-only into `python:3.12-slim@sha256:…` with `--network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534:65534`, no runner environment, tmpfs `/tmp`, 300 s limit; the image is pulled before Claude starts (`--pull never` after) | `run-tests.sh` |
| The fix agent's tools: Read/Grep/Glob, Edit/Write, `git diff`, `git status`, and the one exact `bash <action>/run-tests.sh <checkout> <test-command>`; no MCP, no web, no gh. The hook enforces it (fix mode) and fix-prep self-tests the hook | `settings.py`, `hook.py`, `scope.py` |
| Edit/Write only inside the app checkout, never `.github/`, `.claude/`, `docs/`, any `.git/`, root dotfiles and `*.cfg/*.ini/*.toml`, or build/test config at any depth (`pyproject.toml`, `setup.*`, `tox.ini`, `pytest.ini`, `conftest.py`, `requirements*`, lock files, `Makefile`, `Dockerfile*`, `.pre-commit-config.yaml`, `.gitattributes`, `.gitmodules`) | `scope.protected_reason` (hook and patch filter) |
| `.git/config` must be unchanged after the fix (else restored and rejected); the scripts run git with `core.fsmonitor=false`, `core.hooksPath=/dev/null`, no system/global config | `fix.py` |
| The patch is rejected if it is empty, touches a protected path, has a symlink/submodule/binary/rename, more than 400 changed lines, a secret-looking added line, or anything the strict parser does not recognise | `fix.check_patch_text` |
| Tests must not be weakened: at least one new `def test_…`; in existing test files only additions; no deleted test files; no added skip/xfail/expectedFailure/skipTest/SkipTest; existing test functions unchanged (AST); no test defined twice; no new test that returns first | `fix.check_test_integrity`, `fix.check_test_sources` |
| Sandbox runs: the original tree and the patched tree (`-v`): after must pass, report `Ran N` with N ≥ before + 1 (0 always fails), keep every test name that ran before, skip no more than before; then the original code plus the new tests must **fail** (else rejected). Only a sandbox error on that last run lets a fix through unproven, and the PR says so | `fix.evaluate` |
| Only a proposed patch is kept in the artifacts; a rejected one leaves its file list, line counts and reason. The agent's log is kept scrubbed, and not at all when the patch held a secret | `fix.check_main` |
| The propose job re-checks the patch (checksum, the same parser and test rules) and, after `git apply --index`, the staged paths and modes; it runs no tests and no Claude | `fix.propose` |

Repo setting needed: Settings → Actions → General → "Allow GitHub Actions to create and approve pull
requests". `ci.yml` needs `workflow_dispatch` so a reviewer can start CI on the fix branch.

Residual risks: the fix agent sees issue-derived text (prompt injection), so its edits are only as
trustworthy as a stranger's PR: that is why the patch is filtered, tested in a sandbox, and merged
only by a person. Within the investigate job the agent's environment still holds the Anthropic key
and the read-only job token (as in the investigation step).

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
`anthropic-api-key`, `model` (`claude-sonnet-5-5`), `max-turns` (40), `namespace` (`taskboard`),
`fix` (`true`), `test-command` (`python3 -m unittest discover -s tests`, plain words; runs only in
the sandbox), `fix-max-turns` (30); `command: post` with `comment-dir` for the post job;
`command: propose` with `comment-dir` (the downloaded full-mode artifact) for the propose job.
Outputs: `work-dir`, `findings-file`, `comment-file`.

## What keeps the agent in bounds

The Grafana Viewer token can read every namespace, and claude-code-action passes the whole process
environment to Claude. So:

| Layer | What it does |
|---|---|
| Job token | The investigate job (the investigation and the fix agent) is read-only (`contents`, `issues`, `pull-requests: read`); only the `post` job (comments) and the `propose` job (the fix branch and PR, no Claude) can write, and only from the artifacts. The investigate checkout uses `persist-credentials: false`. |
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

## In the cluster (the kagent version)

Two modules serve the platform version, where there is no PreToolUse hook and no Grafana token:

- `telemetry.py` queries Loki and Prometheus directly (`LOKI_URL`, `PROMETHEUS_URL`; defaults are
  the in-cluster services in `logging`). `query()` returns the same data frames as `grafana.query`,
  so `verify --telemetry direct` re-runs every query with no token; links still open Grafana Explore.
  Every function runs the scope check before any HTTP request.
- `mcp_server.py` is a stdio MCP server (newline-delimited JSON-RPC) with mcp-grafana's tool names
  and arguments: `query_loki_logs`, `query_loki_stats`, `query_prometheus`, `list_loki_label_names`,
  `list_loki_label_values`. Every call runs `scope.check_tool_call`, exactly as the hook does; a
  refused or failed call is a tool result with `isError: true`. Run it as
  `python3 -I /core/src/bug_investigator/mcp_server.py` (stdlib only; agentgateway serves it over HTTP).

## Local runs

```bash
uv run --project bug-investigator pytest          # all tests (fake gh, real local git, fake Grafana)
python3 -I bug-investigator/run.py hook --root "$PWD" <<< '{"tool_name":"mcp__grafana__query_prometheus","tool_input":{"datasourceUid":"PBFA97CFB590B2093","expr":"up","endTime":"now"}}'; echo $?   # 2
python3 -I bug-investigator/run.py verify --mode full --findings f.json --repo o/r --issue 1 --app-dir . --out v.json
python3 -I bug-investigator/run.py render --mode full --findings v.json --out comment.md
```

Runtime is the runner's `python3` (3.10+), standard library only, plus `git` and `gh`.
