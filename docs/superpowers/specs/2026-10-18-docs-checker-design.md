# docs-checker: a LangGraph BYO agent that finds stale docs — Design

Date: 2026-10-18 · Owner: Ari Sela · Status: draft for review

Supersedes the purpose chosen in `2026-10-18-homelab-scout-design.md` (repo and catalog Q&A, which overlaps
`homelab-knowledge`). That document's findings on the kagent 1.0 BYO contract (§3), the cluster's gates (§4),
the ledger (§6.1) and library versions (§10) still hold and are not repeated here; this design reuses the
skeleton built for it (`homelab-scout/`: server, executor, config, ledger, llm, models, gate, tools).

## 1. Intent

Ari wants one agent where they can practise, on a real job, what ATL DevCon 2026 taught: a LangGraph graph
with real nodes, the seven cost levers measured one at a time, a per-run cost ledger divided by verified
outcomes, a drift check, guardrails and memory. It must be a separate agent; `homelab-knowledge` stays
untouched. It should also be a pattern Ari can show their team at work and the AI pathfinders group.

The job: **find the lines in the `arigsela/kubernetes` docs that no longer match the manifests they describe,
and say what each line should say instead.** Today that is manual: docs PRs are about 1 in 8 of the 400 PRs
since 2026-07-28, with sweeps every one to two weeks (#643, #656–658, #751), SPEC T77 is still open (nine app
`docs.md` describe the removed nginx Ingress), and four stale docs were found by hand on 2026-10-18.

## 2. Goals, non-goals, anti-goals

**Goals**
1. A weekly report of stale doc lines (`stale` and `missing` verdicts, §4), each with evidence (source file,
   line, quoted value) and a proposed replacement line, delivered to Slack. Also callable on demand for one
   doc or a list.
2. Precision first: at least 0.85 precision on the labelled eval set before it is deployed. Recall is
   reported, target at least 0.6 (my call; Ari can move both).
3. A baseline run with every lever off, then each lever switched on alone with its before/after cost and
   quality, recorded in a results table in the repo. This is a proof of concept for a demo, so the lever
   table runs on a small subset (§8) and its numbers are directional, not statistically sound.
4. A drift check on every proposed action, and the guardrails in §7, each with a test.
5. Cheap: all evals together stay under $20 (§8).
6. Deployable as a kagent 1.0 BYO agent (alpha14), image in ECR.

**Non-goals (v1)**
- Opening pull requests. v2 hands accepted findings to the existing `implementer` agent (it already has the
  propose class, PR limits and a merge-by-human flow); docs-checker itself stays read class.
- Checking live cluster state. Git is the source of truth; the agent never needs a live-cluster tool.
- Docs without a `sources:` front-matter list, `SPEC.md`, `docs/superpowers/**` (history), generated copies
  (`base-apps/*/docs/index.md`, `base-apps/*/docs/runbook.md`, made by `scripts/gen-techdocs.py`) and
  `templates/**` (scaffolds with `${{ }}` placeholders). That leaves about 57 docs, about 10k lines.
