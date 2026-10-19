import json

import protovalidate
import pytest
from google.protobuf.json_format import MessageToJson, ParseDict
from kagent.config.v1.adk_pb2 import ADKConfig

from docs_checker.config import load_settings

# translator.RuntimeConfig, as the alpha14 controller compiles it for a BYO agent. The
# name, namespace and port differ from the code defaults, so the assertions prove the parse.
RUNTIME = {
    "control_plane_url": "http://kagent-controller.kagent:8083",
    "gateway_url": "http://kagent-controller.kagent:8083",
    "name": "docs-checker-canary",
    "namespace": "agents",
    "log_level": "info",
    "port": 8080,
}

# adkconfig.Builder.compileAgent: an Anthropic ModelConfig and two MCP bindings, one with
# a Secret-backed header (only the __KAGENT_ENV[...]__ reference is compiled in).
AGENT = {
    "model": {
        "model": "claude-sonnet-5-5",
        "anthropic": {"prompt_caching": True, "cache_ttl": "1h"},
    },
    "description": "docs-checker",
    "http_tools": [
        {
            "params": {"url": "http://agent-docs-mcp.kagent:3000/mcp"},
            "tools": ["search_code", "get_file_contents"],
        },
        {
            "params": {
                "url": "http://backstage.backstage.svc.cluster.local/api/mcp-actions/v1/catalog",
                "headers": {"Authorization": "__KAGENT_ENV[KAGENT_CREDENTIAL_ABC123]__"},
            },
            "tools": ["get-catalog-entity"],
            "require_approval": True,
        },
    ],
    "stream": True,
    "session_db_url": "sqlite+aiosqlite:////data/sessions.db",
}


def compiled(runtime: dict, agent: dict) -> str:
    """KAGENT_CONFIG_JSON as compiler.go writes it: an ``ADKConfig`` in ProtoJSON with
    proto field names. Parsing through kagent-proto's generated message rejects any field
    the alpha14 contract does not have, so these fixtures cannot drift from it."""
    message = ParseDict({"runtime": runtime, "agent": agent}, ADKConfig())
    protovalidate.validate(message)
    return MessageToJson(message, preserving_proto_field_name=True, indent=None)


def test_alpha14_adk_config_is_parsed():
    env = {
        "KAGENT_CONFIG_JSON": compiled(RUNTIME, AGENT),
        "KAGENT_CREDENTIAL_ABC123": "kagent-credential-injected",
    }
    settings = load_settings(env)
    assert (settings.agent_name, settings.namespace) == ("docs-checker-canary", "agents")
    assert (settings.a2a_port, settings.ready_port) == (8080, 8081)
    assert settings.under_kagent
    assert settings.kagent_api_url == "http://kagent-controller.kagent:8083"
    assert settings.template_model == "claude-sonnet-5-5"
    assert (settings.prompt_caching, settings.cache_ttl) == (True, "1h")

    docs, catalog = settings.mcp_servers
    assert (docs.name, docs.url) == ("agent-docs-mcp", "http://agent-docs-mcp.kagent:3000/mcp")
    assert docs.tools == ("get_file_contents", "search_code")  # sorted
    assert docs.headers == {}
    assert catalog.name == "backstage"
    assert catalog.tools == ("get-catalog-entity",)
    # Secret-backed headers carry only the placeholder; the egress gateway injects the value.
    assert catalog.headers == {"Authorization": "kagent-credential-injected"}


def test_an_absent_port_selects_the_listener_default():
    runtime = {key: value for key, value in RUNTIME.items() if key != "port"}
    settings = load_settings({"KAGENT_CONFIG_JSON": compiled(runtime, AGENT)})
    assert (settings.a2a_port, settings.ready_port) == (80, 8081)


def test_protojson_omits_a_disabled_prompt_cache():
    # ProtoJSON drops zero values: a compiled Anthropic provider without
    # prompt_caching has it off, and an empty cache_ttl is the 5-minute default.
    agent = {**AGENT, "model": {"model": "claude-haiku-5-5", "anthropic": {"max_tokens": 1024}}}
    config = compiled(RUNTIME, agent)
    assert "prompt_caching" not in config
    settings = load_settings({"KAGENT_CONFIG_JSON": config})
    assert (settings.prompt_caching, settings.cache_ttl) == (False, "5m")


def test_the_alpha11_bare_agent_config_fails_at_startup():
    # alpha11 sent the bare AgentConfig (and KAGENT_API_URL). Under that controller the
    # TaskStore service does not exist, so the image must refuse to start, not run toolless.
    bare = {"model": {"type": "anthropic", "model": "claude-sonnet-5-5"}, "http_tools": []}
    with pytest.raises(ValueError, match="alpha14 ADKConfig"):
        load_settings(
            {
                "KAGENT_CONFIG_JSON": json.dumps(bare),
                "KAGENT_API_URL": "http://kagent-controller.kagent:8083",
            }
        )


def test_local_defaults():
    settings = load_settings({})
    assert not settings.under_kagent
    assert (settings.agent_name, settings.namespace) == ("docs-checker", "kagent")
    assert settings.a2a_port == 80
    assert settings.recursion_limit == 80  # never LangGraph's 10007 default
    assert settings.node_models["intake"].model == "claude-haiku-5-5"
    assert settings.node_models["judge_escalate"].model == "claude-sonnet-5-5"
    assert settings.data_dir == "/data/docs-checker"
    assert settings.checkpoint_db == "/data/docs-checker/checkpoints.sqlite"


def test_node_models_are_overridable_by_literal_env():
    settings = load_settings(
        {"DOCS_CHECKER_JUDGE_MODEL": "claude-sonnet-5-5", "DOCS_CHECKER_JUDGE_EFFORT": "high"}
    )
    assert (settings.node_models["judge"].model, settings.node_models["judge"].effort) == (
        "claude-sonnet-5-5",
        "high",
    )


def test_an_unknown_rate_card_fails_at_startup_instead_of_pricing_silently():
    with pytest.raises(ValueError, match="unknown DOCS_CHECKER_RATE_CARD"):
        load_settings({"DOCS_CHECKER_RATE_CARD": "anthropic-1999-01-01"})


def test_the_repository_setting_must_be_owner_slash_name():
    assert load_settings({"DOCS_CHECKER_REPO": "arigsela/kubernetes"}).repo == "arigsela/kubernetes"
    with pytest.raises(ValueError, match="owner/name"):
        load_settings({"DOCS_CHECKER_REPO": "kubernetes"})
