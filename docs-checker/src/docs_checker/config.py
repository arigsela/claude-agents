"""Runtime configuration: what the kagent BYO compiler hands this container.

kagent 1.0 does not let a Harness carry secrets (env entries are literal values
only) and caps an actor at 32 environment variables, most of which kagent
itself sets. So almost everything comes from two places:

- ``KAGENT_CONFIG_JSON``: kagent v1.0.0-alpha14's ``ADKConfig``
  (proto/kagent/config/v1/adk.proto), written by the BYO compiler in ProtoJSON
  with proto field names. ``runtime`` holds the process settings (controller URL,
  agent name, namespace, A2A port); ``agent`` is the AgentTemplate compiled (model,
  instruction, MCP tool bindings with their URLs and tool filters). alpha14 sets no
  ``KAGENT_API_URL``/``KAGENT_NAME``/``KAGENT_PORT``, so none are read. ProtoJSON
  omits zero values: an absent bool is false and an absent string is empty.
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
from typing import Literal
from urllib.parse import urlsplit

from docs_checker.levers import Levers, parse_levers

# The A2A gRPC port the gateway dials (fixed by the BYO contract) and the
# readiness port Substrate probes. Neither is configurable upstream.
DEFAULT_A2A_PORT = 80
READY_PORT = 8081
# AgentCore Runtime's A2A contract: JSON-RPC on 9000, session storage at /mnt/workspace.
AGENTCORE_A2A_PORT = 9000
AGENTCORE_DATA_DIR = "/mnt/workspace/docs-checker"

_ENV_REF = re.compile(r"__KAGENT_ENV\[([A-Z0-9_]+)\]__")

# Nodes that call a model. Per-node model and effort are lever 6.
NODES = ("intake", "extract", "judge", "judge_escalate", "fix", "report")

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
ALLOWED_MODELS = frozenset({HAIKU, SONNET})

# node -> (model with right_size on, effort, max_tokens). With right_size off every
# node defaults to Sonnet. A DOCS_CHECKER_<NODE>_MODEL value still wins.
_DEFAULT_NODE_MODELS = {
    "intake": (HAIKU, "low", 1024),
    "extract": (HAIKU, "low", 4096),
    "judge": (HAIKU, "low", 2048),
    "judge_escalate": (SONNET, "medium", 2048),
    "fix": (HAIKU, "low", 2048),
    "report": (HAIKU, "low", 2048),
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
    levers: Levers = field(default_factory=Levers.all_on)
    # Run budget: $1.00 for a whole-repo run, $0.10 for a single doc.
    run_budget_all_usd: float = 1.00
    run_budget_doc_usd: float = 0.10
    max_calls_per_doc: int = 12
    # Where this process listens, as "host:port"; empty means the runtime port on every
    # interface and the probe port. docs_checker.front runs the server on loopback.
    listen_a2a: str = ""
    listen_ready: str = ""
    concurrency: int = 4
    http_timeout_s: float = 60.0
    tool_timeout_s: float = 30.0
    run_timeout_s: float = 900.0
    # Discovery and search bounds.
    max_docs: int = 80
    max_dir_files: int = 50
    max_file_bytes: int = 262144
    max_line_chars: int = 2000
    max_claims_per_doc: int = 25
    max_searches: int = 20
    search_interval_s: float = 6.0
    # Ruling S1: GitHub does not index arigsela/kubernetes, so the search fallback
    # is off unless DOCS_CHECKER_SEARCH says otherwise (and then only at HEAD).
    search_enabled: bool = False
    # kagent alpha14 snapshots persist only /data between turns.
    data_dir: str = "/data/docs-checker"
    checkpoint_db: str = "/data/docs-checker/checkpoints.sqlite"
    # A test seam, off unless set: every model response comes from the cassettes in this
    # directory (replay only, never recorded, nothing sent). The image smoke test runs on it.
    replay_dir: str = ""
    # Where model calls go: the Anthropic API (kagent, local) or Amazon Bedrock
    # (AgentCore). On Bedrock each logical model in ALLOWED_MODELS maps to an
    # application inference profile ARN, and effort is sent only when the profile
    # accepts it.
    model_provider: Literal["anthropic", "bedrock"] = "anthropic"
    bedrock_model_ids: dict[str, str] = field(default_factory=dict)
    aws_region: str = ""
    bedrock_effort: bool = False
    # Which runtime contract this process serves. On AgentCore, SQLite runs without
    # file locks (session storage has none).
    runtime: Literal["kagent", "agentcore", "local"] = "local"
    sqlite_nolock: bool = False

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


def _adk_config(env: Mapping[str, str]) -> tuple[dict, dict]:
    """Return ``(runtime, agent)`` from the alpha14 ``ADKConfig``; both empty locally.

    Any other top-level field means another contract, such as alpha11's bare
    ``AgentConfig``, whose controller has no ``kagent.runtime.v1`` TaskStore. Fail
    at startup rather than run locally, with an in-memory store and no tools.
    """
    raw = json.loads(env.get("KAGENT_CONFIG_JSON") or "{}")
    if not isinstance(raw, dict) or not set(raw) <= {"runtime", "agent"}:
        found = sorted(raw)[:6] if isinstance(raw, dict) else [type(raw).__name__]
        raise ValueError(
            "KAGENT_CONFIG_JSON is not a kagent v1.0.0-alpha14 ADKConfig ({runtime, agent}); "
            f"found: {', '.join(found)}"
        )
    return raw.get("runtime") or {}, raw.get("agent") or {}


def _prompt_cache(model: dict) -> tuple[bool, str]:
    """Prompt caching and its TTL from the compiled Anthropic provider block.

    With a provider block, an absent ``prompt_caching`` is false (ProtoJSON omits
    it). Without one, caching stays on with the 5m TTL: that is local mode only
    (the tests, the eval harness and the smoke test run with no provider block), so
    the cache lever can be measured offline; in-cluster the BYO compiler always
    writes the block of the ModelConfig the template binds.
    """
    if "anthropic" not in model:
        return True, "5m"
    anthropic = model["anthropic"] or {}
    return bool(anthropic.get("prompt_caching", False)), anthropic.get("cache_ttl") or "5m"


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


def _node_models(env: Mapping[str, str], levers: Levers) -> dict[str, NodeModel]:
    result = {}
    for node, (model, effort, max_tokens) in _DEFAULT_NODE_MODELS.items():
        key = node.upper()
        if not levers.right_size:
            model = SONNET
        chosen = env.get(f"DOCS_CHECKER_{key}_MODEL", model)
        if chosen not in ALLOWED_MODELS:
            raise ValueError(
                f"DOCS_CHECKER_{key}_MODEL {chosen!r} is not allowed; "
                f"allowed: {', '.join(sorted(ALLOWED_MODELS))}"
            )
        result[node] = NodeModel(
            model=chosen,
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


def _replay_dir(value: str) -> str:
    """Fail at startup on a replay directory that is not there, never miss every call."""
    if value and not os.path.isdir(value):
        raise ValueError(f"DOCS_CHECKER_REPLAY_DIR {value!r} is not a directory")
    return value


def _runtime(env: Mapping[str, str]) -> str:
    default = "kagent" if env.get("KAGENT_CONFIG_JSON") else "local"
    runtime = env.get("DOCS_CHECKER_RUNTIME", default)
    if runtime not in ("kagent", "agentcore", "local"):
        raise ValueError(
            f"DOCS_CHECKER_RUNTIME {runtime!r} is not allowed; allowed: kagent, agentcore, local"
        )
    return runtime


def _agentcore_mcp_servers(env: Mapping[str, str]) -> tuple[McpServer, ...]:
    """The Gateway's MCP endpoint, the one server on AgentCore. Requests are SigV4
    signed by the tool client (no headers here), and the binding names exactly the
    read tools, so the belt's allowlist is the same as in-cluster."""
    from docs_checker.tools import READ_ONLY_TOOLS

    url = env.get("DOCS_CHECKER_MCP_URL", "")
    if not url:
        raise ValueError("DOCS_CHECKER_MCP_URL is required with DOCS_CHECKER_RUNTIME=agentcore")
    return (McpServer(name="github", url=url, tools=tuple(sorted(READ_ONLY_TOOLS))),)