- Answering questions (that is `homelab-knowledge`'s job). Off-topic requests get a short refusal.
- The Message Batches API. A weekly batch would suit it, but it changes the A2A task lifetime; later.

**Anti-goals (it fails even if it works)**
- A noisy report. If Ari stops reading it, it has failed. Fewer, surer findings beat coverage.
- Proposing a change to a manifest so it matches a doc. The doc is what gets fixed.
- Quoting a secret, token or key, even when it appears in a manifest or doc.
- Any change to `homelab-knowledge`, or a tool binding wider than §7.

## 3. Constraints

- **Runtime:** kagent 1.0 BYO contract as found in the homelab-scout design §3: A2A v1 over gRPC on
  `KAGENT_PORT`, `/readyz` on 8081 after the A2A port binds, task state through the controller's TaskStore,
  Harness env literal only (≤ 32 vars), secrets injected at egress. Target **alpha14** (`kagent-core
  1.0.0a14`, the TaskStore proto package renamed to `kagent.runtime.v1`): the cluster upgrade is being done
  separately in the kubernetes repo, and the image must match the controller.
- **Egress:** only to origins the Harness binds: the Anthropic ModelConfig and the `agent-docs` MCP server.
  No database, no Prometheus, no web.
- **Admission:** BYO is denied today by `agent-capability-runtime`; Ari has agreed to allow it (K1 in §11).
- **Image:** ECR (`852893458518.dkr.ecr.us-east-2.amazonaws.com`). The cluster's ECR pull secret does not reach
  Substrate: atelet pulls sandbox images itself and the Harness has no pull-secret field. The Substrate
  chart's `atelet.imageCredentialProviderConfig` must be set up with an ECR credential provider and AWS
  credentials on the workers (K2). That is kubernetes-repo work and a deploy prerequisite.
- **Sandbox:** gVisor, bookworm base with a uv-managed Python (the homelab-scout design §4.2 explains why).
  The actor's disk is snapshotted between turns of one conversation; each conversation is its own actor.
- **Money:** the Anthropic workspace hit its spend limit on 2026-10-14 and took every agent down (SPEC T119).
  The agent must stop itself before it spends more than its run budget (§6, lever 5).

## 4. What it does

Input (A2A text or data part): a scope, `all`, one doc path or a list; an optional git `ref` (default `main`;
evals use old commits); a mode, `scheduled` or `interactive`; and the memory snapshot (§9) when the trigger
sends one. Output: the report as Markdown text, the findings and the updated memory as data parts, the ledger
summary as a data part, and usage under `kagent.dev/a2a/usage`.

Each claim gets one verdict:

| Verdict | Meaning | In the report? |
|---|---|---|
| `supported` | Evidence in the repo confirms it | No |
| `stale` | Evidence in the repo contradicts it | Yes, with a proposed fix |
| `missing` | The doc names a file, resource or path that no longer exists in the repo (the T77 kind) | Yes, with a proposed fix (repoint or remove) |
| `unsupported` | No evidence either way (e.g. a Helm chart default, an external fact) | No: counted in the summary line and listed in the job log; not a finding, and not counted in precision or recall |

A **finding** is a `stale` or `missing` claim: doc path, line range, the claim, verdict, evidence (source
path, line, quoted value, redacted), confidence, and a proposed replacement for those doc lines only.
Findings under 0.7 confidence go in a "needs a look" section instead of the main list.

**Where evidence comes from.** First the doc's `sources:`, which take four forms in the repo today: a path, a
directory (listed, then its files read), an `{id, resource, title}` map (its `resource` is read when it is a
repo path), and an external URL (not fetched; recorded as skipped). Then, when nothing there matches, one
repo-wide `search_code` for the value, since evidence often sits outside `sources:` (#751's fixes rest on
`renovate.json5` and SPEC). (My calls.)

A **checkable claim** is a concrete fact a manifest can confirm or deny: versions and image tags, chart
versions, names of resources and namespaces, hosts, ports, paths, schedules, resource requests and limits,
counts, and "X is configured to do Y" statements. Rationale, history and opinion are not claims.

## 5. The graph

```
START → intake ──(off-topic)──────────────────────────────→ refuse → END
          │
        scope (no model: list docs, read front matter, compare memory → skip unchanged)
          │
          ├─ Send(doc) ─→ [per-doc subgraph]  … one branch per doc, bounded concurrency
          │                 load → extract_claims → locate_evidence → judge → propose_fix → gate
          │                 returns list[Finding] only
          ↓
        collect (reduce) → filter (confidence, dismissals) → budget check → report → END
```

- **intake** (Haiku, structured output): classify the request (`audit`, `off_topic`) and parse the scope.
  Requests to change anything, run commands or answer general questions are `off_topic`.
- **scope** (no model): resolve the doc list, read each doc's front matter (`sources`, `last_reviewed`), get
  the latest commit for the doc and each source (`list_commits`), and skip any doc whose content hash and
  source hashes match memory (lever 3).
- **per-doc subgraph**, reached with `Send`, one branch per doc, at most four at a time (my call):
  - **load** (no model): fetch the doc and its sources at `ref` (`get_file_contents`).
  - **extract_claims** (Haiku, no tools): the doc's lines in, a list of `Claim` out (line range, text, kind,
    the keys and values to look for, which source probably holds them).
  - **locate_evidence** (no model): for each claim, find candidate lines in the doc's sources by key and value
    and cut a window of ±3 lines around each hit (lever 7). If nothing matches in the sources, one
    `search_code` call for the value across the repo, then the same windowing.
  - **judge**: when the value is found verbatim, decide in code (`supported`, no model call). Otherwise Haiku
    judges; when Haiku's confidence is under 0.8, Sonnet judges (lever 6). Output: a `Verdict` per claim.
  - **propose_fix** (Haiku): for `stale` claims only, the replacement text for those doc lines.
  - **gate**: the drift check (§7) on each proposed fix. Allow → keep; ask → interrupt in interactive mode,
    "needs a look" in scheduled mode; refuse → drop and record.
