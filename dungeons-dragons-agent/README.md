# dungeons-dragons-agent

Dungeons And Dragons agent that will handle knowledge related to dungeons and dragons 5e

## Architecture

This is a CrewAI multi-agent project with two services:

- **Orchestrator** (port 8000): FastAPI web server that receives queries, classifies them
  via keyword matching, and routes to sub-agents using the A2A (Agent-to-Agent) protocol
- **Character Creation Agent** (port 8080): CrewAI agent that processes domain-specific
  queries using tools, knowledge sources, and an Anthropic LLM

```
                    ┌─────────────────────────────────┐
  HTTP request      │       Orchestrator (FastAPI)     │
  POST /invoke ───▶ │  classify ─▶ route ─▶ delegate  │
                    │         │              │         │
                    └─────────┼──────────────┼─────────┘
                              │              │
                      no_match│              │ sub_agent (A2A)
                              ▼              ▼
                    "I can't help       ┌──────────────┐
                     with that"         │  Sub-Agent   │
                                        │  (CrewAI)    │
                                        │  tools +     │
                                        │  knowledge   │
                                        └──────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- An Anthropic API key (`ANTHROPIC_API_KEY`)

### Local Development

```bash
# 1. Copy environment file and fill in your API key
cp .env.example .env

# 2. Start services with Docker Compose
docker-compose up --build

# 3. Test the orchestrator health endpoint
curl http://localhost:8000/health

# 4. Send a test query
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"query": "Hello, what can you help me with?"}'
```

### Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## API Reference

The orchestrator exposes three endpoints. Visit `/docs` for interactive Swagger UI.

### `GET /health`

Health check for K8s liveness/readiness probes.

```bash
curl http://localhost:8000/health
# {"status": "healthy", "service": "dungeons-dragons-agent"}
```

### `GET /info`

Returns metadata about the orchestrator, configured sub-agents, and routing keywords.

```bash
curl http://localhost:8000/info
# {"service": "...", "role": "orchestrator", "sub_agents": [...]}
```

### `POST /invoke`

Main query endpoint. Sends a query through the orchestrator flow (classify, route, delegate).

```bash
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"query": "your question here"}'
# {"result": "...", "route": "sub_agent"}
```

**Note:** AI agent queries can take 30-120+ seconds due to LLM inference, tool calls, and
chain-of-thought reasoning. The K8s ingress is configured with 300s timeouts to accommodate this.

## Interacting with the Agent

### From inside the cluster

```bash
# Direct service call (other pods in the same namespace)
curl -X POST http://dungeons-dragons-agent-orchestrator/invoke \
  -H "Content-Type: application/json" \
  -d '{"query": "your question"}'

# From a different namespace
curl -X POST http://dungeons-dragons-agent-orchestrator.oncall-crewai.svc:80/invoke \
  -H "Content-Type: application/json" \
  -d '{"query": "your question"}'
```

### Via kubectl port-forward (quickest for testing)

```bash
# Terminal 1: Forward the orchestrator port to localhost
kubectl port-forward svc/dungeons-dragons-agent-orchestrator 8000:80 -n oncall-crewai

# Terminal 2: Send queries
curl -X POST http://localhost:8000/invoke \
  -H "Content-Type: application/json" \
  -d '{"query": "your question"}'
```

### Via ingress (if domain is configured)

No domain was configured during scaffolding. To expose the orchestrator externally, create
an Ingress resource pointing to the `dungeons-dragons-agent-orchestrator` service on port 80.
See the existing agents' ingress manifests for a reference configuration with TLS,
IP whitelisting, and extended timeouts.

## Deployment

### Docker Image Builds

Docker images are built by GitHub Actions, triggered automatically by the Backstage
scaffolder via `workflow_dispatch`. The workflow:

1. Checks out the PR branch from `arigsela/claude-agents`
2. Builds `dungeons-dragons-agent-orchestrator` and `dungeons-dragons-agent-character-creation-agent` images
3. Pushes to ECR with version tag + `latest`

To rebuild manually:

```bash
# Via GitHub Actions (preferred — no Docker daemon needed locally)
gh workflow run build-agent-images.yaml \
  -R arigsela/claude-agents \
  -r main \
  -f project-name=dungeons-dragons-agent \
  -f sub-agent-name=character-creation-agent \
  -f version=1.0.1 \
  -f branch=main

