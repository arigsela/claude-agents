# homelab-agent

LangGraph BYO re-implementation of the `homelab-knowledge` kagent agent.
Serves the A2A protocol on :8080. See `LEARNING.md` for the LangGraph
concept glossary and `docs/superpowers/plans/2026-07-16-langraph-knowledge-agent-plan.md`
for the design.

## Env contract (what the kagent BYO `Agent` CR must provide)

| Env var | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | yes (runtime) | — | ChatAnthropic auth (own Vault key, not shared `kagent-anthropic`) |
| `MODEL_NAME` | no | `claude-sonnet-4-6` | Main graph model (parity with current agent) |
| `ROUTER_MODEL_NAME` | no | `claude-haiku-4-5-20251001` | Cheap model for the orient fallback classifier |
| `AGENT_DOCS_MCP_URL` | no | `http://agent-docs-mcp.kagent:3000/mcp` | Read-only GitHub MCP (streamable HTTP) |
| `AGENT_DOCS_MCP_AUTH_HEADER` | no | `` | Optional `Authorization` header value for agent-docs MCP |
| `BACKSTAGE_MCP_URL` | no | `http://backstage.backstage.svc.cluster.local/api/mcp-actions/v1/catalog` | Backstage catalog MCP (streamable HTTP) |
| `BACKSTAGE_MCP_TOKEN` | yes (runtime) | `` | Bearer token for the Backstage MCP |
| `K8S_READER_A2A_URL` | no | `http://k8s-reader.kagent.svc.cluster.local:8080` | A2A endpoint of the read-only k8s-reader agent |
| `LOG_LEVEL` | no | `INFO` | Python log level |
| `AGENT_URL` | no | `http://0.0.0.0:8080` | Self-URL advertised in the A2A agent card |

`KAGENT_URL` / kagent runtime envs are injected by the kagent controller into
BYO pods and enable the checkpointer (see `checkpointer.py`); absent locally,
the graph runs without persistence.

## Pinned environment

| Package | Installed version | Notes |
|---|---|---|
| `kagent-langgraph` | 0.9.11 | Provides `KAgentCheckpointer`. Its `__init__.py` unconditionally imports `kagent.langgraph._a2a`, which needs `a2a.server.apps.A2AStarletteApplication` — present in a2a-sdk 0.3.x, removed in a2a-sdk 1.x (this project resolves to `a2a-sdk` 1.1.1). As a result `from kagent.langgraph import KAgentCheckpointer` currently raises `ModuleNotFoundError` in this environment; `checkpointer.get_checkpointer()` catches that and degrades to `None` with a logged warning (see `# TODO(deploy-follow-up)` in `checkpointer.py`). `kagent-core` 0.9.11 (a transitive dependency) additionally requires the unrelated `openai` package to import, due to an unconditional otel auto-instrumentor import. |

## Local dev

    python3 -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    pytest tests/ -v

## Run the server locally

    ANTHROPIC_API_KEY=... uvicorn homelab_agent.server:app --host 0.0.0.0 --port 8080

## Parity harness

    OLD_AGENT_URL=http://localhost:18080 NEW_AGENT_URL=http://localhost:8080 \
      python scripts/parity_check.py
