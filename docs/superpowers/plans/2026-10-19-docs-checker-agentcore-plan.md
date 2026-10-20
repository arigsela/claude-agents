# docs-checker on Bedrock AgentCore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run docs-checker as an interactive A2A agent on AgentCore Runtime in sb-asela (`414696729697`, us-west-2), checking OpenTofu repo docs through Bedrock models and a Gateway-fronted read-only GitHub MCP server, with fix-approval pauses kept.

**Architecture:**
- The graph, levers, gate, redaction and memory don't change. A new runtime layer (`agentcore.py`) serves the existing `DocsCheckerExecutor` over A2A JSON-RPC on port 9000, with an on-disk A2A task store and the existing SQLite checkpointer, both on AgentCore session storage.
- Models go through the Anthropic SDK's Bedrock client (`AsyncAnthropicBedrock`), so the request body, prompt caching and the ledger's usage parsing stay Anthropic-shaped.
- A per-repo profile replaces `sources:` front matter and the kubernetes wording in the prompts.
- Findings go to CloudWatch.
- The kagent path keeps working, so the homelab deploy is untouched.

**Tech Stack:** Python 3.13, langgraph 1.2.16, langgraph-checkpoint-sqlite 3.1.2, langchain-anthropic 1.7.6, anthropic 1.15.0 (`[bedrock]` extra), a2a-sdk 1.2.2 (`[http-server,sqlite]` extras), langchain-mcp-adapters 0.3.2, starlette 1.9.0, uvicorn 0.54.0, boto3, aws-cli 2.34.43, uv (locked).

**Spec:** `docs-checker/docs/bedrock-agentcore-handover.md` (on this branch), plus the decision record in Ari's notes (`personal/deploy-agents-bedrock/initial-exploration.md`). Every decision this plan relies on is copied into Global Constraints, so executors don't need the notes. Executors also read `docs/superpowers/specs/2026-10-18-docs-checker-design.md` for what must not change.

## Global Constraints

- **Where:** worktree `/Users/asela/git/claude-agents-docs-checker`, branch `feature/docs-checker`. Code in `docs-checker/`. Commit locally; push only when Ari asks.
- **Account:** sb-asela only, `--profile sb-asela --region us-west-2` on every AWS call. Pass the profile explicitly; zsh does not word-split, so use `${=P}` when holding flags in a variable. No prod, no other account.
- **AWS mutations:** every create/update/put lives in a script under `docs-checker/deploy/agentcore/`. The script has a `--check` mode that makes read-only calls only. Run the mutating mode only after Ari has read the commands.
- **The kagent path must not regress.** With no `DOCS_CHECKER_RUNTIME` set, behaviour is unchanged and the full suite passes (996 at the start of this plan). With no profile set, every model request body is byte-identical to today's, so `tests/fixtures/cassettes-smoke/` replays unchanged.
- **Models:** logical names stay `claude-haiku-5-5` and `claude-sonnet-5-5` (`config.ALLOWED_MODELS`). On Bedrock each maps to an application inference profile ARN created from the `global.anthropic.claude-haiku-5-5` and `global.anthropic.claude-sonnet-5-5` system profiles. Tag the profiles `Consumer=docs-checker`, `Model=<foundation model id>`, `Environment=sb-asela`, `Service=Bedrock`.
- **Rate card `bedrock-global-2026-10-19`** (USD per million tokens, AWS Pricing API, us-west-2, `global_standard`):
  - Haiku 5.5: input 0.10, cache write 5m 0.125, cache write 1h 0.20, cache read 0.01, output 0.50. Above the long-context threshold: 0.50, 0.625, 1.00, 0.05, 2.50.
  - Sonnet 5.5: input 2.00, cache write 5m 2.50, cache write 1h 4.00, cache read 0.10, output 10.00.
- **Budgets and limits** (homelab defaults, unchanged): $1.00 for `all`, $0.10 per doc, 12 model calls per doc, concurrency 4, `recursion_limit` 80. `DOCS_CHECKER_RUN_TIMEOUT_S` is **780**: AgentCore's request timeout is 15 minutes and not adjustable.
- **Runtime:**
  - Protocol `A2A`: JSON-RPC 2.0 over HTTP on `0.0.0.0:9000` at `/`, Agent Card at `/.well-known/agent-card.json`.
  - Image: ARM64, pinned by digest.
  - Network: `networkMode VPC` on private subnets `subnet-01710edde6972a0b0` (usw2-az2), `subnet-0271ab029fabc7f10` (usw2-az1) and `subnet-0d4e90025ee4dcb38` (usw2-az3), in `vpc-0e8e76490d5ea04ae`. Egress goes through the existing NAT gateways. New security group `docs-checker-runtime`: no ingress, egress TCP 443 to `0.0.0.0/0`.
  - Session storage mounted at `/mnt/workspace`.
  - Lifecycle: `idleRuntimeSessionTimeout` 3600, `maxLifetime` 28800.
  - One runtime per repo: `docs_checker_bedrock` and `docs_checker_opensearch`.
