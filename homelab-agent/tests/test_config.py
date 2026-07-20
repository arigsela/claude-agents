"""Config is the env contract: everything external is injectable via env."""

from homelab_agent.config import Settings


def test_defaults_point_at_cluster_services(monkeypatch):
    # Clear any ambient env so we test the defaults themselves.
    for var in (
        "MODEL_NAME", "ROUTER_MODEL_NAME", "AGENT_DOCS_MCP_URL",
        "AGENT_DOCS_MCP_AUTH_HEADER", "BACKSTAGE_MCP_URL",
        "BACKSTAGE_MCP_TOKEN", "K8S_READER_A2A_URL", "LOG_LEVEL",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert s.model_name == "claude-sonnet-4-6"
    assert s.router_model_name == "claude-haiku-4-5-20251001"
    assert s.agent_docs_mcp_url == "http://agent-docs-mcp.kagent:3000/mcp"
    assert s.backstage_mcp_url == (
        "http://backstage.backstage.svc.cluster.local/api/mcp-actions/v1/catalog"
    )
    assert s.k8s_reader_a2a_url == "http://k8s-reader.kagent.svc.cluster.local:8080"
    assert s.agent_docs_mcp_auth_header == ""
    assert s.backstage_mcp_token == ""
    assert s.log_level == "INFO"


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "claude-sonnet-5")
    monkeypatch.setenv("K8S_READER_A2A_URL", "http://localhost:9999")
    monkeypatch.setenv("BACKSTAGE_MCP_TOKEN", "sekrit")
    s = Settings.from_env()
    assert s.model_name == "claude-sonnet-5"
    assert s.k8s_reader_a2a_url == "http://localhost:9999"
    assert s.backstage_mcp_token == "sekrit"


def test_memory_defaults(monkeypatch):
    for var in (
        "MEMORY_DB_URL", "OLLAMA_BASE_URL", "EMBEDDING_MODEL",
        "MEMORY_TOP_K", "MEMORY_NAMESPACE", "MEMORY_SIMILARITY_FLOOR",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert s.memory_db_url == ""
    assert s.ollama_base_url == "http://ollama.ollama.svc.cluster.local:11434"
    assert s.embedding_model == "nomic-embed-text"
    assert s.memory_top_k == 3
    assert s.memory_namespace == "homelab-agent"
    assert s.memory_similarity_floor == 0.3


def test_memory_env_overrides(monkeypatch):
    monkeypatch.setenv("MEMORY_DB_URL", "postgresql://u:p@db:5432/kagent")
    monkeypatch.setenv("MEMORY_TOP_K", "5")
    monkeypatch.setenv("MEMORY_SIMILARITY_FLOOR", "0.55")
    s = Settings.from_env()
    assert s.memory_db_url == "postgresql://u:p@db:5432/kagent"
    assert s.memory_top_k == 5
    assert s.memory_similarity_floor == 0.55
