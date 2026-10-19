"""Per-node chat models (lever 6: right-size the model per node).

``ModelSet`` is the seam tests replace with fake chat models. The real one
builds ``ChatAnthropic`` lazily so importing this package needs no API key.

In-cluster there is no real key in the container: kagent sets
``ANTHROPIC_API_KEY`` to the placeholder ``kagent-credential-injected`` and the
Substrate egress gateway overwrites ``x-api-key`` on the way to
api.anthropic.com. The gateway intercepts TLS; httpx 0.28 trusts its CA through
``SSL_CERT_FILE``, which kagent sets to /run/kagent/egress/trust-bundle.pem.
"""

from __future__ import annotations

from typing import Any, Protocol

from docs_checker.config import NodeModel


class ModelSet(Protocol):
    def get(self, node: str) -> Any: ...

    def name(self, node: str) -> str: ...


class AnthropicModels:
    def __init__(self, node_models: dict[str, NodeModel]):
        self._specs = node_models
        self._cache: dict[str, Any] = {}

    def name(self, node: str) -> str:
        return self._specs[node].model

    def get(self, node: str) -> Any:
        if node not in self._cache:
            from langchain_anthropic import ChatAnthropic

            spec = self._specs[node]
            self._cache[node] = ChatAnthropic(
                model=spec.model,
                max_tokens=spec.max_tokens,
                effort=spec.effort,
                # Lever 5: llm.call_model owns retries; the SDK must not add its own.
                max_retries=0,
                default_request_timeout=120,
            )
        return self._cache[node]