- **Data dir on AgentCore:** `/mnt/workspace/docs-checker`. SQLite there opens with `nolock=1`, `PRAGMA journal_mode=MEMORY`, `PRAGMA synchronous=OFF`, because session storage does not support POSIX locks.
- **Every runtime update sends the full configuration.** `update-agent-runtime` replaces the configuration, and omitting `--filesystem-configurations` silently drops session storage. The deploy script builds one full request for both create and update.
- **GitHub:** a fine-grained PAT with access to `chghealthcare/chg-infra-opentofu-bedrock` and `chghealthcare/chg-infra-opentofu-opensearch` only, `Contents: read` and `Metadata: read`. It's held only in an AgentCore Identity API-key credential provider, never in env, image or repo. Tool allowlist unchanged: `get_file_contents`, `search_code`, `list_commits`, `get_commit`.
- **Gateway inbound auth:** `AWS_IAM`. The runtime's execution role signs MCP requests with SigV4, service `bedrock-agentcore`.
- **Findings:** one JSON event per finding to log group `/docs-checker/findings`, stream `<runtime name>/<run id>`. Retention 30 days.
- **Interactive only.** No scheduler and no memory store: memory is honoured in `scheduled` mode only.
- **Quality bar per task:** inside `docs-checker/`: `.venv/bin/ruff check src tests`, `.venv/bin/black --check src tests`, `.venv/bin/pytest -q`. All clean, no skipped contract tests.

## Review Focus

1. **A resume after the microVM was recycled.** The approval reply arrives after the session's VM stopped (idle timeout) and a new VM mounts the same session storage. The task must still be `input-required` and resume from its checkpoint, not start over or report "Task not found" (Task 5, restart test).
2. **A Gateway-prefixed tool name.** Gateway lists tools as `<target>___<tool>`. The allowlist must match the canonical name and still refuse any tool outside the four, prefixed or not (Task 6).
3. **A `//` or `/* */` comment in a `.tf` file.** Comments are not evidence (ruling R1d), so a value only in an HCL comment must not make a claim `supported` (Task 8).
4. **A doc in a profile whose source file is gone.** A profile source missing at the run's commit is a `missing` finding only on a confirmed 404, never on a 403 or timeout (Task 7, using the existing reader rule).
5. **Findings when CloudWatch is unreachable.** A `PutLogEvents` failure must not fail the run or lose the A2A report. It logs one warning to stdout and the task still completes (Task 9).

---

## Phase 1: AWS foundation and probes

### Task 1: Bedrock profiles, execution role, ECR, log groups

**Files:**
- Create: `docs-checker/deploy/agentcore/env.sh` (shared constants: account, region, subnets, VPC, names)
- Create: `docs-checker/deploy/agentcore/01-foundation.sh`
- Create: `docs-checker/deploy/agentcore/policies/execution-role-trust.json`, `docs-checker/deploy/agentcore/policies/execution-role.json`

**Interfaces:**
- Produces: `env.sh` exports `ACCOUNT=414696729697`, `REGION=us-west-2`, `P="--profile sb-asela --region us-west-2"`, `VPC_ID`, `SUBNETS` (the three above), `ROLE_NAME=docs-checker-agentcore`, `ECR_REPO=docs-checker`, `FINDINGS_LOG_GROUP=/docs-checker/findings`. After `--apply`, the script prints the two profile ARNs as `HAIKU_PROFILE_ARN=...` and `SONNET_PROFILE_ARN=...`, which Task 11 reads from `deploy/agentcore/out/foundation.env` (gitignored).

