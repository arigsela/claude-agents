"""Runtime configuration: what the kagent BYO compiler hands this container.

kagent 1.0 does not let a Harness carry secrets (env entries are literal values
only) and caps an actor at 32 environment variables, most of which kagent
itself sets. So almost everything comes from two places:

- ``KAGENT_CONFIG_JSON``: the ADK-shaped config compiled from the AgentTemplate
  (model, instruction, MCP tool bindings with their URLs and tool filters).
  v1.0.0-alpha11 sends the bare ``AgentConfig``; alpha14 wraps it as
  ``{"runtime": {...}, "agent": {...}}``. Both shapes parse here.
- Code defaults, overridable by a handful of literal ``DOCS_CHECKER_*`` env values.

Secrets never appear: the egress gateway injects ``x-api-key`` for the model
and Secret-backed MCP headers, and the runtime sees only the placeholder
``kagent-credential-injected`` (``__KAGENT_ENV[NAME]__`` in header values).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# The A2A gRPC port the gateway dials (fixed by the BYO contract) and the
# readiness port Substrate probes. Neither is configurable upstream.
DEFAULT_A2A_PORT = 80
READY_PORT = 8081

_ENV_REF = re.compile(r"__KAGENT_ENV\[([A-Z0-9_]+)\]__")

# Nodes that call a model. Per-node model and effort are lever 6.
NODES = ("router", "planner", "specialist", "responder")

_DEFAULT_NODE_MODELS = {
    "router": ("claude-haiku-5-5", "low", 1024),
    "planner": ("claude-sonnet-5-5", "medium", 4096),
    "specialist": ("claude-sonnet-5-5", "medium", 8192),
    "responder": ("claude-haiku-5-5", "low", 4096),
}


@dataclass(frozen=True)
class McpServer:
    """One MCP tool binding from the AgentTemplate, as compiled for the runtime."""

    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class NodeModel:
    model: str
    effort: str
    max_tokens: int


@dataclass(frozen=True)
class Settings:
    agent_name: str
    namespace: str
    a2a_port: int
    ready_port: int
    kagent_api_url: str
    template_model: str
    prompt_caching: bool
    cache_ttl: str
    mcp_servers: tuple[McpServer, ...]
    node_models: dict[str, NodeModel]
    recursion_limit: int
    rate_card_version: str
    # The one repository the repo tools may read (owner/name).
    repo: str = "arigsela/kubernetes"

    @property
    def under_kagent(self) -> bool:
        """True when the controller TaskStore is configured (in-cluster)."""
        return bool(self.kagent_api_url)


def _expand_env_refs(value: str, env: Mapping[str, str]) -> str:
    """Replace ``__KAGENT_ENV[NAME]__`` with that env value (a placeholder in-cluster)."""
    return _ENV_REF.sub(lambda m: env.get(m.group(1), ""), value)


def _server_name(url: str, index: int) -> str:
    host = urlsplit(url).hostname or ""
    return host.split(".")[0] or f"mcp-{index}"


def _agent_config(raw: dict) -> dict:
    """Return the AgentConfig from either config shape (alpha11 bare, alpha14 wrapped)."""
    if isinstance(raw.get("agent"), dict):
        return raw["agent"]
    return raw


def parse_mcp_servers(agent: dict, env: Mapping[str, str]) -> tuple[McpServer, ...]:
    servers: list[McpServer] = []
    names: dict[str, str] = {}  # server name -> url, so two servers never share a name
    bindings = list(agent.get("http_tools") or []) + list(agent.get("sse_tools") or [])
    for index, binding in enumerate(bindings):
        params = binding.get("params") or {}
        url = params.get("url") or ""
        if not url:
            continue
        name = _server_name(url, index)
        if names.get(name, url) != url:
            # Same host, different endpoint: a distinct server, so a distinct name
            # (tools are authorized per server name).
            name = f"{name}-{index}"
        names[name] = url
        headers = {
            name: _expand_env_refs(str(value), env)
            for name, value in (params.get("headers") or {}).items()
        }
        servers.append(
            McpServer(
                name=name,
                url=url,
                headers=headers,
                tools=tuple(sorted(binding.get("tools") or ())),
            )
        )
    return tuple(servers)


def _node_models(env: Mapping[str, str]) -> dict[str, NodeModel]:
    result = {}
    for node, (model, effort, max_tokens) in _DEFAULT_NODE_MODELS.items():
        key = node.upper()
        result[node] = NodeModel(
            model=env.get(f"DOCS_CHECKER_{key}_MODEL", model),
            effort=env.get(f"DOCS_CHECKER_{key}_EFFORT", effort),
            max_tokens=int(env.get(f"DOCS_CHECKER_{key}_MAX_TOKENS", max_tokens)),
        )
    return result


def _rate_card(version: str) -> str:
    """Fail at startup on an unknown rate card, never price with a silent default."""
    from docs_checker.ledger import RATE_CARDS

    if version not in RATE_CARDS:
        known = ", ".join(sorted(RATE_CARDS))
        raise ValueError(f"unknown DOCS_CHECKER_RATE_CARD {version!r}; known: {known}")
    return version


def _repo(value: str) -> str:
    owner, sep, name = value.strip().partition("/")
    if not sep or not owner or not name or "/" in name:
        raise ValueError(f"DOCS_CHECKER_REPO must be owner/name, got {value!r}")
    return f"{owner}/{name}"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    raw = json.loads(env.get("KAGENT_CONFIG_JSON") or "{}")
    runtime = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
    agent = _agent_config(raw)
    model = agent.get("model") or {}

    return Settings(
        agent_name=env.get("KAGENT_NAME") or runtime.get("name") or "docs-checker",
        namespace=env.get("KAGENT_NAMESPACE") or runtime.get("namespace") or "kagent",
        a2a_port=int(env.get("KAGENT_PORT") or runtime.get("port") or DEFAULT_A2A_PORT),
        ready_port=READY_PORT,
        kagent_api_url=env.get("KAGENT_API_URL") or runtime.get("control_plane_url") or "",
        template_model=model.get("model") or "",
        prompt_caching=bool(model.get("prompt_caching", True)),
        cache_ttl=model.get("cache_ttl") or "5m",
        mcp_servers=parse_mcp_servers(agent, env),
        node_models=_node_models(env),
        # LangGraph 1.2's default recursion limit is 10007; a small explicit limit
        # is the circuit breaker (lever 5).
        recursion_limit=int(env.get("DOCS_CHECKER_RECURSION_LIMIT", "12")),
        rate_card_version=_rate_card(env.get("DOCS_CHECKER_RATE_CARD", "anthropic-2026-10-18")),
        repo=_repo(env.get("DOCS_CHECKER_REPO", "arigsela/kubernetes")),
    )
