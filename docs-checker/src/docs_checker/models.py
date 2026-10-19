"""Per-node chat models (lever 6: right-size the model per node).

``ModelSet`` is the seam tests replace with fake chat models. The real one
builds ``ChatAnthropic`` lazily so importing this package needs no API key.

In-cluster there is no real key in the container: kagent sets
``ANTHROPIC_API_KEY`` to the placeholder ``kagent-credential-injected`` and the
Substrate egress gateway overwrites ``x-api-key`` on the way to
api.anthropic.com. The gateway intercepts TLS; httpx trusts its CA through
``SSL_CERT_FILE``, which kagent sets to /run/kagent/egress/trust-bundle.pem.

Retries (lever 5, ``retry_limits``). On: the SDK gets ``max_retries=0`` and a
timeout, so ``llm.call_model`` (3 attempts) is the only retry layer. Off: the
SDK keeps its default ``max_retries=2`` and has no timeout, under the same 3
``call_model`` attempts, which is the stacked default the spec compares against
(up to 9 calls).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from docs_checker.config import NodeModel
from docs_checker.levers import Levers


class ModelSet(Protocol):
    def get(self, node: str) -> Any: ...

    def name(self, node: str) -> str: ...


def no_tools_choice() -> dict:
    """``tool_choice`` for schemas that are bound but must not be called (tools_on_demand off).

    langchain-anthropic passes this dict through unchanged; the string ``"none"``
    would instead force a tool named "none".
    """
    return {"type": "none"}


class AnthropicModels:
    def __init__(
        self,
        node_models: dict[str, NodeModel],
        levers: Levers,
        *,
        http_timeout_s: float,
        transport: Any = None,
        on_response: Callable[[Any], Awaitable[None]] | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """``api_key`` and ``base_url`` default to ChatAnthropic's own (the
        ``ANTHROPIC_API_KEY`` and ``ANTHROPIC_BASE_URL`` env values); the eval harness
        passes both, so its key is the eval workspace's and nothing else."""
        self._specs = node_models
        self._levers = levers
        self._timeout_s = http_timeout_s
        self._transport = transport
        self._on_response = on_response
        self._api_key = api_key
        self._base_url = base_url
        self._cache: dict[str, Any] = {}

    def name(self, node: str) -> str:
        return self._specs[node].model

    def get(self, node: str) -> Any:
        if node not in self._cache:
            self._cache[node] = self._build(self._specs[node])
        return self._cache[node]

    def _build(self, spec: NodeModel) -> Any:
        import anthropic
        from langchain_anthropic import ChatAnthropic

        retry_limits = self._levers.retry_limits
        max_retries = 0 if retry_limits else 2
        timeout = self._timeout_s if retry_limits else None
        explicit: dict[str, Any] = {}
        if self._api_key is not None:
            explicit["api_key"] = self._api_key
        if self._base_url is not None:
            explicit["base_url"] = self._base_url
        chat = ChatAnthropic(
            model=spec.model,
            max_tokens=spec.max_tokens,
            effort=spec.effort,
            max_retries=max_retries,
            default_request_timeout=timeout,
            **explicit,
        )
        # Own the HTTP client so the request-id hook and a replay transport reach it.
        http_kwargs: dict[str, Any] = {"timeout": timeout}
        if self._transport is not None:
            http_kwargs["transport"] = self._transport
        if self._on_response is not None:
            http_kwargs["event_hooks"] = {"response": [self._on_response]}
        chat.__dict__["_async_client"] = anthropic.AsyncClient(
            api_key=chat.anthropic_api_key.get_secret_value(),
            base_url=chat.anthropic_api_url,
            max_retries=max_retries,
            timeout=timeout,
            http_client=anthropic.DefaultAsyncHttpxClient(**http_kwargs),
        )
        return chat