- [ ] **Step 1: Write `env.sh` and `01-foundation.sh`.** Usage: `--check` (default) or `--apply`. `--apply` creates whatever is missing:
  - two application inference profiles (`aws bedrock create-inference-profile --model-source copyFrom=<global system profile ARN>`, tags from Global Constraints);
  - ECR repo `docs-checker` with `IMMUTABLE` tags and scan on push;
  - log group `/docs-checker/findings` with 30-day retention;
  - role `docs-checker-agentcore`.

  The role's trust policy allows `bedrock-agentcore.amazonaws.com` with `aws:SourceAccount` = `414696729697`. Its permissions:
  - `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on the two profile ARNs and on `arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-5-5` and `.../anthropic.claude-sonnet-5-5`, plus the two `global.` system profile ARNs;
  - `ecr:GetAuthorizationToken` on `*`, and image pull on the repo;
  - `logs:CreateLogStream` and `logs:PutLogEvents` on `/aws/bedrock-agentcore/*` and `/docs-checker/findings:*`;
  - `bedrock-agentcore:GetWorkloadAccessToken*` and `bedrock-agentcore:GetResourceApiKey` on the default workload identity directory and the credential provider;
  - `bedrock-agentcore:InvokeGateway` on the gateway ARN, added by Task 6.

  It grants nothing on `foundation-model/*`. Each create is preceded by a describe, so `--apply` can be re-run.
- [ ] **Step 2: Run `--check`.** Run: `bash deploy/agentcore/01-foundation.sh --check`. Expected: one `MISSING` line per resource, exit 0, no mutating call (verify with `grep -E 'create-|put-|attach-' ` on the `--check` code path).
- [ ] **Step 3: Ari runs `--apply`, then `--check` again.** Expected: every line `OK`, and `out/foundation.env` holds both ARNs.
- [ ] **Step 4: Commit** (`deploy/agentcore/out/` in `.gitignore`).

```bash
git add docs-checker/deploy/agentcore docs-checker/.gitignore
git commit -m "feat(docs-checker): AgentCore foundation script for sb-asela"
```

### Task 2: Bedrock and Gateway probes, recorded

**Files:**
- Create: `docs-checker/scripts/bedrock_probe.py`
- Create: `docs-checker/docs/agentcore-probes.md`

**Interfaces:**
- Consumes: `out/foundation.env` (Task 1).
- Produces: answers that Tasks 3 and 6 branch on, recorded in `docs/agentcore-probes.md` as `PROBE <name>: <result>` lines:
  - `effort` (accepted / rejected);
  - `cache_min_tokens_haiku`;
  - `usage_shape` (the raw usage keys);
  - `request_id_header`;
  - `haiku_long_ctx_threshold` (unknown is acceptable).

- [ ] **Step 1: Write `bedrock_probe.py`.** It uses `anthropic.AsyncAnthropicBedrock(aws_region="us-west-2", aws_profile="sb-asela")` with `model=<HAIKU_PROFILE_ARN>`, and makes three calls of `max_tokens` 16 each:
  1. a plain call;
  2. the same call with `output_config={"effort": "low"}` passed through `extra_body`;
  3. a system prompt of the size `prompts.system_message("extract")` produces, with `cache_control` on it, sent twice, recording `cache_creation_input_tokens` and `cache_read_input_tokens`.

  It prints the response headers' names and the raw `usage` dict. Total cost is under $0.01.
- [ ] **Step 2: Run it.** Run: `.venv/bin/python scripts/bedrock_probe.py`. Expected: exit 0 and the five `PROBE` lines.
- [ ] **Step 3: Record the results** in `docs/agentcore-probes.md`. If `effort` is rejected, the Bedrock models in Task 3 omit `effort` (they still keep `NodeModel.effort` for the Anthropic path). If the second cache call reads 0, set `DOCS_CHECKER_LEVERS` without `cache_prefix` in the Task 11 env.
- [ ] **Step 4: Commit.**

```bash
git add docs-checker/scripts/bedrock_probe.py docs-checker/docs/agentcore-probes.md
git commit -m "docs(docs-checker): record Bedrock probe results for the AgentCore port"
```

## Phase 2: Code

### Task 3: Bedrock models and rate card

**Files:**
- Modify: `docs-checker/src/docs_checker/models.py` (add `BedrockModels`)
- Modify: `docs-checker/src/docs_checker/config.py` (`Settings` fields, `load_settings`)
- Modify: `docs-checker/src/docs_checker/ledger.py:82-96` (second rate card)
- Modify: `docs-checker/src/docs_checker/llm.py:89-96` (`request_id_hook`)
- Modify: `docs-checker/src/docs_checker/server.py:249-273` (`build_models` picks the provider)
- Modify: `docs-checker/pyproject.toml` (`anthropic[bedrock]`), `uv.lock`
- Test: `docs-checker/tests/test_models.py`, `tests/test_config.py`, `tests/test_ledger.py`, `tests/test_llm.py`

**Interfaces:**
- Produces, on `Settings`:
  - `model_provider: Literal["anthropic", "bedrock"] = "anthropic"`;
  - `bedrock_model_ids: dict[str, str] = {}`, mapping a logical model name to a profile ARN;
  - `aws_region: str = ""`.
- Produces: `class BedrockModels(AnthropicModels)` with `__init__(self, node_models, levers, *, model_ids: dict[str, str], aws_region: str, http_timeout_s: float, transport=None, on_response=None, send_effort: bool)`. `name(node)` still returns the logical name, so the ledger prices by logical name.
- Env:
  - `DOCS_CHECKER_MODEL_PROVIDER=bedrock`;
  - `DOCS_CHECKER_BEDROCK_MODEL_IDS` as a JSON object, whose keys must equal `ALLOWED_MODELS` exactly;
  - `AWS_REGION`;
  - `DOCS_CHECKER_RATE_CARD=bedrock-global-2026-10-19`.

- [ ] **Step 1: Write the failing tests.**
  - `test_bedrock_models_invoke_the_profile_arn`: with a fake transport, the request URL path contains the URL-encoded Haiku profile ARN and `/invoke`, and `name("extract") == "claude-haiku-5-5"`.
  - `test_bedrock_models_need_a_full_id_map`: `load_settings` with `MODEL_PROVIDER=bedrock` and a map missing Sonnet raises `ValueError` naming `claude-sonnet-5-5`.
  - `test_bedrock_rate_card_matches_pricing_api`: `RATE_CARDS["bedrock-global-2026-10-19"].rates_for("claude-sonnet-5-5", 1000) == Rates(2.00, 2.50, 4.00, 0.10, 10.00)`, and the Haiku tiers equal the Global Constraints figures.
  - `test_request_id_hook_reads_bedrock_header`: a response with only `x-amzn-requestid: abc` records `request_id == "abc"`.
  - `test_anthropic_path_unchanged`: with no provider env, `build_models` returns `AnthropicModels`, not a subclass.
- [ ] **Step 2: Run them to see them fail.** Run: `.venv/bin/pytest tests/test_models.py tests/test_config.py tests/test_ledger.py tests/test_llm.py -q`. Expected: the five new tests FAIL.
- [ ] **Step 3: Implement.**
  - `BedrockModels._build` builds `ChatAnthropic(model=<profile ARN>, api_key="bedrock-unused", ...)` with `effort` only when `send_effort`. It then replaces `chat.__dict__["_async_client"]` with `anthropic.AsyncAnthropicBedrock(aws_region=..., max_retries=..., timeout=..., http_client=anthropic.DefaultAsyncHttpxClient(**http_kwargs))`, the same seam `AnthropicModels._build` uses.
  - `send_effort` comes from the Task 2 `effort` result through `DOCS_CHECKER_BEDROCK_EFFORT` (default `false`).
  - `request_id_hook` falls back from `request-id` to `x-amzn-requestid`.
  - Add the `bedrock-global-2026-10-19` card. Its Haiku long-context threshold stays at `100_000` unless Task 2 measured another.
  - Add `anthropic[bedrock]` to the dependencies and run `uv lock`.
- [ ] **Step 4: Run the full suite.** Run: `.venv/bin/pytest -q`. Expected: all pass, including the smoke replay.
- [ ] **Step 5: Commit.**

```bash
git add docs-checker/src docs-checker/tests docs-checker/pyproject.toml docs-checker/uv.lock
git commit -m "feat(docs-checker): Bedrock model client and rate card"
```

### Task 4: AgentCore settings and session-storage SQLite

**Files:**
- Modify: `docs-checker/src/docs_checker/config.py`
- Modify: `docs-checker/src/docs_checker/graph.py:229-237` (`open_checkpointer`)
- Test: `docs-checker/tests/test_config.py`, `tests/test_restart.py`

**Interfaces:**
- Produces, on `Settings`:
  - `runtime: Literal["kagent", "agentcore", "local"]`, from `DOCS_CHECKER_RUNTIME`, default `kagent` when `KAGENT_CONFIG_JSON` is set and `local` otherwise;
  - `sqlite_nolock: bool`, true when the runtime is `agentcore`.
- Produces: `open_checkpointer(path: str, *, nolock: bool = False)`. When `nolock` is set, it opens `file:<path>?nolock=1` with `uri=True` and runs `PRAGMA journal_mode=MEMORY` and `PRAGMA synchronous=OFF` before yielding.
- With the `agentcore` runtime:
  - `KAGENT_CONFIG_JSON` is ignored;
  - `data_dir` defaults to `/mnt/workspace/docs-checker`;
  - `a2a_port` is 9000;
  - MCP servers come from `DOCS_CHECKER_MCP_URL`, one server named `github` with an empty header map (Task 6 adds the auth).

- [ ] **Step 1: Write the failing tests.**
  - `test_agentcore_runtime_defaults`: env `{"DOCS_CHECKER_RUNTIME": "agentcore", "DOCS_CHECKER_MCP_URL": "https://gw.example/mcp"}` gives `a2a_port == 9000`, `data_dir == "/mnt/workspace/docs-checker"`, `sqlite_nolock is True`, `under_kagent is False`, and one MCP server whose URL is `https://gw.example/mcp`.
  - `test_agentcore_requires_mcp_url`: the same env without the URL raises `ValueError`.
  - `test_nolock_checkpointer_pragmas`: opening a temp db with `nolock=True` reads back `journal_mode == "memory"` and `synchronous == 0`.
  - `test_nolock_checkpoint_survives_reopen`: a checkpoint written, closed and reopened with `nolock=True` is still there.
- [ ] **Step 2: Run them to see them fail.** Run: `.venv/bin/pytest tests/test_config.py tests/test_restart.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** `_open_checkpoints` passes `nolock=settings.sqlite_nolock`.
- [ ] **Step 4: Run the full suite.** Run: `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.**

```bash
git commit -am "feat(docs-checker): AgentCore settings and session-storage SQLite"
```

### Task 5: A2A JSON-RPC server for AgentCore

**Files:**
- Create: `docs-checker/src/docs_checker/agentcore.py`
- Modify: `docs-checker/src/docs_checker/server.py:85-121` (`build_agent_card` takes the interface URL and binding)
- Modify: `docs-checker/pyproject.toml` (new extra `agentcore = ["a2a-sdk[http-server,sqlite]>=1.2.2,<2", "uvicorn>=0.54,<1", "boto3>=1.40"]`, script `docs-checker-agentcore = "docs_checker.agentcore:main"`), `uv.lock`
- Test: `docs-checker/tests/test_agentcore.py`

**Interfaces:**
- Consumes: `server.open_executor(settings)`, `Settings.runtime == "agentcore"` (Task 4).
- Produces:
  - `build_agent_card(settings, *, url: str, binding: Literal["GRPC", "JSONRPC"]) -> AgentCard`. kagent passes the old values; the card's other fields are unchanged.
  - `async def open_task_store(stack: AsyncExitStack, settings: Settings) -> TaskStore`: a2a-sdk `DatabaseTaskStore` on `sqlite+aiosqlite:///<data_dir>/tasks.sqlite?nolock=1`, falling back to `InMemoryTaskStore` with a warning, the same pattern as `_open_checkpoints`.
  - `def build_app(handler, card) -> Starlette`: `create_agent_card_routes(card)` plus `create_jsonrpc_routes(handler, rpc_url="/")` plus `GET /ping` returning `{"status": "Healthy"}`.
  - `def main() -> None`: logging to stdout (stderr is captured too); uvicorn on `0.0.0.0:9000`; a startup phase log like `server.serve`.
- The card URL comes from env `AGENTCORE_RUNTIME_URL`, default `http://127.0.0.1:9000/`.

- [ ] **Step 1: Write the failing tests** (Starlette `TestClient`, the fake graph from `tests/fake_graph.py`).
  - `test_agent_card_served`: `GET /.well-known/agent-card.json` returns 200 with `supportedInterfaces[0].protocolBinding == "JSONRPC"`.
  - `test_ping`: `GET /ping` returns 200.
  - `test_message_send_completes`: a JSON-RPC `SendMessage` with text `check docs/USAGE.md` reaches `TASK_STATE_COMPLETED`, with a `docs-checker/report` data part.
  - `test_pause_survives_restart`: a fake graph that interrupts leaves the task `TASK_STATE_INPUT_REQUIRED`. Close the app and its stores, build a new one on the same `data_dir`, send the approval with the same `taskId` and `contextId`, and the task reaches `TASK_STATE_COMPLETED` with one ledger (no restart note). This is Review Focus 1.
  - `test_kagent_card_unchanged`: `build_agent_card(settings, url="http://127.0.0.1:80", binding="GRPC")` equals today's card byte for byte.
- [ ] **Step 2: Run them to see them fail.** Run: `.venv/bin/pytest tests/test_agentcore.py -q`. Expected: FAIL (the module is missing).
- [ ] **Step 3: Implement** `agentcore.py`, reusing `open_executor`, with `DefaultRequestHandlerV2(agent_executor=executor, task_store=<from open_task_store>, agent_card=card)`.
- [ ] **Step 4: Run the full suite.** Run: `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.**

```bash
git add docs-checker/src docs-checker/tests docs-checker/pyproject.toml docs-checker/uv.lock
git commit -m "feat(docs-checker): A2A JSON-RPC server for AgentCore Runtime"
```

### Task 6: Gateway and GitHub MCP target, SigV4 tool client

**Files:**
- Create: `docs-checker/deploy/agentcore/02-gateway.sh`
- Create: `docs-checker/src/docs_checker/aws_auth.py`
- Modify: `docs-checker/src/docs_checker/server.py:224-246` (`load_mcp_tools` passes `auth`)
- Modify: `docs-checker/src/docs_checker/tools.py` (canonical names)
- Test: `docs-checker/tests/test_tools.py`, `tests/test_aws_auth.py`

**Interfaces:**
- Produces:
  - `class SigV4Auth(httpx.Auth)` with `__init__(self, *, service: str, region: str)`. It signs each request with botocore's `SigV4Auth` from the default credential chain, which is the runtime role.
  - `canonical_tool_name(name: str) -> str` strips one leading `<target>___` prefix.
  - `ToolBelt` filters and calls by the canonical name, and sends the original name to the server.
- `02-gateway.sh` (`--check` / `--apply`) creates:
  - the API-key credential provider `docs-checker-github`. Ari pastes the PAT through `read -rs`; it never touches argv or a file.
  - the gateway `docs-checker` with protocol `MCP` and authorizer `AWS_IAM`;
  - the target `github` as an `mcpServer` pointed at GitHub's hosted read-only MCP endpoint with the `repos` toolset.

  It prints `MCP_URL=<gateway url>` to `out/gateway.env` and adds `bedrock-agentcore:InvokeGateway` on the gateway ARN to the Task 1 role.
- **Fallback** if `--apply` rejects an `API_KEY` provider on an `mcpServer` target, or the target's tool list is empty: record it in `docs/agentcore-probes.md` as `PROBE gateway_api_key: rejected`. Then ship `github-mcp-server --read-only --toolsets repos` in the image as a stdio server (`McpServer` with `transport="stdio"`), with the PAT fetched at startup from the same credential provider through `GetResourceApiKey`. Tasks 10 and 11 follow whichever path the probe line names.

- [ ] **Step 1: Write the failing tests.**
  - `test_canonical_tool_name`: `canonical_tool_name("github___get_file_contents") == "get_file_contents"` and `canonical_tool_name("get_commit") == "get_commit"`.
  - `test_prefixed_write_tool_refused`: a server listing `github___create_or_update_file` and `github___get_file_contents` leaves the belt holding only `get_file_contents`. This is Review Focus 2.
  - `test_prefixed_call_sends_original_name`: a belt call to `get_file_contents` reaches the fake server as `github___get_file_contents`.
  - `test_sigv4_signs_request`: with static fake credentials, a signed request carries `Authorization: AWS4-HMAC-SHA256 Credential=AKID/<date>/us-west-2/bedrock-agentcore/aws4_request` and `x-amz-date`.
- [ ] **Step 2: Run them to see them fail.** Run: `.venv/bin/pytest tests/test_tools.py tests/test_aws_auth.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the canonical names, `SigV4Auth`, and `load_mcp_tools` passing `"auth": SigV4Auth(service="bedrock-agentcore", region=settings.aws_region)` when `settings.runtime == "agentcore"`.
- [ ] **Step 4: Run the full suite** (`.venv/bin/pytest -q`, all pass). Then **Ari runs `02-gateway.sh --apply`**, and the executor runs `--check`. Expected: provider, gateway and target `OK`; `aws bedrock-agentcore-control list-gateway-targets` shows `github` READY.
- [ ] **Step 5: Commit.**

```bash
git add docs-checker/src docs-checker/tests docs-checker/deploy/agentcore/02-gateway.sh
git commit -m "feat(docs-checker): Gateway MCP tools with SigV4 and canonical tool names"
```

### Task 7: Repo profiles for the OpenTofu repos

**Files:**
- Create: `docs-checker/src/docs_checker/profile.py`
- Create: `docs-checker/profiles/chg-infra-opentofu-bedrock.yaml`, `docs-checker/profiles/chg-infra-opentofu-opensearch.yaml`
- Modify: `docs-checker/src/docs_checker/graph.py:329-360` (`scope` uses `doc_meta`)
- Modify: `docs-checker/src/docs_checker/scope.py:82-130` (`discover` uses the profile list when one is set)
- Modify: `docs-checker/src/docs_checker/prompts.py` (repo and domain text from the profile)
- Modify: `docs-checker/src/docs_checker/config.py` (`DOCS_CHECKER_PROFILE`)
- Test: `docs-checker/tests/test_profile.py`, `tests/test_scope.py`, `tests/test_prompts.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class RepoProfile` with these fields:
  - `repo: str`;
  - `domain: str`, the phrase that replaces "Kubernetes manifest, a Helm values file, an Argo CD Application";
  - `docs: dict[str, tuple[SourceRef, ...]]`, in file order.
- Produces:
  - `load_profile(path: str) -> RepoProfile`, which raises `ValueError` on a doc with no sources, a source that is itself a doc (`not is_evidence_source`), or a repo different from `Settings.repo`;
  - `doc_meta(path: str, text: str, profile: RepoProfile | None) -> DocMeta`: the profile's sources when the path is in it, otherwise `parse_front_matter`.
- `KUBERNETES_PROFILE_TEXT` keeps today's prompt strings verbatim, so no profile means byte-identical prompts.
- Profile YAML shape: `repo:`, `domain:`, then `docs:` mapping each doc path to a list of `path:` or `dir:` sources.
- Starting content, from the docs and skill tables read on 2026-10-19:
  - **bedrock:** `docs/BEDROCK-DEVELOPER-RUNBOOK.md` against `variables.tf`, `environments/sb-eip/config.tfvars`, `environments/common-nonprod/config.tfvars`, `environments/common-prod/config.tfvars`, `iam.tf`, `inference_profiles.tf`, `cloudwatch.tf`. `docs/USAGE.md` against `variables.tf`, `outputs.tf`, `iam.tf`, `iam_user.tf`, `kubernetes.tf`, `dir: .github/workflows`.
  - **opensearch:** `docs/OPENSEARCH-DEVELOPER-RUNBOOK.md` against `variables.tf`, `iam.tf`, `opensearch.tf`, `locals.tf`, `main.tf`, `environments/sb-eip/config.tfvars`. `USAGE.md` against `variables.tf`, `outputs.tf`.

  Ari reviews both files before the first live run.
- `domain`: `"an OpenTofu module (variables.tf, resources, outputs), an environment's config.tfvars, or a GitHub Actions workflow"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_profile_sources_replace_front_matter`: `doc_meta("docs/USAGE.md", "# no front matter\n", profile).sources[0].value == "variables.tf"`.
  - `test_profile_rejects_doc_as_source`: a source `docs/README.md` raises `ValueError`.
  - `test_discover_uses_profile_docs`: `discover` with a profile returns exactly the profile's doc paths, in order.
  - `test_missing_profile_source_needs_404`: a profile source that reads `forbidden` makes the doc `incomplete`, never a `missing` finding; one that reads `absent` gives a `missing` finding. This is Review Focus 4.
  - `test_prompts_unchanged_without_profile`: the `system_message` output for every node equals a golden copy taken before this change.
  - `test_shipped_profiles_load`: both YAML files load.
- [ ] **Step 2: Run them to see them fail.** Run: `.venv/bin/pytest tests/test_profile.py tests/test_scope.py tests/test_prompts.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The executor's deps carry `profile`, loaded once at startup from `DOCS_CHECKER_PROFILE` (a path inside the image, `/app/profiles/<name>.yaml`).
- [ ] **Step 4: Run the full suite.** Run: `.venv/bin/pytest -q`. Expected: all pass, and the smoke cassettes replay unchanged.
- [ ] **Step 5: Commit.**

```bash
git add docs-checker/src docs-checker/tests docs-checker/profiles
git commit -m "feat(docs-checker): per-repo profiles for docs without sources front matter"
```

### Task 8: HCL comments are not evidence

**Files:**
- Modify: `docs-checker/src/docs_checker/evidence.py:20-82`
- Test: `docs-checker/tests/test_evidence.py`

**Interfaces:**
- Produces: `code_text(path: str, text: str) -> str`. The path parameter is new, and every caller is updated. For `.tf`, `.tfvars` and `.hcl` paths it also drops `//` lines, inline `//` and `#` tails, and `/* ... */` spans, keeping line count by blanking. Other paths behave as today.

- [ ] **Step 1: Write the failing tests.**
  - `test_hcl_line_comment_not_evidence`: `default = "a" // was "b"` has no hit for `"b"`.
  - `test_hcl_block_comment_not_evidence`: a value only inside `/* ... */` across 3 lines has no hit, and the line count is preserved.
  - `test_yaml_unchanged`: today's YAML cases pass with the path argument added.
  - `test_url_in_hcl_string_kept`: `source = "https://example.com//x"` keeps the URL. Only `//` outside quotes is a comment.
