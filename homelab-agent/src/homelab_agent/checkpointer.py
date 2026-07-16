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

Pinned-environment note (Task 7 Step 1, revised after review): the original
probe hit `ModuleNotFoundError: No module named 'a2a.server.apps'`, because
this project's `a2a-sdk` pin resolved to 1.1.1 and `kagent.langgraph.__init__`
imports `kagent.langgraph._a2a`, which needs a class a2a-sdk 1.x removed.
kagent-langgraph 0.9.11 targets a2a-sdk 0.3.x (the same line oncall-crewai
runs in production against the same kagent 0.9.11 controller). Pinning
`a2a-sdk[http-server]>=0.3.10,<0.4` (nothing in Tasks 1-6 imports the `a2a`
package directly, so the downgrade was safe) resolves that import. It
surfaced one further undeclared transitive need: `kagent.core` unconditionally
imports an otel auto-instrumentor for `openai`, even though this project
never calls the OpenAI SDK — `openai` is pinned in pyproject.toml purely to
satisfy that import chain. See README's "Pinned environment" section for the
full resolved version table.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def get_checkpointer():
    """Return a KAgentCheckpointer when running under kagent, else None."""
    if not os.getenv("KAGENT_URL"):
        return None
    try:
        from kagent.core import KAgentConfig
        from kagent.langgraph import KAgentCheckpointer
    except ImportError as exc:
        logger.warning(
            "kagent packages unavailable or unimportable (%s); running without persistence",
            exc,
        )
        return None

    config = KAgentConfig()
    # Constructor signature confirmed via inspect.signature(KAgentCheckpointer.__init__)
    # against the real, importable package: it takes a configured
    # httpx.AsyncClient, not a bare base_url string.
    client = httpx.AsyncClient(base_url=config.url)
    return KAgentCheckpointer(client=client, app_name=config.app_name)