def _model_provider(env: Mapping[str, str]) -> tuple[str, dict[str, str], str]:
    """``(provider, model ids, region)``; Bedrock needs a profile for every allowed model."""
    provider = env.get("DOCS_CHECKER_MODEL_PROVIDER", "anthropic")
    if provider == "anthropic":
        return provider, {}, ""
    if provider != "bedrock":
        raise ValueError(
            f"DOCS_CHECKER_MODEL_PROVIDER {provider!r} is not allowed; allowed: anthropic, bedrock"
        )
    ids = json.loads(env.get("DOCS_CHECKER_BEDROCK_MODEL_IDS") or "{}")
    if not isinstance(ids, dict) or set(ids) != ALLOWED_MODELS or not all(ids.values()):
        missing = sorted(ALLOWED_MODELS - set(ids)) if isinstance(ids, dict) else []
        raise ValueError(
            "DOCS_CHECKER_BEDROCK_MODEL_IDS must map exactly "
            f"{', '.join(sorted(ALLOWED_MODELS))} to profile ARNs; missing: {', '.join(missing)}"
        )
    region = env.get("AWS_REGION", "")
    if not region:
        raise ValueError("AWS_REGION is required with DOCS_CHECKER_MODEL_PROVIDER=bedrock")
    return provider, {str(k): str(v) for k, v in ids.items()}, region


