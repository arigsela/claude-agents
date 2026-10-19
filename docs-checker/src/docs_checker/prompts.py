"""The agent's description and the cached system message (lever 1: cache the stable prefix).

Rules that keep each prefix byte-identical across runs, sessions and users:
no timestamps, no ids, no per-user data, no conditional sections. Everything
that varies goes in the user message after the cache breakpoint.
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage

AGENT_DESCRIPTION = (
    "Finds lines in the arigsela/kubernetes docs that no longer match the manifests they "
    "describe, and proposes the corrected line. Read-only."
)


def system_message(text: str, *, cache: bool, ttl: str = "5m") -> SystemMessage:
    """A system message whose last block carries the cache breakpoint."""
    block: dict = {"type": "text", "text": text}
    if cache:
        block["cache_control"] = (
            {"type": "ephemeral", "ttl": "1h"} if ttl == "1h" else {"type": "ephemeral"}
        )
    return SystemMessage(content=[block])