- **collect / filter**: merge the branches, drop findings Ari dismissed (§9), apply the confidence split.
- **budget check**: before each model call and here: if the ledger's spend reaches the run budget, stop
  fanning out, finish the branches in flight, and report what was checked and what was skipped.
  Interactive mode asks (interrupt) before going past it.
- **report** (no model): render Markdown and the data parts.

Plain `StateGraph` nodes with direct `ChatAnthropic` calls, not `create_agent`: each node's model, tools and
prompt are fixed, so a tool loop is not needed, and every lever stays visible in our own code. Middleware
from `langchain.agents.middleware` is used only where it fits a node (§6). This is my call; the trade-off is
less prebuilt code in exchange for levers we can see and measure.

## 6. The levers

Every lever has a switch in config (default off for the baseline) and a test. Each is measured alone against
the baseline on the eval set: cost per verified finding, precision, recall, model calls per doc.

| # | Lever | In docs-checker | Off means |
|---|---|---|---|
| 1 | Cache the stable prefix | Frozen system prompts per node (no dates, ids or per-run data); `cache_control` on the last system block. One prefix serves every doc in a run. Tools sorted by name. | No `cache_control` |
| 2 | Typed handoffs | Pydantic `Claim`, `Evidence`, `Verdict`, `Finding`; the subgraph returns only `list[Finding]`; the report node never sees a transcript | Each branch returns its full message history to collect, and report renders from it with a model call |
| 3 | Short-circuit repeats | Cross-run: skip docs whose doc and source hashes match memory. In-run: LangGraph `CachePolicy` on `judge` keyed by (normalized claim, evidence window hash), so the same claim in `docs.md` and `runbook.md` is judged once | Every doc and every claim checked |
| 4 | Load tools on demand | Each node gets only its tools: `extract_claims` and `judge` none, `load` `get_file_contents`, `locate_evidence` `search_code` as a fallback | Every model call carries all four tool schemas |
| 5 | One retry layer, explicit limits | Only `llm.py` retries (`retry_on` = the error's `is_retryable`, 2 retries, backoff); SDK `max_retries=0`; no `RetryPolicy` on model nodes; HTTP timeout 60 s; `recursion_limit` 80; at most 12 model calls per doc (my calls) | Library defaults: three layers stacked (27 attempts for one overload in a mock test), no timeout, recursion limit 10007, no per-doc cap |
| 6 | Right-size the model | No model where code can decide; Haiku 5.5 for intake, extraction, first-pass judging and fixes; Sonnet 5.5 only for contested verdicts | Sonnet 5.5 everywhere |
| 7 | Shrink tool results | Evidence windows of ±3 lines, not whole manifests; doc sent as numbered claim lines; any tool result over 8 KB truncated with a marker | Whole doc and whole source files sent to every call |

**The run budget is not a lever and is always on.** Its amount comes from config: deployed defaults are
$1.00 for `all` and $0.10 for one doc, revisited after the first ledger numbers (my calls). The eval harness
sets its own amount per doc instance, high enough that a baseline run is never cut short, and the eval
budget (§8) caps the whole eval run.

The ledger (`ledger.py`, kept from homelab-scout) records every model call with run id, request id, node,
model, attempt and rate-card version, in four disjoint buckets: uncached input, cache write, cache read and
output. Two traps it already handles: `usage_metadata.input_tokens` includes cache reads and writes, and
`cache_creation` reads 0 when the TTL breakdown is present. The request id comes from an httpx response hook,
since langchain drops it. A call without usage counts as unknown, never zero. **Outcome** = a finding the eval
set marks correct; cost per verified finding = run cost / correct findings.

## 7. The drift check and other guardrails

**Drift check** (`gate.py` seam, after authorization, before any action leaves the agent). Two layers:

1. **Rules, deterministic, always on.** A proposed fix must target the doc under check, stay inside the
   claim's line range, and change nothing else. A tool read must be inside `arigsela/kubernetes`. Anything
   else is refused. This is the guard that matters for safety.
2. **Angle, the DevCon method.** Embed the intent (the claim plus its evidence) and the action (the old line
   and the proposed line), take the angle between them, and allow under θ1, ask between θ1 and θ2, refuse
   over θ2. Thresholds are set from the eval set, and the result is logged with every decision. This layer
   is for practice and measurement: it may only add an ask or a refusal, never allow what layer 1 refused.

**Embedder: left to a spike in the plan.** Anthropic has no embeddings API. Option A: Ollama
`nomic-embed-text` (already in the cluster as ModelConfig `embedding-model-config`), if a BYO Harness can bind
a second ModelConfig and so open egress to Ollama. Option B: a small in-process ONNX model, if NumPy and
onnxruntime run under gVisor on these CPUs (E5-2670, no AVX2). The spike tries A first. If neither works,
layer 2 runs only in the offline eval harness and the deployed agent ships with layer 1.

**Other guardrails**
- Read only by construction: the code allowlist (`get_file_contents`, `search_code`, `list_commits`,
  `get_commit`, all `read` in the taxonomy) intersected with the template binding.
- Untrusted text: doc and manifest content go in delimited blocks marked as data; only typed `Claim` and
  `Evidence` objects cross node boundaries, so free text from a file cannot become an instruction to a later
  node. The eval set carries an injection canary doc.
- Secrets: every quoted value passes a redactor (key and token patterns, plus the B30 rule: name the line,
  never quote a value that looks like a credential) before it enters a finding.
- The run budget is always on (§6). Lever 5's limits are switched off only inside the eval harness, to
  measure the baseline; the deployed agent always runs with them on.
- Human in the loop: drift "ask" and budget overrun interrupt in interactive mode (`interrupt()`, resumed by
  the next A2A turn); the checkpointer is `SqliteSaver` on the actor's disk so the pause survives the
  snapshot between turns.

## 8. Eval set

Built before any lever ships, stored in the repo with the agent:

- **History positives.** For each sweep PR (#643, #656, #657, #658, #751), each in-scope doc at the PR's
  parent commit (about 61 doc instances, 44 of them from #657), and the lines the PR changed **as factual
  corrections** (sweeps also reword prose, so these are labelled, not taken from the diff).
- **Negatives are labelled, never assumed.** A line the sweep left alone is not automatically true: after
  #643, `base-apps/logging/docs.md` still described a `grafana-ingress.yaml` deleted on 2026-08-03. Only
  claim lines a labeller confirmed against the repo at that commit count as negatives; a missed stale line
  found this way becomes a positive.
- **Live positive.** `base-apps/kagent/docs.md`'s harness table (found stale 2026-10-18). The T77 docs are
  not used: #657 already fixed them on 2026-09-30 (SPEC still marks T77 open, which is itself stale but out
  of scope).
- **Planted positives.** Copies of clean docs with one fact changed (a version, a port, a namespace), so the
  answer is known exactly.
- **Canary.** A doc carrying an injected instruction; the pass condition is that nothing in the run follows it
  and no finding quotes it as an instruction.

The offline harness runs the graph against a fake `agent-docs` that serves `git show <ref>:<path>` from a
local clone, so evals are deterministic, need no GitHub calls, and can run at any commit. Model calls are
real (that is what is being measured) and logged in the ledger.

**Keeping evals cheap (Ari: "keep it very cheap, this is a PoC for a demo").** Total eval spend is capped at
**$20**, enforced by the harness (it refuses to start a run its estimate would push past the cap, and stops
at the cap), with the eval workspace's own Anthropic spend limit set to $25 as the backstop. Estimates
before the first ledger numbers:

| Run | Scope | Estimate |
|---|---|---|
| Lever table: baseline plus one run per lever | 3 small docs, one pass each, 8 passes | $5–8 |
| Quality gate (precision, recall) | Full labelled set, all levers on (Haiku first, small windows) | $1–2 per pass |
| Prompt tuning | Single docs, all levers on | cents per run |

- **Record and replay.** Every real model response is saved with its request hash; a re-run whose prompts
  did not change replays from disk at no cost. Only a changed prompt or model goes to the API. Unit tests
  never call the API.
- **Key:** a separate Anthropic workspace for evals, its key read from Ari's environment, never written to
  the repo, so a heavy eval cannot hit the cluster agents' spend limit (the 2026-10-14 outage).
- **Labels:** two agents label the set independently; Ari reviews every positive and every disagreement in a
  review page made for it (about 45–60 minutes). Negatives the agents agree on are spot-checked.

## 9. Memory

- **Short-term:** the LangGraph checkpointer (`SqliteSaver` on the actor's disk) for one conversation,
  which is what makes interrupt and resume work.
- **Long-term, my call for v1:** the caller holds it. The weekly trigger keeps a JSON snapshot in a ConfigMap
  and sends it with the request; the agent loads it into a LangGraph `BaseStore` (subclass of
  `InMemoryStore`), reads and writes through the normal `runtime.store` API, and returns the changed entries
  as a data part, which the trigger saves. What it holds: per doc, the doc hash and source hashes at the last
  clean check; per claim, the last verdict keyed by (normalized claim, evidence hash). The agent stays read
  class and needs no new server. Moving later to an MCP-backed store means one new `BaseStore` subclass
  (only `batch`/`abatch` are abstract).
- **Dismissals live in git:** `docs/docs-checker-dismissed.yaml` in the kubernetes repo lists findings Ari
  rejected (doc, claim text, reason, date). The agent reads it with `get_file_contents`, and a dismissed
  finding comes back only if its evidence changes. Edits to it are ordinary PRs, so the human feedback is
  reviewed and versioned.

## 10. Trigger and delivery

- **Weekly CronJob** (`docs-checker-trigger`, Mondays 14:00 UTC, after Renovate's Monday batch, my call),
  stdlib Python like `eval-gate`: read the memory ConfigMap, call A2A `kagent/docs-checker` with service
  account identity through the mesh, save the returned memory, post the report to n8n's `agent-findings`
  webhook, the same path the dispatcher uses to reach Slack.
- **On demand:** `~/git/kubernetes/scripts/ask-hk --agent kagent/docs-checker "check base-apps/vault/docs.md"`.
- The `agent-findings` workflow posts to `#oncall-alerts` with an "Investigation: <alertname>" header and
  cuts the body at 3000 characters. v1 sends `alertname` "Weekly docs check" and a compact list (doc:line,
  verdict, a one-line fix) that fits; evidence and full fixes stay in the job log (Loki) and the A2A task.
  A separate channel would need a new n8n workflow, a later change if the alerts channel gets noisy (my
  call).

## 11. Changes outside this repo (kubernetes repo PRs, in order; described in the plan, not done by it)

| | Change | Note |
|---|---|---|
| K0 | kagent alpha14 upgrade | Being handed to a separate agent; deploy waits for it |
| K1 | Admit `spec.byo` when the image is in a new taxonomy list `byo-images`, the template is class `read`, and it binds only servers in a new list `read-only-servers` | Policy, generator, validator, tests and fixtures in one change (V84) |
| K2 | ECR pulls for Substrate. **Owned by this plan** (Ari). A pull-only IAM user scoped to the `docs-checker` repository (`ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`), its keys in Vault and delivered to the workers outside git, wired through the Substrate chart's `atelet.imageCredentialProviderConfig` with an ECR credential-provider binary. A spike comes first: how atelet's provider reads credentials (the config's `env` takes literals only, so a credentials file path rather than keys) and whether atelet can see a file on the host | The cluster already pulls ECR with static IAM keys from Vault (`ecr-credentials-sync`), so this matches today's trust model |
| K3 | ECR repository `docs-checker` in `terraform/roots/asela-cluster/ecr.tf` | |
| K4 | Harness (byo, image by digest), AgentTemplate (class `read`, binds `agent-docs` with the four tools), Agent | Reuse ModelConfig `anthropic-claude-sonnet-5-5` |
| K5 | `tests/eval-corpus/docs-checker.yaml` for the cluster eval gate | Own entries plus the shared adversarial corpus |
| K6 | Trigger CronJob, memory ConfigMap, service account, `docs/docs-checker-dismissed.yaml` | |

## 12. Decided by Ari

- A new, separate agent; `homelab-knowledge` stays untouched.
- BYO on kagent is acceptable (it is the only way to run a LangGraph graph there).
- The job: the stale-docs checker.
- Image in ECR with pull credentials.
- The alpha14 upgrade is done separately in the kubernetes repo.
- Evals stay very cheap: it is a proof of concept for a demo (cap set in §8 from this).
- Evals use a separate Anthropic workspace and key.
- Ari reviews every positive label and every disagreement in the eval set.
- ECR pulls for Substrate (K2) are part of this plan.

## 13. Left to the builder

Package layout inside `docs-checker/`, prompt wording, the exact claim kinds, concurrency tuning, the
redaction patterns beyond B30, test structure, how the per-lever results table is laid out, and how the
homelab-scout skeleton is renamed (it was never committed; its spec and plan are superseded by this one).
