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
| `kagent-langgraph` | 0.9.11 | Provides `KAgentCheckpointer` (`checkpointer.get_checkpointer()`). |
| `kagent-core` | 0.9.11 | Transitive dependency of `kagent-langgraph`; provides `KAgentConfig`. |
| `a2a-sdk` | 0.3.26 (pinned `[http-server]>=0.3.10,<0.4`) | Pinned to the 0.3.x line because `kagent.langgraph.__init__` imports `kagent.langgraph._a2a`, which needs `a2a.server.apps.A2AStarletteApplication` — present in a2a-sdk 0.3.x, removed in a2a-sdk 1.x. This also matches production: `oncall-crewai` runs `a2a-sdk==0.3.24` against the same kagent 0.9.11 controller. Nothing in this codebase imports the `a2a` package directly (yet — Task 8's A2A server will), so the downgrade from the initially-resolved 1.1.1 was safe. |
| `openai` | 2.45.0 | **Not used by this project's code.** Pinned solely because `kagent.core.tracing` unconditionally imports an OpenTelemetry auto-instrumentor for the `openai` SDK; without it, `from kagent.core import KAgentConfig` raises `ModuleNotFoundError: No module named 'openai'`. This is an undeclared-dependency wart in kagent-core 0.9.11, not something this project uses directly. |
| container base | `python:3.14-slim` | Matches the dev venv's interpreter (all 50 tests run on 3.14) rather than the `python:3.11-slim` inherited from the oncall-crewai template — `kagent-core`'s otel dependency chain doesn't resolve on 3.11. `requires-python` in `pyproject.toml` stays `>=3.11` (that floor describes the code, not the shipped image). |

With these versions, `from kagent.langgraph import KAgentCheckpointer` and
`from kagent.core import KAgentConfig` import cleanly, and
`checkpointer.get_checkpointer()` returns a real `KAgentCheckpointer` when
`KAGENT_URL`, `KAGENT_NAME`, and `KAGENT_NAMESPACE` are all set (as kagent
injects into BYO pods), else `None`.

## Local dev

    python3 -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    pytest tests/ -v

## Run the server locally

    ANTHROPIC_API_KEY=... uvicorn homelab_agent.server:app --host 0.0.0.0 --port 8080

## Parity harness

    OLD_AGENT_URL=http://localhost:18080 NEW_AGENT_URL=http://localhost:8080 \
      python scripts/parity_check.py

## Container

    docker build -t homelab-agent:dev .
    docker run --rm -p 8080:8080 -e ANTHROPIC_API_KEY=... homelab-agent:dev

## Deploy image to ECR

    ./deploy-to-ecr.sh v0.1.0

Cluster-side deployment (kagent BYO `Agent` CR, ESO secrets, Vault role) is
the follow-up plan in `arigsela/kubernetes` — this repo only produces the
image and documents the env contract above.
