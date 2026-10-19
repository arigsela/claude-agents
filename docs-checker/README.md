# docs-checker

A read-only LangGraph agent that finds lines in the `arigsela/kubernetes` docs that no longer
match the manifests they describe, and proposes the corrected line. It is built as a
**kagent 1.0 BYO runtime**, with a per-run cost ledger.

Status: the runtime and the audit graph are wired and tested offline (scripted models, a
local git fake of the agent-docs server), and so is the eval harness (record and replay,
the $20 spend guard, scoring; `evals/README.md`), and the image builds and completes a real
A2A task in its smoke test (Container). The eval set is labelled (pending Ari's review), and
the evals are preregistered and dry-run (Results); the paid evals come next.
Design:
`docs/superpowers/specs/2026-10-18-docs-checker-design.md`; plan:
`docs/superpowers/plans/2026-10-18-docs-checker-plan.md`.

## What it proves

kagent 1.0's BYO contract (v1.0.0-alpha14) can be met by a LangGraph app with published
libraries, even though `kagent-langgraph` does not meet it (it serves FastAPI JSON-RPC only):

| Contract | Where | Test |
|---|---|---|
| A2A v1 over gRPC (`lf.a2a.v1.A2AService`) on `runtime.port` (80) | `server.py` (`start`) | `tests/test_server.py` |
| `GET /readyz` → 200 on 8081, bound after A2A | `server.py` (`_readyz`) | `tests/test_server.py` |
| Tasks created, versioned and settled through the controller TaskStore (`kagent.runtime.v1`), with the projected actor identity | `server.py` (`build_request_handler`), kagent-core | `tests/test_taskstore_contract.py` |
| `KAGENT_CONFIG_JSON` parsed as the alpha14 `ADKConfig` | `config.py` (`load_settings`) | `tests/test_config.py` |
| HITL `input-required` with a kagent `tool_approval_request`, resumed on the same task | `executor.py`, `tools.py` | `tests/test_hitl.py` |

Not proven here: a real controller, Atenet routing, the golden snapshot and gVisor
suspend/resume.

## Runtime contract (alpha14)

The image targets kagent v1.0.0-alpha14 (commit `673d181e`); the cluster still runs alpha11
until its upgrade lands, and the two are not compatible. What changed from alpha11:

- **Env names:** alpha11 set `KAGENT_API_URL`; alpha14 sets no `KAGENT_API_URL`, `KAGENT_NAME`,
  `KAGENT_NAMESPACE` or `KAGENT_PORT`, so none is read. Of kagent's own variables only
  `KAGENT_CONFIG_JSON` and the `KAGENT_CREDENTIAL_*` header placeholders are read;
  `KAGENT_AGENT_CARD_JSON` is not (`server.py` builds its own card).
- **Config shape:** `KAGENT_CONFIG_JSON` is an `ADKConfig` in ProtoJSON with proto field names,
  `{"runtime": {control_plane_url, gateway_url, name, namespace, log_level, port}, "agent": {...}}`
  (alpha11 sent the bare agent config). The model's provider is a oneof, so Anthropic's
  `prompt_caching`/`cache_ttl` sit under `model.anthropic`, and zero values are omitted. Any other
  top-level field fails at startup.
- **readyz:** unchanged; Substrate's wake-up probe is `GET /readyz` on 8081 (30 s timeout).
- **TaskStore service:** `kagent.api.v1alpha1.TaskStoreService` is now
  `kagent.runtime.v1.TaskStoreService` (Python `kagent.runtime.v1.task_store_pb2`), with the
  same five RPCs, at `runtime.control_plane_url`.
- **Identity files:** unchanged; Substrate projects `name` (`session-<uuid>`), `atespace` and
  `uid` under `/run/kagent/identity`, re-read on every TaskStore call and sent as
  `x-kagent-insecure-runtime-identity: <atespace>/<name>/<uid>`.
- **Workload command:** unchanged; a BYO Harness must set
  `workload.command: ["/app/.venv/bin/docs-checker"]` and a `workload.image` pinned by digest.
- **Snapshots:** a commit snapshot now keeps only the durable `/data` directory (alpha11 kept
  process memory too), so state that must survive a suspend has to live under `/data`.

## Plumbing

The executor (`executor.py`) runs the audit graph (`graph.py`): one A2A task is one graph run
and one cost ledger (`ledger.py`). A request is the message's data part
`{"scope", "ref", "mode", "memory"}` or its text (`check all`, `check <path>[, <path>...]`,
optionally `at <ref>`); the run budget follows the scope, and a turn longer than
`run_timeout_s` fails as `timeout`. A completed task carries the report as text and the
findings, the full memory snapshot, the Slack digest, the `Report`, one
`function_call`/`function_response` pair per tool call and the ledger as data parts. The
executor keeps a paused task's ledger and replay memo (`paused.py`) in the checkpoint db under
`/data`, so a resume, even after a restart, reports its whole cost and does not pay for a model
reply or run a tool twice; a resume that lost them says its cost is a lower bound.
It turns parallel pauses into one HITL request, cancels a running task, and redacts what it
logs and publishes (`redact.py`). Every tool call goes through the tool belt (`tools.py`):
the read-only allowlist, per-server bindings, per-node scoping, repository scoping, then the
drift gate (`gate.py`); a paused call runs only when the reply approves that call's id with a
boolean `True`. Results come back whole and typed (`ok`, `absent`, `denied`, `transient`,
`error`, read from the server's captured shapes in `tests/fixtures/mcp/`), `model_text` caps
what a model sees, and searches are capped and paced per run. The repository is read at one
commit per run (`repo.py`): `resolve_commit` turns the ref into a sha at intake and every read
names that sha; `evals/localrepo.py` serves the same tools, in the server's shapes, from a local
clone for evals. Model calls go through the one retry owner (`llm.py`).

The A2A input and output tests (`tests/test_executor.py`, `tests/test_restart.py`) drive the
audit graph; the pure-plumbing tests run against `tests/fake_graph.py`, a minimal graph with a
memoized model step, tool calls through the belt, and two parallel `Send` branches.

## Configuration

kagent supplies `KAGENT_CONFIG_JSON` (the runtime settings, and the AgentTemplate compiled:
model, MCP bindings and their tool filters) and the egress trust bundle variables. Secrets
never enter the container: `ANTHROPIC_API_KEY` and Secret-backed MCP headers hold the
placeholder `kagent-credential-injected`, and the Substrate egress gateway injects the real
values. A Harness may add literal values only, and an actor carries at most 32 variables in
all, so the knobs below are optional:

| Variable | Default | Purpose |
|---|---|---|
| `DOCS_CHECKER_<NODE>_MODEL` | see `config.py` | Model per node |
| `DOCS_CHECKER_<NODE>_EFFORT` | see `config.py` | `output_config.effort` per node |
| `DOCS_CHECKER_RECURSION_LIMIT` | `12` | Graph circuit breaker (LangGraph's own default is 10007) |
| `DOCS_CHECKER_RATE_CARD` | `anthropic-2026-10-18` | Rate card the ledger prices with |
| `DOCS_CHECKER_REPO` | `arigsela/kubernetes` | The one repository the tools may read |
| `DOCS_CHECKER_REPLAY_DIR` | unset | Test seam: every model response from the cassettes in this directory (replay only: nothing recorded or sent, a request with no recording fails its call; logged at startup). The smoke test uses it; never set it in a Harness |

## Local development

    uv lock
    uv sync --extra dev
    .venv/bin/pytest -q
    .venv/bin/black --check src tests && .venv/bin/ruff check src tests

The `dev` extra includes the `kagent` extra, so the TaskStore contract tests always run. The
tests use scripted fake models and fake tools; they make no Anthropic calls and need no key
(`tests/conftest.py` points the SDK at an unroutable address and a placeholder key).

The `kagent` extra pins `kagent-core==1.0.0a14` (the controller version this image targets)
and installs `kagent-proto` from the kagent repo at that tag's commit, because it is not on
PyPI. It also declares `fastapi`, which kagent-core 1.0.0a14 imports but does not declare.
`grpcio-health-checking` stays below 1.75 because kagent-proto needs protobuf < 7.

## Container

    docker build --platform linux/amd64 -t docs-checker:dev docs-checker
    bash docs-checker/scripts/smoke.sh      # DOCKER_CONTEXT=<context> to pick a docker context

`Dockerfile` follows kagent's own BYO samples and runtime image (v1.0.0-alpha14): a bookworm
base and a uv-managed Python 3.13, because gVisor checkpoint/restore crashed processes on
trixie's glibc and on the system CPython. Two stages: the build stage (uv, and git for
`kagent-proto`) runs `uv sync --locked --no-dev --extra kagent --no-editable`; the final
stage holds only the interpreter (`/python`) and the venv (`/app/.venv`), runs as uid 65532
(kagent's runtime uid) with `/data` owned by it, and has
`ENTRYPOINT ["/app/.venv/bin/docs-checker"]`. Both bases are pinned by digest. The
`.dockerignore` is an allowlist (`pyproject.toml`, `uv.lock`, `README.md`, `src/`), so `.env`
files, the venv, tests, eval cassettes and the spend ledger never reach the build.
`tests/test_dockerfile.py` pins these invariants. The Harness must set
`workload.command: ["/app/.venv/bin/docs-checker"]` and the image by digest.

`scripts/smoke.sh` builds the image (or tests `SMOKE_IMAGE`, e.g. the pushed digest) and runs
one real task through it with no key and no cluster: a sidecar built from the image's build
stage serves the fake controller TaskStore (`tests/fake_controller.py`) and a fake agent-docs
MCP server over a fixture repository (`tests/fixtures/smoke-repo`), waits for `/readyz`, sends
`check base-apps/kagent/docs.md` over A2A gRPC and checks that the controller holds the task
COMPLETED and settled, with the report and the ledger. The model calls replay
`tests/fixtures/cassettes-smoke` through `DOCS_CHECKER_REPLAY_DIR`. It also checks the
image's user, entrypoint and interpreter, prints each check, and ends with `smoke ok`. It runs
in the docker context `DOCKER_CONTEXT` names (the CLI's own variable), never switches
contexts, pushes or prunes, and removes its containers and network on exit.
`tests/test_smoke_stack.py` runs the same task in process in every test run; when a change
alters a model request it fails there, and `.venv/bin/python -m tests.smoke_stack record`
rewrites the cassettes from hand-written answers (no API, no key).

## Memory

The agent has no database. The weekly trigger holds a JSON memory snapshot, sends it with each run and gets back the full updated snapshot. Trust model: the trigger is the only caller that sends memory, and it is the one that receives the report. Memory is honoured only in `scheduled` mode; any other mode starts with an empty store. A snapshot that is oversize, garbled or the wrong version is ignored with a warning. The graph marks findings carried from memory as `carried: true` in the report.

## Results

Dry run only. No priced eval has run yet (the eval key was not set), so there are no
measured numbers and no `evals/results.md`.

`evals/plan.md` preregisters the evals: the bars, the arms in priority order, the canary
and the stop rules. It also holds the dry run: what a priced run of each arm would cost,
from the harness's per-doc defaults ($0.05 a doc with every lever on, $0.60 for any other
mix). The dry run made no call.

| Tier | Arms | Docs per arm | Estimate |
|---|---|---:|---:|
| 1 pilot | every lever on, the `lever` set | 3 | $0.15 |
| 2 baseline | every lever off, the `lever` set | 3 | $1.80 |
| 3 quality | every lever on, the dev set | 7 | $0.35 |
| 4 holdout | every lever on, run once | 4 | $0.20 |
| 5 each lever alone | the seven levers on the `lever` set (see notes) | 3 | $12.60 |
| 6 leave-one-out | `right_size` and `shrink_results` | 3 | $3.60 |
| **total** | | | **$18.70 of the $20 cap** |

- Tier 5 runs `short_circuit` twice, cold then warm.
- Its `retry_limits` row replays the baseline under synthetic 529s, so it costs nothing.
- No arm's estimate is over the $4 single-arm stop.
- The bar: holdout precision ≥ 0.85 with ≥ 3 TP, with recall reported. It is provisional
  until Ari reviews the labels.
- Ari runs them with the commands in `evals/README.md`, "Running the paid evals (Ari)".
