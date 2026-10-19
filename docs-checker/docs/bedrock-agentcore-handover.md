# docs-checker → Bedrock AgentCore: handover

For the Claude session that ports docs-checker to Amazon Bedrock AgentCore and points it at
the work repositories. Written 2026-10-19, right after the homelab deploy. Read this first, then
the files it names; you should not need anything from the session that wrote it.

## 1. What you are inheriting

docs-checker is a read-only LangGraph agent that finds **stale statements in documentation**:
lines that no longer match the configuration files the doc describes, and source files that no
longer exist. For each one it reports evidence (`file:line`) and, where safe, a minimal
corrected line. It never writes to a repository.

It is live in Ari's homelab (kagent 1.0.0-alpha14 on k3s, a "BYO" runtime in a gVisor
Substrate sandbox), checking `arigsela/kubernetes`:

- Agent `kagent/docs-checker` is Ready on image `docs-checker:51f7c166faeb`
  (`852893458518.dkr.ecr.us-east-2.amazonaws.com/docs-checker@sha256:1a2a11aa…`).
- First live check: `ask-hk --agent kagent/docs-checker "check base-apps/kagent/docs.md"`
  ran in 2m23s for $0.011. Coverage was incomplete (see §6, the per-doc call cap).
- The kagent eval gate scored it 12/12 on its first run.
- A weekly CronJob runs `check all` on Mondays at 14:00 UTC and posts to Slack.

**Code:** `arigsela/claude-agents`, branch `feature/docs-checker`, directory `docs-checker/`.
Locally it is the worktree
`/Users/arisela/git/claude-agents/.claude/worktrees/agent-aee2de46c29529766`. The branch was
**not pushed** as of this writing, so ask Ari before you assume it is on GitHub. Tests:
`cd docs-checker && uv sync --extra dev && .venv/bin/pytest -q` (983 pass, 0 skipped, with no
network and no key).

**Must-read, in order:**
1. `docs/superpowers/specs/2026-10-18-docs-checker-design.md`: the design (intent, graph,
   levers, guardrails, evals, memory).
2. `docs-checker/README.md`: configuration, container, memory.
3. `docs-checker/HANDOFF.md`: every design decision made during the build ("rulings"), each
   with its cost if wrong. Many of them you will revisit.
4. `docs-checker/evals/README.md`: the eval harness, labelling rubric and money rules.

## 2. Architecture in one screen

| Layer | Modules (`src/docs_checker/`) | Portable to AgentCore? |
|---|---|---|
| Graph | `graph.py` (run: intake → scope → dispatch → per-doc subgraph → collect → report), `graph_doc.py` (per doc: load → extract claims → evidence → judge → fix → gate), `nodes.py`, `state.py`, `request.py` | **Yes, as is** |
| Cost levers | `levers.py` (cache_prefix, typed_handoffs, short_circuit, tools_on_demand, retry_limits, right_size, shrink_results), `ledger.py` (4 token buckets, budget reservations, rate card), `llm.py` | Yes, but the **rate card** is Anthropic-API pricing and needs Bedrock prices |
| Guardrails | `gate.py` (the fix gate: replacement rules G0-G5 + digest handling, the AngleGate seam), `prompts.py` (data-block isolation, validate_replacement), `redact.py`, `render.py` | Yes |
| Evidence | `scope.py` (which docs), `frontmatter.py` (`sources:`), `evidence.py`, `repo.py` | Partly: see §4 |
| Memory | `memory.py` (caller-held snapshot: the caller sends it in and gets the updated one back; no DB), `dismissals.py` | Yes; only where the caller stores it changes |
| Models | `models.py` (`ChatAnthropic`, lazy), `config.py` (per-node model and effort) | Needs a Bedrock client |
| Tools | `tools.py`: the MCP tool belt over a read-only GitHub MCP server (`get_file_contents`, `search_code`, `list_commits`, `get_commit`), pinned to one repo | Yes if work is on GitHub; else new tools |
| Runtime | `server.py` (A2A **gRPC** + `/readyz` on 8081), `executor.py` (kagent TaskStore, HITL pauses), `paused.py`, `entry.py` | **No: rewrite this layer** (§3) |
| Evals | `evals/` (replay cassettes, $20 per-user spend ledger, maximum-matching scorer, curated set, drift demo) | Yes; needs work eval sets |

The graph, the levers, the guardrails and the memory format don't know they're on kagent. The
kagent coupling sits in `server.py`, `executor.py`, `paused.py` and parts of `config.py`
(`KAGENT_CONFIG_JSON`).

## 3. Porting to AgentCore Runtime

What AgentCore expects (verified from AWS docs on 2026-10-19; re-check before building):

