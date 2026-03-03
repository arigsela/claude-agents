# chores-tracker-agent

AI agent specialized in the Chores Tracker application with RAG knowledge support

## Architecture

This is a CrewAI multi-agent project with:

- **Orchestrator** (port 8000): Routes queries to sub-agents via A2A protocol
- **Chores Tracker Knowledge Specialist** (port 8080): Answer questions about the Chores Tracker app architecture, API, deployment, and troubleshooting using knowledge sources and tools.

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- An Anthropic API key (`ANTHROPIC_API_KEY`)

### Local Development

```bash
# 1. Copy environment file and fill in your values
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

## Deployment

### Build & Push Images

```bash
# Build and push to ECR (requires AWS credentials)
./deploy-to-ecr.sh --version 1.0.0
```

### Kubernetes Deployment

K8s manifests are managed in the [arigsela/kubernetes](https://github.com/arigsela/kubernetes)
GitOps repo. The Backstage template creates a PR there automatically.

**Automated by the Backstage scaffolder:**
- ECR repositories (`chores-tracker-agent-orchestrator` and `chores-tracker-agent-knowledge-agent`) are created automatically
- Docker images are built and pushed to ECR during scaffolding

**Post-merge steps** (after the K8s PR is merged):

1. Create Vault role and secrets at path `k8s-secrets/data/chores-tracker-agent`
2. ArgoCD will auto-deploy once manifests are in the `main` branch

### Required Vault Secrets

| Key | Description |
|-----|-------------|
| `anthropic-api-key` | Anthropic API key for CrewAI LLM calls |
| `api-keys` | Comma-separated API keys for inter-service A2A auth |
| `openai-api-key` | OpenAI API key for RAG vector embeddings |

## Customizing Your Agent

### Adding Knowledge Sources (RAG)

Place files in `config/knowledge/` to give your agent domain-specific context:

- `.txt` files for architecture docs, runbooks, and guides
- `.json` files for API specs and structured data
- `.csv` files for tabular data (service catalogs, metrics)
- `.pdf` files for design docs and RFCs


**RAG is enabled.** Knowledge files are automatically discovered, chunked, and
embedded at startup using CrewAI's built-in RAG system. The agent's context is
enriched with relevant chunks during execution — no code changes needed.

**Requirements:**
- Set `OPENAI_API_KEY` in your `.env` file (or Vault for production)
- OpenAI embeddings are used because Anthropic does not provide an embeddings API
- The `search_knowledge` tool also provides keyword-based file search as a complement to RAG

**How it works:**
1. `src/shared/knowledge.py` scans `config/knowledge/` for supported files
2. Files are wrapped in CrewAI `KnowledgeSource` objects (TextFile, JSON, CSV, PDF)
3. `agent.py` passes these to `Agent(knowledge_sources=..., embedder=...)`
4. CrewAI chunks, embeds, and indexes the content automatically
5. During execution, relevant chunks are injected into the agent's context


Rebuild with `docker-compose up --build` to include new knowledge files.

### Customizing Tools

Edit `src/knowledge-agent/tools.py` to add domain-specific tools.
Each tool is a Python function decorated with `@tool` from CrewAI:

```python
from crewai.tools import tool

@tool("my_custom_tool")
def my_custom_tool(query: str) -> str:
    """Description of what this tool does."""
    # Your implementation here
    return json.dumps({"result": "..."})
```

### Modifying Routing Keywords

Edit `src/orchestrator/prompts.py` or update the `ROUTING_KEYWORDS` environment
variable to change which queries route to your sub-agent.

## Adding More Sub-Agents

1. Create a new directory under `src/` following the pattern of `src/knowledge-agent/`
2. Add a Dockerfile in `docker/`
3. Add K8s manifests in the [arigsela/kubernetes](https://github.com/arigsela/kubernetes) repo under `base-apps/chores-tracker-agent/`
4. Update the orchestrator's routing keywords and agent factories in `src/orchestrator/`

## Project Structure

```
chores-tracker-agent/
├── src/
│   ├── shared/          # Common utilities (config, logging, models)
│   ├── orchestrator/    # Query router + A2A delegation
│   └── knowledge-agent/  # Sub-agent with tools and knowledge
├── docker/              # Dockerfiles per service
├── config/              # Configuration files (knowledge sources, etc.)
└── tests/               # Unit and integration tests
```
