"""Bedrock probes for the AgentCore port: what the Haiku 5.5 application profile accepts.

    uv run --with 'anthropic[bedrock]==1.15.0' python scripts/bedrock_probe.py

Reads HAIKU_PROFILE_ARN from deploy/agentcore/out/foundation.env (written by
01-foundation.sh) and calls it as sb-asela with max_tokens 16 each time. Prints one
``PROBE <name>: <result>`` line per answer that Tasks 3 and 6 branch on; the cost is a
fraction of a cent. Nothing here runs in the agent.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import anthropic

from docs_checker import prompts

HERE = Path(__file__).resolve().parent.parent
FOUNDATION_ENV = HERE / "deploy" / "agentcore" / "out" / "foundation.env"
QUESTION = [{"role": "user", "content": "Reply with the single word: ok"}]
# Padding sized well past 4096 tokens, so a zero read on the
# real prompt can be told apart from caching not working at all.
PADDING = "\n".join(
    f"Reference line {i}: this line is padding for a cache probe." for i in range(450)
)


def profile_arn() -> str:
    for line in FOUNDATION_ENV.read_text().splitlines():
        key, _, value = line.partition("=")
        if key == "HAIKU_PROFILE_ARN" and value:
            return value
    sys.exit(f"HAIKU_PROFILE_ARN not in {FOUNDATION_ENV}; run 01-foundation.sh first")


async def call(
    client: anthropic.AsyncAnthropicBedrock, model: str, **kwargs: Any
) -> tuple[Any, Any]:
    raw = await client.messages.with_raw_response.create(
        model=model, max_tokens=16, messages=QUESTION, **kwargs
    )
    return raw, await raw.parse()


async def cache_pair(client: anthropic.AsyncAnthropicBedrock, model: str, text: str) -> list[dict]:
    system = [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]
    usages = []
    for _ in range(2):
        _, message = await call(client, model, system=system)
        usages.append(message.usage.model_dump())
    return usages


async def main() -> None:
    model = profile_arn()
    client = anthropic.AsyncAnthropicBedrock(aws_region="us-west-2", aws_profile="sb-asela")

    raw, message = await call(client, model)
    print("headers:", sorted(raw.headers.keys()))
    print("usage:", json.dumps(message.usage.model_dump()))
    print(
        f"PROBE usage_shape: {sorted(k for k, v in message.usage.model_dump().items() if v is not None)}"
    )
    request_ids = {k: raw.headers[k] for k in raw.headers if "request" in k.lower()}
    print(f"PROBE request_id_header: {request_ids}")

    try:
        await call(client, model, extra_body={"output_config": {"effort": "low"}})
        print("PROBE effort: accepted")
    except anthropic.BadRequestError as error:
        print(f"PROBE effort: rejected ({error.status_code}: {error.message})")

    for label, text in (("extract", prompts.EXTRACT), ("padded", prompts.EXTRACT + "\n" + PADDING)):
        first, second = await cache_pair(client, model, text)
        print(f"cache {label}: first={json.dumps(first)} second={json.dumps(second)}")
        print(
            f"PROBE cache_{label}: input_tokens={first['input_tokens'] + (first.get('cache_creation_input_tokens') or 0)}"
            f" write={first.get('cache_creation_input_tokens')} read={second.get('cache_read_input_tokens')}"
        )
    print("PROBE haiku_long_ctx_threshold: unknown (not probed; needs a >200k-token call)")


if __name__ == "__main__":
    asyncio.run(main())