- **A2A protocol:** JSON-RPC 2.0 over HTTP on **port 9000** at path `/`, an Agent Card at
  `/.well-known/agent-card.json`, bound to `0.0.0.0`, and an **ARM64** image. The platform adds a
  session-id header.
  [A2A protocol contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a-protocol-contract.html)
- **HTTP protocol (alternative):** port 8080, `POST /invocations` (plus a ping route).
  [Runtime service contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html)

What that means here:

1. **New server adapter.** Replace `server.py`'s gRPC server and kagent TaskStore wiring with
   a2a-sdk's JSON-RPC HTTP app (a2a-sdk 1.2.2 is already a dependency), keeping
   `DocsCheckerExecutor` as the `AgentExecutor`. Drop `KAGENT_CONFIG_JSON` parsing for AgentCore:
   read settings from env or a config file. `build_agent_card` already builds the card.
2. **ARM64 image.** The Dockerfile pins `--platform linux/amd64` and a bookworm base with a
   uv-managed Python 3.13. The bookworm and managed-Python choices exist for gVisor
   checkpoint/restore, which AgentCore doesn't use, so you can revisit them.
   `tests/test_dockerfile.py` pins today's invariants; update it with intent.
3. **Models through Bedrock.** `models.py` builds `ChatAnthropic`. Switch to
   `ChatBedrockConverse` (langchain-aws) or the Anthropic SDK's Bedrock client, authenticated by
   the runtime's IAM role. Then:
   - re-price `ledger.py`'s rate card for Bedrock (on-demand vs cross-region inference
     profiles);
   - check how prompt caching (the `cache_prefix` lever) and `output_config.effort` map on
     Bedrock;
   - keep `ALLOWED_MODELS` honest.
