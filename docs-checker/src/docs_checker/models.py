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


class BedrockModels(AnthropicModels):
    """The same per-node models through Amazon Bedrock (the AgentCore runtime).

    ChatAnthropic keeps the logical model name, so the request body, the prompt cache
    blocks and everything keyed on the name (the ledger's pricing, langchain's model
    checks) are the Anthropic path's. Only the SDK client differs: it signs with SigV4
    and, just before the URL is built, swaps the logical name for its application
    inference profile ARN (``/model/<arn>/invoke``). ``send_effort`` is off unless the
    profile accepts ``output_config.effort`` (docs/agentcore-probes.md).
    """

    def __init__(
        self,
        node_models: dict[str, NodeModel],
        levers: Levers,
        *,
        model_ids: dict[str, str],
        aws_region: str,
        http_timeout_s: float,
        transport: Any = None,
        on_response: Callable[[Any], Awaitable[None]] | None = None,
        send_effort: bool,
    ):
        super().__init__(
            node_models,
            levers,
            http_timeout_s=http_timeout_s,
            transport=transport,
            on_response=on_response,
            api_key="bedrock-unused",
        )
        self._model_ids = dict(model_ids)
        self._aws_region = aws_region
        self._send_effort = send_effort

    def _build(self, spec: NodeModel) -> Any:
        import anthropic
        from langchain_anthropic import ChatAnthropic

        retry_limits = self._levers.retry_limits
        max_retries = 0 if retry_limits else 2
        timeout = self._timeout_s if retry_limits else None
        chat = ChatAnthropic(
            model=spec.model,
            max_tokens=spec.max_tokens,
            effort=spec.effort if self._send_effort else None,
            max_retries=max_retries,
            default_request_timeout=timeout,
            api_key=self._api_key,
        )
        http_kwargs: dict[str, Any] = {"timeout": timeout}
        if self._transport is not None:
            http_kwargs["transport"] = self._transport
        if self._on_response is not None:
            http_kwargs["event_hooks"] = {"response": [self._on_response]}
        chat.__dict__["_async_client"] = _profile_client_class()(
            model_ids=self._model_ids,
            aws_region=self._aws_region,
            max_retries=max_retries,
            timeout=timeout,
            http_client=anthropic.DefaultAsyncHttpxClient(**http_kwargs),
        )
        return chat


def _profile_client_class() -> type:
    """``AsyncAnthropicBedrock`` that sends each logical model to its profile ARN.

    Built on first use so importing this module never imports the Bedrock client."""
    import anthropic

    class ProfileBedrock(anthropic.AsyncAnthropicBedrock):
        def __init__(self, *, model_ids: dict[str, str], **kwargs: Any):
            super().__init__(**kwargs)
            self._model_ids = model_ids

        async def _prepare_options(self, options: Any) -> Any:
            data = options.json_data
            if isinstance(data, dict) and data.get("model") in self._model_ids:
                remapped = {**data, "model": self._model_ids[data["model"]]}
                options = options.model_copy(update={"json_data": remapped})
            return await super()._prepare_options(options)

    return ProfileBedrock