# Or locally with the deploy script (requires Docker + AWS creds)
./deploy-to-ecr.sh --version 1.0.1
```

### Kubernetes Deployment

K8s manifests are managed in the [arigsela/kubernetes](https://github.com/arigsela/kubernetes)
GitOps repo under `base-apps/oncall-crewai/dungeons-dragons-agent/`. The Backstage
template creates a PR there automatically. Resources are synced by the existing
**oncall-crewai** ArgoCD Application — no separate ArgoCD app is created.

**Automated by the Backstage scaffolder:**
- ECR repositories (`dungeons-dragons-agent-orchestrator` and `dungeons-dragons-agent-character-creation-agent`) are created automatically
- Docker images are built via GitHub Actions workflow dispatch
- Vault policy, K8s auth role, and placeholder secrets are provisioned automatically

**Post-merge steps** (after the K8s PR is merged):

1. Replace placeholder Vault secrets with real values at path `k8s-secrets/data/dungeons-dragons-agent`
2. ArgoCD will auto-deploy once manifests are in the `main` branch

### Required Vault Secrets

| Key | Description |
|-----|-------------|
| `anthropic-api-key` | Anthropic API key for CrewAI LLM calls |
| `api-keys` | Comma-separated API keys for inter-service A2A auth |

## Customizing Your Agent

### Modifying Routing Keywords

The orchestrator uses keyword matching to decide which queries route to the sub-agent.
Queries that don't match any keyword get a fallback response explaining what topics
the agent handles.

Edit `src/orchestrator/prompts.py` to update the `ROUTING_KEYWORDS` list, or set
the `ROUTING_KEYWORDS` environment variable (comma-separated) at runtime. Include
common variations and abbreviations to avoid missed matches — for example, both
`"dnd"` and `"d&d"` for Dungeons & Dragons.

### Adding Knowledge Sources (RAG)

Place files in `config/knowledge/` to give your agent domain-specific context:

- `.txt` files for architecture docs, runbooks, and guides
- `.json` files for API specs and structured data
- `.csv` files for tabular data (service catalogs, metrics)
- `.pdf` files for design docs and RFCs


**RAG is disabled.** The `search_knowledge` tool performs keyword-based file search
against `.txt` and `.json` files in `config/knowledge/`. This is useful but does
not include vector-based semantic search.

To enable full RAG with vector embeddings, re-scaffold this project with
`enableKnowledge: true` in the Backstage template. This will:
- Auto-discover and embed knowledge files using CrewAI's RAG system
- Add OpenAI embeddings configuration (required since Anthropic has no embeddings API)
- Add `OPENAI_API_KEY` to the K8s secrets and docker-compose environment


Rebuild with `docker-compose up --build` to include new knowledge files.

### Customizing Tools

Edit `src/character_creation_agent/tools.py` to add domain-specific tools.
Each tool is a Python function decorated with `@tool` from CrewAI:

```python
from crewai.tools import tool

@tool("my_custom_tool")
def my_custom_tool(query: str) -> str:
    """Description of what this tool does — the LLM reads this to decide when to call it."""
    # Your implementation here
    return json.dumps({"result": "..."})
```

Tools must return strings (the LLM reads the return value as text). Handle errors
gracefully by returning error messages instead of raising exceptions.

## Adding More Sub-Agents

1. Create a new directory under `src/` following the pattern of `src/character_creation_agent/`
2. Add a Dockerfile in `docker/`
3. Add K8s manifests in the [arigsela/kubernetes](https://github.com/arigsela/kubernetes) repo under `base-apps/oncall-crewai/dungeons-dragons-agent/`
4. Update the orchestrator's routing keywords and agent factories in `src/orchestrator/`

## Known Constraints

### CrewAI 1.6.x Pin

This project pins `crewai==1.6.1`. Versions 1.10+ add LanceDB as the default memory
backend, and LanceDB's Rust binaries require AVX2 CPU instructions. Older CPUs
(e.g. Intel E5-2670 Sandy Bridge) only support AVX, causing SIGILL (exit code 132)
on `Flow()` instantiation. Stay on 1.6.x unless your cluster nodes have AVX2.

### Reasoning and Planning Require OpenAI

CrewAI's `reasoning=True` and `planning=True` options use OpenAI internally, even
when the main LLM is Anthropic. These are disabled by default. To enable them:

1. Set `OPENAI_API_KEY` in your environment
2. Uncomment `reasoning=True` in `src/character_creation_agent/agent.py`
3. Uncomment `planning=True` in the Crew constructor

### Import Paths (CrewAI 1.6.x)

CrewAI 1.6.x uses different import paths than newer versions:

```python
from crewai.tools import tool        # NOT: from crewai import tool
from crewai.a2a import A2AConfig     # NOT: from crewai.agent import A2AConfig
from crewai.a2a.auth import APIKeyAuth
from crewai.llm import LLM           # NOT: from crewai import LLM
```

### Nested Event Loop

The orchestrator's `/invoke` endpoint is intentionally a sync function (`def`, not
`async def`). CrewAI's `Flow.kickoff()` calls `asyncio.run()` internally, which
cannot run inside uvicorn's event loop. FastAPI automatically runs sync functions
in a thread pool, giving each invocation its own event loop. The flow's
`handle_sub_agent` method uses `concurrent.futures.ThreadPoolExecutor` for the
same reason — `crew.kickoff()` also calls `asyncio.run()`.

## Project Structure

```
dungeons-dragons-agent/
├── src/
│   ├── shared/                        # Common utilities (config, logging, models, observability)
│   ├── orchestrator/                  # FastAPI app + CrewAI Flow (classify → route → delegate)
│   │   ├── main.py                    # FastAPI endpoints (/health, /info, /invoke)
│   │   ├── flow.py                    # OrchestratorFlow (keyword routing state machine)
│   │   ├── agents.py                  # A2A delegate agent creation
│   │   └── prompts.py                 # Routing keywords and fallback messages
│   └── character_creation_agent/  # Sub-agent with tools and knowledge
│       ├── agent.py                   # CrewAI Agent + Crew creation and invocation
│       ├── tools.py                   # @tool-decorated functions (search, health, etc.)
│       ├── prompts.py                 # Agent role, goal, backstory, task template
│       ├── server.py                  # A2A server (receives delegated queries)
│       ├── executor.py                # A2A executor (bridges A2A → agent.invoke())
│       └── config/                    # YAML config for agents and tasks
├── docker/                            # Dockerfiles per service
├── config/knowledge/                  # Knowledge files for RAG / keyword search
├── tests/                             # Unit and integration tests
├── docker-compose.yml                 # Local development stack
├── requirements.txt                   # Python dependencies (crewai pinned to 1.6.1)
└── .env.example                       # Environment variable template
```