4. **Checkpoints and pauses.** Today they live in SQLite under `/data`, because kagent's
   Substrate snapshots persist `/data` between turns. Don't assume AgentCore's local disk
   survives a session. Use a durable checkpointer (DynamoDB, or AWS's LangGraph checkpointer)
   if you keep interactive pauses (fix approvals); or drop pauses and run scheduled mode only.
   `server._open_checkpoints` already falls back to in-memory with a warning.
5. **Tools.** The agent calls a read-only GitHub MCP server
   (`github-mcp-server --read-only --toolsets repos`). On AWS:
   - run that server behind AgentCore Gateway, or call it directly;
   - keep the token in AgentCore Identity or Secrets Manager, never in env literals;
   - keep it **read-only server-side**: the tool belt filters tools by name, but a read-only
     server is the real control.
6. **Trigger and memory storage.** The homelab CronJob calls the agent weekly and stores the
   memory snapshot in a ConfigMap, with optimistic concurrency, idempotent delivery and alerts
   (`scripts/docs_checker_trigger.py` in the kubernetes repo is the reference). The equivalent
   on AWS is EventBridge Scheduler → a small Lambda → the runtime, with the snapshot in S3 or
   DynamoDB (conditional writes). Keep the rules:
   - always write back the returned snapshot after a completed run, and never after a failed
     one;
   - deliver at most once per run id;
   - post a visible alert on any failure;
   - deliver the report even when memory can't be saved.
7. **Delivery.** It posts a Slack digest today (≤3000 chars, the `docs-checker/slack` data
   part). Ask Ari what the work team uses.

## 4. Generalising beyond `arigsela/kubernetes`

These are repo-specific today:

1. **One repo per process:** `DOCS_CHECKER_REPO` (`config.py:275`); the tools refuse others.
   Options: one runtime per repo, or a per-request repo checked against an allowlist.
2. **Which docs:** `scope.py:25`, roots `base-apps`, `docs`, `recovery`, with exclusions for
   this repo's layout. Make it a per-repo profile (roots, exclusions, max docs).
3. **The front-matter contract, the big one.** A doc is checked only if its YAML front matter
   lists `sources:`, the files it describes (`frontmatter.py`). The kubernetes repo adopted that
   convention; the work repos almost certainly haven't. Either:
   - (a) the teams add `sources:` to the docs that matter (cheap, precise, keeps every
     guarantee); or
   - (b) the agent infers what a doc describes, for example docs next to code, or links and
     paths found in the text. That means real work, and it loosens the evidence model the fix
     gate relies on.

   Ask Ari before choosing.
4. **Prompts name the domain.** `prompts.py` EXTRACT and INTAKE say "arigsela/kubernetes" and
   "Kubernetes manifest, Helm values, Argo CD Application". Template them per profile.
5. **Evidence and gate assume configuration files.** Claim kinds: image, host, namespace and
   name (`gate.py` `NAMED_KINDS`), versions, ports, paths. Other assumptions: `#` comments are
   stripped and not evidence (ruling R1d), and digest-pinned images are handled (F2). Terraform
   and shell fit; docs about application behaviour or APIs would need new kinds and evidence
   rules.
6. **Evals are per repo type.** The 943 labels in `evals/labels/` are kubernetes-only, and
   precision doesn't transfer. Build a small labelled set per work repo type with
   `python -m docs_checker.evals.curate` (packets → two labellers → merge → adjudicate →
   validate). The rubric is in `evals/README.md`. Run evals through the harness with its
   per-user spend cap.

## 5. Lessons from the homelab deploy (they will bite again)

- **Follow-up turns cold-boot the process.** This is the biggest one.
  - The first turn of a new session restores the golden snapshot (`scope: full`, the whole
    process, about 3 s).
  - After each turn, kagent alpha14 checkpoints **only `/data`** (`scope: data`). The next turn
    in the same session therefore starts the process from scratch, paying the full Python
    startup (about 27 s).
  - The kagent UI gives a session about 5 s to become available, then cancels the restore:
    "input was not accepted; retry after the session becomes available".
  - Go agents boot in under a second, so they never hit this.
  - Lesson: a turn's cold boot must reach readiness in a few seconds. The fix shipped in
    claude-agents `68f145a` is `docs_checker.front`, a standard-library-only front process
    (about 185 ms to start under emulation). It answers `/readyz` at once on a session boot,
    holds A2A connections, and splices them to the real server (a loopback child) once that
    server is up. On the golden boot (atespace `ate-golden`) it waits for the server, so new
    sessions restore a warm snapshot (capped at 25 s). Check whether AgentCore sessions resume a
    memory snapshot or cold-start; if they cold-start, keep this pattern.
- **Readiness budget.** Substrate gave the golden actor 30 s to answer `/readyz`. Python
  imports alone took **23.5 s** under gVisor (7 s under qemu locally), and the first cold
  attempt missed the window. AgentCore cold starts are different but count too. Keep startup
  lean: lazy-import heavy SDKs where the design allows, or precompile bytecode
  (`compileall --invalidation-mode unchecked-hash`). Measure in the target sandbox, not
  locally.
- **Only stdout was visible.** The sandbox showed stdout, and Python logging and tracebacks
  went to stderr. That's why the first failure looked silent. `entry.py` prints before the heavy
  imports, and `main()` logs to stdout. kagent-core's import-time `configure_logging()` only
  restyles an existing handler, so install yours first. Check what AgentCore captures.
- **Don't assume the uid.** The image runs as uid 65532, but the sandbox ran it as uid 0. A
  local reproduction with a root-owned `/data` sent me after the wrong cause for an hour.
  Reproduce the environment, not your guess about it.
- **Eval-gate race.** A post-deploy eval that runs before the agent is ready scores nothing
  ("no ready prepared revision"). Wait for readiness first.
- **Per-doc call cap.** 12 model calls per doc left 5 claims unjudged on a 477-line doc
  (status `incomplete`). Tune it with the evals, not by guessing; `right_size` and `typed_handoffs`
  change the count.
- **Exact-digest admission.** The homelab admits a BYO image only on an exact digest, and every
  rebuild needs a reviewed re-pin. On AWS, pin the runtime's image by digest too.

## 6. What stays non-negotiable (from the design)

- Read-only: no write tools bound, ever. Evidence never comes from documentation.
- Every proposed fix passes the fix gate. Injected instructions in a doc are data. The eval set
  has a canary doc whose `fails_if` predicates must stay green.
- Budgets: per-run and per-doc caps, reservations before each model call, and
  `BudgetExceeded` ends work gracefully (skipped-budget docs are picked up first next run).
- Evals: the paid ones go through the harness and its spend ledger, under a cap; a frozen
  holdout is never used for tuning.

## 7. Open questions for Ari (ask before building)

1. Where do the work docs live: next to the code, a docs repo, or a wiki? This decides §4.3.
2. Which git host (GitHub, GitHub Enterprise, GitLab, Bitbucket)? This decides §3.5.
3. Which Claude models are available through the work Bedrock account, in which region, and with what
   per-run budget?
4. Where should findings go (Slack, Teams, Jira, PR comments)?
5. One AgentCore runtime per repo, or one runtime with a repo allowlist?

## 8. Homelab follow-ups you do not own

Ari's list, not yours, so don't wait on these:
- speed up docs-checker's import time;
- remove the old `byo-images` entry and correct SPEC T131's cause note;
- make the eval gate wait for Ready;
- tune the per-doc cap;
- run the paid eval pilot;
- review the labels.