- [ ] **Step 2: Run them to see them fail.** Run: `.venv/bin/pytest tests/test_evidence.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** with a small scanner that tracks double-quoted strings. Regex alone cannot keep the URL case.
- [ ] **Step 4: Run the full suite.** Run: `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.**

```bash
git commit -am "feat(docs-checker): strip HCL comments from evidence"
```

### Task 9: Findings to CloudWatch

**Files:**
- Create: `docs-checker/src/docs_checker/findings_sink.py`
- Modify: `docs-checker/src/docs_checker/executor.py` (call the sink after the report is built, before the completed status)
- Modify: `docs-checker/src/docs_checker/config.py` (`DOCS_CHECKER_FINDINGS_LOG_GROUP`, default empty, meaning off)
- Test: `docs-checker/tests/test_findings_sink.py`, `tests/test_executor.py`

**Interfaces:**
- Produces: `class CloudWatchFindings` with `__init__(self, *, log_group: str, stream_prefix: str, client=None)` and `async def publish(self, run_id: str, findings: list[Finding], summary: RunSummary) -> None`.
- Each finding becomes one event: `{"type": "finding", "run_id", "repo", "commit", "doc", "line_start", "line_end", "verdict", "confidence", "evidence": [...], "replacement", "fix_withheld"}`. One `{"type": "run", ...}` event carries docs checked, findings, cost in USD, model calls and incomplete docs.
- Every string has already been through `redact.py`, because the findings are taken from the same objects the report uses.
- It is `boto3.client("logs")` called through `asyncio.to_thread`. It creates the stream if missing and never raises: on any error it logs one warning (`findings not published: <error class>`) and returns.