def _num(env: Mapping[str, str], name: str, default: float) -> float:
    return float(env.get(f"DOCS_CHECKER_{name}", default))


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(f"DOCS_CHECKER_{name}")
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    runtime_kind = _runtime(env)
    agentcore = runtime_kind == "agentcore"
    # AgentCore has no kagent controller: its ADKConfig, if one is set, is ignored.
    runtime, agent = ({}, {}) if agentcore else _adk_config(env)
    model = agent.get("model") or {}
    prompt_caching, cache_ttl = _prompt_cache(model)
    levers = parse_levers(env.get("DOCS_CHECKER_LEVERS", "all"))
    data_dir = env.get(
        "DOCS_CHECKER_DATA_DIR", AGENTCORE_DATA_DIR if agentcore else "/data/docs-checker"
    )
    model_provider, bedrock_model_ids, aws_region = _model_provider(env)

    return Settings(
        agent_name=runtime.get("name") or "docs-checker",
        namespace=runtime.get("namespace") or "kagent",
        # Absent selects the listener default; the BYO compiler always sends 80.
        a2a_port=AGENTCORE_A2A_PORT if agentcore else int(runtime.get("port") or DEFAULT_A2A_PORT),
        ready_port=READY_PORT,
        listen_a2a=env.get("DOCS_CHECKER_LISTEN_A2A", ""),
        listen_ready=env.get("DOCS_CHECKER_LISTEN_READY", ""),
        kagent_api_url=runtime.get("control_plane_url") or "",
        template_model=model.get("model") or "",
        prompt_caching=prompt_caching,
        cache_ttl=cache_ttl,
        mcp_servers=_agentcore_mcp_servers(env) if agentcore else parse_mcp_servers(agent, env),
        node_models=_node_models(env, levers),
        # LangGraph 1.2's default recursion limit is 10007; an explicit limit is
        # the circuit breaker.
        recursion_limit=int(env.get("DOCS_CHECKER_RECURSION_LIMIT", "80")),
        rate_card_version=_rate_card(env.get("DOCS_CHECKER_RATE_CARD", "anthropic-2026-10-18")),
        repo=_repo(env.get("DOCS_CHECKER_REPO", "arigsela/kubernetes")),
        levers=levers,
        run_budget_all_usd=_num(env, "RUN_BUDGET_ALL_USD", 1.00),
        run_budget_doc_usd=_num(env, "RUN_BUDGET_DOC_USD", 0.10),
        max_calls_per_doc=int(_num(env, "MAX_CALLS_PER_DOC", 12)),
        concurrency=int(_num(env, "CONCURRENCY", 4)),
        http_timeout_s=_num(env, "HTTP_TIMEOUT_S", 60.0),
        tool_timeout_s=_num(env, "TOOL_TIMEOUT_S", 30.0),
        run_timeout_s=_num(env, "RUN_TIMEOUT_S", 900.0),
        max_docs=int(_num(env, "MAX_DOCS", 80)),
        max_dir_files=int(_num(env, "MAX_DIR_FILES", 50)),
        max_file_bytes=int(_num(env, "MAX_FILE_BYTES", 262144)),
        max_line_chars=int(_num(env, "MAX_LINE_CHARS", 2000)),
        max_claims_per_doc=int(_num(env, "MAX_CLAIMS_PER_DOC", 25)),
        max_searches=int(_num(env, "MAX_SEARCHES", 20)),
        search_interval_s=_num(env, "SEARCH_INTERVAL_S", 6.0),
        search_enabled=_flag(env, "SEARCH", False),
        data_dir=data_dir,
        checkpoint_db=env.get("DOCS_CHECKER_CHECKPOINT_DB") or f"{data_dir}/checkpoints.sqlite",
        replay_dir=_replay_dir(env.get("DOCS_CHECKER_REPLAY_DIR", "")),
        model_provider=model_provider,
        bedrock_model_ids=bedrock_model_ids,
        aws_region=aws_region,
        bedrock_effort=_flag(env, "BEDROCK_EFFORT", False),
        runtime=runtime_kind,
        sqlite_nolock=agentcore,
    )
