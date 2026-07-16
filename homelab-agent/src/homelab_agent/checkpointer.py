"""Optional KAgentCheckpointer wiring.

LangGraph concept — checkpointer & threads:
a checkpointer persists the graph's state after every superstep, keyed by
`thread_id` (passed via config.configurable). Same thread_id → the graph
resumes from the saved state; different thread_id → a fresh conversation.
"Thread state persistence" = conversations survive pod restarts.

kagent's controller offers a checkpoint store over HTTP; KAgentCheckpointer
is the LangGraph adapter for it. kagent injects its config (KAGENT_URL etc.)
into BYO pods — locally those envs are absent and we run without
persistence, which keeps tests hermetic.

Pinned-environment note (Task 7 Step 1): `kagent-langgraph` 0.9.11 (pulling
in `kagent-core` 0.9.11) installs cleanly from PyPI and its
`kagent.langgraph._checkpointer` module (the real KAgentCheckpointer, needing
only httpx/langchain-core/pydantic/langgraph) is self-contained. But its
package `__init__.py` unconditionally imports `kagent.langgraph._a2a`, which
imports `a2a.server.apps.A2AStarletteApplication` — a class that existed in
a2a-sdk 0.3.x but was removed in a2a-sdk 1.x (this project pins
`a2a-sdk[http-server]>=0.3.10`, which resolves to 1.1.1). So
`from kagent.langgraph import KAgentCheckpointer` raises ModuleNotFoundError
in this environment even though the package is installed and genuinely
provides the class. We do not special-case around this (e.g. reaching into
the private `_checkpointer` submodule still executes the same broken
`__init__.py` first) — we let the natural ImportError degrade to `None`,
exactly like the "kagent packages absent" case, and surface it loudly below.

# TODO(deploy-follow-up): kagent-langgraph 0.9.11 is unusable as installed
# against a2a-sdk 1.x (and kagent-core 0.9.11 further requires the `openai`
# package for an unrelated otel auto-instrumentor it imports unconditionally).
# Before relying on KAgentCheckpointer in a real kagent deployment, pin a
# kagent-langgraph release compatible with the a2a-sdk major version this
# project uses (Task 8), or track upstream for a fix to the unconditional
# `_a2a` import in `kagent/langgraph/__init__.py`.
"""

import logging
import os

logger = logging.getLogger(__name__)


def get_checkpointer():
    """Return a KAgentCheckpointer when running under kagent, else None."""
    if not os.getenv("KAGENT_URL"):
        return None
    try:
        import httpx
        from kagent.core import KAgentConfig
        from kagent.langgraph import KAgentCheckpointer
    except ImportError as exc:
        logger.warning(
            "kagent packages unavailable or unimportable (%s); running without persistence",
            exc,
        )
        return None

    config = KAgentConfig()
    # Constructor signature discovered by reading kagent/langgraph/_checkpointer.py
    # directly (its normal import path is blocked in this environment — see the
    # module docstring above): KAgentCheckpointer(client: httpx.AsyncClient,
    # app_name: str, serde: SerializerProtocol | None = None). It calls the
    # KAgent Go service over HTTP, so it needs a configured async client, not a
    # bare base_url string.
    client = httpx.AsyncClient(base_url=config.url)
    return KAgentCheckpointer(client=client, app_name=config.app_name)
