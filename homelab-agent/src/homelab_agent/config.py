"""Environment-driven configuration.

This module is the ENTIRE env contract between this container and the
kagent BYO Agent CR that will deploy it (see README table). Cluster URLs
appear here only as defaults so local runs and tests can override them.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    model_name: str
    router_model_name: str
    agent_docs_mcp_url: str
    agent_docs_mcp_auth_header: str
    backstage_mcp_url: str
    backstage_mcp_token: str
    k8s_reader_a2a_url: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            model_name=os.getenv("MODEL_NAME", "claude-sonnet-4-6"),
            router_model_name=os.getenv("ROUTER_MODEL_NAME", "claude-haiku-4-5-20251001"),
            agent_docs_mcp_url=os.getenv(
                "AGENT_DOCS_MCP_URL", "http://agent-docs-mcp.kagent:3000/mcp"
            ),
            agent_docs_mcp_auth_header=os.getenv("AGENT_DOCS_MCP_AUTH_HEADER", ""),
            backstage_mcp_url=os.getenv(
                "BACKSTAGE_MCP_URL",
                "http://backstage.backstage.svc.cluster.local/api/mcp-actions/v1/catalog",
            ),
            backstage_mcp_token=os.getenv("BACKSTAGE_MCP_TOKEN", ""),
            k8s_reader_a2a_url=os.getenv(
                "K8S_READER_A2A_URL", "http://k8s-reader.kagent.svc.cluster.local:8080"
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


settings = Settings.from_env()
