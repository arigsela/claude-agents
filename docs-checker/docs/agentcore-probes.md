# AgentCore port: Bedrock probe results

Run 2026-10-19 by `scripts/bedrock_probe.py` (anthropic 1.15.0, `AsyncAnthropicBedrock`), as `sb-asela` in us-west-2, against application inference profile `docs-checker-claude-haiku-5-5` (`arn:aws:bedrock:us-west-2:414696729697:application-inference-profile/w1pxjj6skr1v`, copied from `global.anthropic.claude-haiku-5-5`). Every call used `max_tokens` 16.

```text
PROBE effort: accepted
PROBE cache_min_tokens_haiku: <= 712 (the 712-token EXTRACT prompt wrote 712 and read 712 on the repeat)
PROBE usage_shape: ['cache_creation', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'input_tokens', 'output_tokens', 'output_tokens_details', 'service_tier']
PROBE request_id_header: x-amzn-requestid (no request-id header)
PROBE haiku_long_ctx_threshold: unknown (not probed; needs a >200k-token call)
```

## What the plan does with them

- **`effort`:** accepted through `extra_body={"output_config": {"effort": "low"}}`. Task 3's Bedrock models keep sending it.
- **Cache:** the cache lever stays on in the Task 11 env. A 9,712-token prompt also wrote and read in full, so caching works at both sizes. The minimum is at most 712 tokens; the probe did not look for the exact floor.
- **Usage shape:** the same keys the ledger parses on the Anthropic API (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, plus the `cache_creation` 5m/1h split). `inference_geo`, `server_tool_use` and `speed` come back null.
- **Request id:** Bedrock returns `x-amzn-requestid`, not `request-id`. `llm.request_id_hook` reads `request-id` only, so Task 3 must make it fall back to `x-amzn-requestid`, or the ledger records no request id on Bedrock.
- **Thinking:** with a system prompt present, Haiku 5.5 spent all 16 output tokens on thinking (`output_tokens_details.thinking_tokens` 16); the plain call without a system prompt spent 0. The probe can't tell whether this is the model's default or something Bedrock sets. Before Task 13, confirm the nodes' `max_tokens` still leaves room for an answer.

## Other response headers

`x-amzn-bedrock-cache-read-input-token-count`, `x-amzn-bedrock-cache-write-input-token-count`, `x-amzn-bedrock-input-token-count`, `x-amzn-bedrock-output-token-count`, `x-amzn-bedrock-invocation-latency`.

## Acceptance on AgentCore (2026-10-19)

Runtimes `docs_checker_bedrock-V3II5y2qYe` and `docs_checker_opensearch-rLh2yS3wal`, VPC mode on the three private subnets, session storage at `/mnt/workspace`, Gateway `docs-checker-dymlm9bjdd` with target `github` (GitHub's hosted MCP server, `x/repos/readonly`, fine-grained PAT in AgentCore Identity).

```text
PROBE gateway_api_key: accepted (API_KEY credential provider on an mcpServer target, header Authorization, prefix Bearer)
PROBE gateway_tools: 13 tools, all prefixed github___ and read-only; the belt keeps get_file_contents, search_code, list_commits, get_commit
PROBE github_structured_content: absent (tools list an outputSchema, results are text only; mcp 1.30.0 call_tool refuses them, so gateway_tools calls through send_request)
PROBE github_404: "Failed to get file contents. The path does not point to a file..." classifies absent
PROBE vpc_az: all three subnets accepted (usw2-az1, az2, az3)
PROBE session_storage: nfs4, 1 GiB; SQLite handles opened at process start failed their first commit (SQLITE_FULL) in 5-6 of 10 new sessions; opened on the first request: 12 of 12
PROBE session_storage_after_idle: kept (the A2A task and the checkpoint survived the idle stop)
PROBE cold_start: process serving 0.4 s after start; first request including cold start 3.9 s
```

| Check | Result |
|---|---|
| One doc, bedrock: `check docs/BEDROCK-DEVELOPER-RUNBOOK.md` | COMPLETED, 63 s, $0.0086, 9 calls; a second run $0.0132, 11 calls, `incomplete` (the 12-call per-doc cap left 3 claims unjudged); 0 findings |
| One doc, opensearch: `check docs/OPENSEARCH-DEVELOPER-RUNBOOK.md` | COMPLETED, 43 s, $0.0115, 7 calls, 0 findings |
| Request ids in the ledger | present (Bedrock `x-amzn-requestid`) |
| Bedrock invocation log `/aws/bedrock/invocations/sb-asela` | 20 of 20 calls under the two docs-checker profile ARNs, caller `docs-checker-agentcore`; no raw model ids |
| Runtime logs | startup phases on stdout; tracebacks of failed runs and a2a errors present |
| Findings log `/docs-checker/findings` | one `run` event per completed run in stream `<repo>/<run id>`; no `finding` rows yet (no findings) |
| Off-topic write request | refused, worded for the profile's repo |
| Pause and approve, same session | `input-required` (budget raise), then COMPLETED on the same task |
| Pause, idle stop, approve | idle timeout 300 s for the test; approved 6 m 46 s after the pause; a different microVM took the reply, found the task `input-required` on session storage and COMPLETED it (no "Task not found", no restart note) |
| Full-config update | 6 updates; every read-back kept session storage, VPC and the digest |

Not yet shown: a `finding` row (no doc had a stale line), and a fix-gate `ask` pause (the pause tests used the budget raise, the same HITL path).