- [ ] **Step 1: Write the failing tests.**
  - `test_one_event_per_finding_plus_run`: 3 findings give 4 events, the last with `type == "run"`.
  - `test_publish_failure_does_not_fail_task`: a client whose `put_log_events` raises `EndpointConnectionError` still leaves the task `COMPLETED`, with one warning logged. This is Review Focus 5.
  - `test_sink_off_by_default`: with no log group set, no client is built.
  - `test_events_are_redacted`: a finding whose evidence holds `ghp_` followed by 36 characters publishes the redacted form.
- [ ] **Step 2: Run them to see them fail.** Run: `.venv/bin/pytest tests/test_findings_sink.py tests/test_executor.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Run: `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.**

```bash
git add docs-checker/src docs-checker/tests
git commit -m "feat(docs-checker): publish findings to CloudWatch Logs"
```

## Phase 3: Image and deploy

### Task 10: ARM64 AgentCore image and local smoke

**Files:**
- Create: `docs-checker/Dockerfile.agentcore`
- Create: `docs-checker/scripts/smoke_agentcore.sh`
- Modify: `docs-checker/tests/test_dockerfile.py` (pin the new file's invariants; the kagent Dockerfile's tests are unchanged)

**Interfaces:**
- Image contract:
  - `--platform linux/arm64`;
  - the same two-stage bookworm build with uv-managed Python 3.13, base images pinned by digest;
  - `uv sync --locked --no-dev --extra agentcore`, with no kagent extra;
  - `COPY profiles/ /app/profiles/`;
  - uid 65532, `EXPOSE 9000`, `ENTRYPOINT ["/app/.venv/bin/docs-checker-agentcore"]`;
  - bytecode precompiled with `python -m compileall --invalidation-mode unchecked-hash /app/.venv` (cold-start lesson);
  - no key, `.env` or PAT in history or filesystem.
