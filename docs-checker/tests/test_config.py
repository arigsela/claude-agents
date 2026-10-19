import json

from docs_checker.config import load_settings

ALPHA11_CONFIG = {
    "model": {
        "type": "anthropic",
        "model": "claude-sonnet-5-5",
        "prompt_caching": True,
        "cache_ttl": "5m",
    },
    "description": "docs-checker",
    "instruction": "",
    "http_tools": [
        {
            "params": {"url": "http://agent-docs-mcp.kagent:3000/mcp", "headers": {}},
            "tools": ["search_code", "get_file_contents"],
        },
        {
            "params": {
                "url": "http://backstage.backstage.svc.cluster.local/api/mcp-actions/v1/catalog",
                "headers": {"Authorization": "__KAGENT_ENV[KAGENT_CREDENTIAL_ABC123]__"},
            },
            "tools": ["get-catalog-entity"],
        },
    ],
    "session_db_url": "sqlite+aiosqlite:////data/sessions.db",
}


def test_alpha11_config_and_env():
    env = {
        "KAGENT_CONFIG_JSON": json.dumps(ALPHA11_CONFIG),
        "KAGENT_API_URL": "http://kagent-controller.kagent:8083",
        "KAGENT_PORT": "80",
        "KAGENT_CREDENTIAL_ABC123": "kagent-credential-injected",
    }
    settings = load_settings(env)
    assert settings.under_kagent
    assert (settings.a2a_port, settings.ready_port) == (80, 8081)
    assert settings.template_model == "claude-sonnet-5-5"
    docs, catalog = settings.mcp_servers
    assert docs.name == "agent-docs-mcp"
    assert docs.tools == ("get_file_contents", "search_code")  # sorted
    # Secret-backed headers carry only the placeholder; the egress gateway injects the value.
    assert catalog.headers == {"Authorization": "kagent-credential-injected"}


def test_alpha14_wrapped_config():
    env = {
        "KAGENT_CONFIG_JSON": json.dumps(
            {
                "runtime": {
                    "control_plane_url": "http://kagent-controller.kagent:8083",
                    "name": "docs-checker",
                    "namespace": "kagent",
                    "port": 80,
                },
                "agent": ALPHA11_CONFIG,
            }
        )
    }
    settings = load_settings(env)
    assert settings.kagent_api_url == "http://kagent-controller.kagent:8083"
    assert len(settings.mcp_servers) == 2


def test_local_defaults():
    settings = load_settings({})
    assert not settings.under_kagent
    assert settings.a2a_port == 80
    assert settings.recursion_limit == 12  # never LangGraph's 10007 default
    assert settings.node_models["router"].model == "claude-haiku-5-5"
    assert settings.node_models["planner"].model == "claude-sonnet-5-5"


def test_node_models_are_overridable_by_literal_env():
    settings = load_settings(
        {"DOCS_CHECKER_PLANNER_MODEL": "claude-opus-5-5", "DOCS_CHECKER_PLANNER_EFFORT": "high"}
    )
    assert (settings.node_models["planner"].model, settings.node_models["planner"].effort) == (
        "claude-opus-5-5",
        "high",
    )


def test_an_unknown_rate_card_fails_at_startup_instead_of_pricing_silently():
    import pytest

    with pytest.raises(ValueError, match="unknown DOCS_CHECKER_RATE_CARD"):
        load_settings({"DOCS_CHECKER_RATE_CARD": "anthropic-1999-01-01"})


def test_the_repository_setting_must_be_owner_slash_name():
    import pytest

    assert load_settings({"DOCS_CHECKER_REPO": "arigsela/kubernetes"}).repo == "arigsela/kubernetes"
    with pytest.raises(ValueError, match="owner/name"):
        load_settings({"DOCS_CHECKER_REPO": "kubernetes"})
