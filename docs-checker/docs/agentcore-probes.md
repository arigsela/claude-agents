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