- If Task 6 fell back to stdio, the image also carries the `github-mcp-server` binary at a pinned release with its sha256 checked.

- [ ] **Step 1: Write the failing tests** in `test_dockerfile.py`:
  - `test_agentcore_dockerfile_arm64`;
  - `test_agentcore_dockerfile_port_9000`;
  - `test_agentcore_entrypoint`;
  - `test_agentcore_no_kagent_extra`;
  - `test_agentcore_base_images_pinned_by_digest`.
- [ ] **Step 2: Run them to see them fail.** Run: `.venv/bin/pytest tests/test_dockerfile.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Write the Dockerfile and `smoke_agentcore.sh`.** The smoke script builds, runs with `DOCS_CHECKER_RUNTIME=agentcore`, `DOCS_CHECKER_REPLAY_DIR` on the smoke cassettes and a temp volume at `/mnt/workspace`, and checks `/ping` 200, the card, and one completed `SendMessage`. It prints `smoke ok`, and reports seconds from container start to the first `/ping` 200.
- [ ] **Step 4: Run them.** Run: `.venv/bin/pytest -q`, then `bash scripts/smoke_agentcore.sh`. Expected: all pass; `smoke ok`; startup under 10 s native on arm64.
- [ ] **Step 5: Commit.**

```bash
git add docs-checker/Dockerfile.agentcore docs-checker/scripts/smoke_agentcore.sh docs-checker/tests/test_dockerfile.py
git commit -m "feat(docs-checker): ARM64 AgentCore image and smoke test"
```

### Task 11: Runtime deploy script

**Files:**
- Create: `docs-checker/deploy/agentcore/03-runtime.sh`
- Create: `docs-checker/deploy/agentcore/runtimes/bedrock.env`, `docs-checker/deploy/agentcore/runtimes/opensearch.env` (non-secret env per runtime)

**Interfaces:**
- Consumes: `out/foundation.env` (Task 1), `out/gateway.env` (Task 6), an image digest argument.
- Usage: `03-runtime.sh <bedrock|opensearch> --image <ecr uri>@sha256:<hex> [--check|--apply]`. It refuses a tag-only image reference.
- It creates the security group `docs-checker-runtime` if missing, then calls `create-agent-runtime` or `update-agent-runtime` with one full request built by the same function both times:
  - protocol `A2A`;
  - `networkMode VPC` with the three subnets and the security group;
  - `filesystemConfigurations=[{sessionStorage:{mountPath:/mnt/workspace}}]`;
  - lifecycle 3600 / 28800;
  - the role from Task 1;
  - the env from `runtimes/<name>.env` plus `DOCS_CHECKER_BEDROCK_MODEL_IDS`, `DOCS_CHECKER_MCP_URL` and `AWS_REGION`.
- After `--apply` it waits for `READY`, then runs `get-agent-runtime` and **fails** unless `filesystemConfigurations`, `networkMode` and the image digest read back as sent.
- `runtimes/bedrock.env` holds:
  - `DOCS_CHECKER_RUNTIME=agentcore`, `DOCS_CHECKER_MODEL_PROVIDER=bedrock`, `DOCS_CHECKER_RATE_CARD=bedrock-global-2026-10-19`;
  - `DOCS_CHECKER_REPO=chghealthcare/chg-infra-opentofu-bedrock`, `DOCS_CHECKER_PROFILE=/app/profiles/chg-infra-opentofu-bedrock.yaml`;
  - `DOCS_CHECKER_RUN_TIMEOUT_S=780`, `DOCS_CHECKER_FINDINGS_LOG_GROUP=/docs-checker/findings`, `DOCS_CHECKER_SEARCH=false`;
  - `DOCS_CHECKER_LEVERS`, set from the Task 2 cache result.

- [ ] **Step 1: Write the script and env files.**
- [ ] **Step 2: Run `--check`.** Run: `bash deploy/agentcore/03-runtime.sh bedrock --image <uri>@sha256:<hex> --check`. Expected: `MISSING runtime docs_checker_bedrock`, `MISSING sg docs-checker-runtime`, no mutating call.
- [ ] **Step 3: Ari pushes the image and applies.**
  - Build: `docker build --platform linux/arm64 --provenance=false -f Dockerfile.agentcore -t <uri>:<sha12> .`.
  - Push, read the digest, then run `03-runtime.sh bedrock --image <uri>@sha256:<hex> --apply`.
  - Expected: `READY` and the read-back check passes. If VPC mode rejects an AZ, the error names it: drop that subnet from `SUBNETS`, record it in `docs/agentcore-probes.md` as `PROBE vpc_az: <az id> unsupported`, and re-run.
- [ ] **Step 4: Commit.**

```bash
git add docs-checker/deploy/agentcore
git commit -m "feat(docs-checker): AgentCore runtime deploy with full-config updates"
```

### Task 12: Interactive client

**Files:**
- Create: `docs-checker/scripts/ask_agentcore.py`
- Test: `docs-checker/tests/test_ask_agentcore.py`

**Interfaces:**
- Usage: `ask_agentcore.py --runtime <arn> [--session <id>] "<text>"`, and `ask_agentcore.py --runtime <arn> --session <id> --task <id> --approve <call id>[,...] | --reject <call id>[,...]`.
- It sends a JSON-RPC `SendMessage` to `https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/<url-encoded arn>/invocations?qualifier=DEFAULT`, SigV4-signed (`SigV4Auth` from Task 6) as `--profile sb-asela`, with header `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`.
- A new session id is `docs-checker-` plus a 32-character hex string (AgentCore needs at least 33 characters). The client prints it with the `contextId` and `taskId` for follow-ups.
- It prints the report text, any pending approvals (call id, doc, line, old and new text), and the ledger summary.

- [ ] **Step 1: Write the failing tests** (fake transport):
  - `test_new_session_id_length`: at least 33 characters, with prefix `docs-checker-`;
  - `test_approval_message_shape`: the payload carries a `tool_approval_response` data part keyed by call id, the same shape `executor.resume_map` reads;
  - `test_url_encodes_arn`.
- [ ] **Step 2: Run them to see them fail.** Run: `.venv/bin/pytest tests/test_ask_agentcore.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite.** Run: `.venv/bin/pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit.**

```bash
git add docs-checker/scripts/ask_agentcore.py docs-checker/tests/test_ask_agentcore.py
git commit -m "feat(docs-checker): interactive SigV4 A2A client for AgentCore"
```

### Task 13: First live runs and acceptance

**Files:**
- Modify: `docs-checker/docs/agentcore-probes.md` (acceptance results)
- Modify: `docs-checker/docs/bedrock-agentcore-handover.md` (replace §3's plan with what shipped, and §7 with the answers)

Each step below is a check with a stated result. Stop and bring back the numbers on any miss.

- [ ] **Step 1: One doc.** Run: `ask_agentcore.py --runtime <bedrock arn> "check docs/BEDROCK-DEVELOPER-RUNBOOK.md"`. Expected:
  - completed in under 780 s, for no more than $0.10;
  - the doc status is `checked` or `incomplete` with its reason;
  - the ledger's `request_id` values are non-empty;
  - the `/aws/bedrock/invocations/sb-asela` log shows calls under the two docs-checker profile ARNs, not raw model IDs.
- [ ] **Step 2: Logs.** `/aws/bedrock-agentcore/runtimes/<id>-DEFAULT` shows the startup phase lines (from stdout), and a deliberately bad request's traceback appears too (from stderr).
- [ ] **Step 3: Findings.** Logs Insights on `/docs-checker/findings` with `filter type = "finding"` returns one row per finding in the A2A report, and one `type = "run"` row.
- [ ] **Step 4: Pause and resume.**
  - In interactive mode with a fix that the gate marks `ask`, the task is `input-required`.
  - Approve within the same session: the task completes with one ledger.
  - Then repeat, waiting longer than `idleRuntimeSessionTimeout` (temporarily 300 s via `03-runtime.sh` with `IDLE_TIMEOUT=300`) before approving. Expected: it resumes from the checkpoint, not "Task not found". If it fails, record `PROBE session_storage_after_idle: lost` and open a follow-up to switch to the `dynamodb` saver in `langgraph-checkpoint-aws` 1.2.5.
- [ ] **Step 5: Read-only proof.** `list-gateway-targets` and the belt's startup log show exactly the four tools. A request asking it to "open a PR fixing this" is refused as off-topic.
- [ ] **Step 6: Second runtime.** `03-runtime.sh opensearch ... --apply`, then one doc check on `docs/OPENSEARCH-DEVELOPER-RUNBOOK.md`, with the same expectations as Step 1.
- [ ] **Step 7: Record and commit.**

```bash
git add docs-checker/docs
git commit -m "docs(docs-checker): AgentCore acceptance results and updated handover"
```

## Not in this plan

- Labelled eval sets for the OpenTofu repos (Ari labels; `python -m docs_checker.evals.curate`). Until they exist, precision on these repos is unmeasured, and every finding is a candidate.
- The weekly trigger, the memory snapshot store (S3 with `If-Match`), async mode for `check all`.
- A CloudWatch or Grafana dashboard over `/docs-checker/findings`.
- VPC endpoints for Bedrock, ECR, Logs and AgentCore (traffic uses NAT today).
- Running `check all` on AgentCore: it must finish inside 15 minutes or move to async.
