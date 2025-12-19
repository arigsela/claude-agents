# AI Agent Portfolio

Production-ready AI agents demonstrating **Claude AI integration patterns** for DevOps automation.

---

## Projects & Skills Demonstrated

### K8s Monitoring Agent ⭐⭐⭐
> Multi-agent system with long-context trend detection

**What I Built**: Autonomous Kubernetes monitoring system using 4 specialized AI agents that coordinate to analyze cluster health, correlate issues with deployments, assess severity, and dispatch alerts.

| Skill | Implementation |
|-------|----------------|
| **Multi-Agent Orchestration** | 4 subagents (analyzer, escalation, slack, github) with task delegation |
| **Long-Context Management** | 120k token sessions with smart pruning to preserve critical findings |
| **Session Persistence** | JSON-based state management across monitoring cycles |
| **Cost Optimization** | Haiku model selection achieving ~$0.90-$1.50/year operational cost |
| **Service Tier Modeling** | P0/P1/P2 criticality classification with max downtime thresholds |

**Technologies**: `Claude Agent SDK` `Python` `Kubernetes` `Slack API` `GitHub API`

```
k8s-monitor/
├── .claude/agents/      # 4 subagent definitions
├── src/orchestrator/    # Long-context session management
└── src/models/          # Structured findings with Pydantic
```

---

### OnCall Troubleshooting API ⭐⭐⭐
> HTTP API with 18 custom tools for incident response

**What I Built**: FastAPI server exposing Claude-powered troubleshooting via RESTful endpoints. Integrates with n8n workflows for interactive incident response with service catalog awareness.

| Skill | Implementation |
|-------|----------------|
| **FastAPI Development** | 8 endpoints with Swagger UI, Pydantic validation |
| **Custom Tool Development** | 18 tools: Kubernetes, GitHub, AWS, Datadog integrations |
| **API Security** | Key authentication, rate limiting (60/30/10 req/min tiers), CORS |
| **Session Management** | Multi-turn conversations with 30-min TTL, automatic cleanup |
| **Service Catalog Design** | Priority classification, dependency mapping, known issues database |

**Technologies**: `Anthropic API` `FastAPI` `Kubernetes Python Client` `PyGithub` `Boto3` `Datadog API`

```
oncall/
├── src/api/
│   ├── api_server.py      # 8 RESTful endpoints
│   ├── custom_tools.py    # 18 tool implementations
│   ├── session_manager.py # Conversation state management
│   └── middleware.py      # Auth & rate limiting
└── config/
    └── service_mapping.yaml  # Service catalog
```

---

### RAG MCP Server ⭐⭐
> Vector search with dual backend support

**What I Built**: Custom MCP server providing semantic search capabilities with abstracted vector storage. Supports both Qdrant (local dev) and PostgreSQL+pgvector (production/RDS).

| Skill | Implementation |
|-------|----------------|
| **MCP Protocol** | Server implementation with stdio/SSE transport |
| **Vector Database Architecture** | Factory pattern abstracting Qdrant vs pgvector backends |
| **Semantic Search** | FastEmbed integration (BAAI/bge-small-en) for local embeddings |
| **Content Deduplication** | Hash-based duplicate detection on storage |

**Technologies**: `MCP Protocol` `Qdrant` `PostgreSQL pgvector` `FastEmbed` `Docker`

```
rag-mcp-server/
├── src/vectorstore/
│   ├── base.py            # Abstract interface
│   ├── qdrant_store.py    # Qdrant implementation
│   ├── pgvector_store.py  # PostgreSQL implementation
│   └── factory.py         # Backend selection
└── k8s/                   # Kubernetes manifests
```

---

### YouTube MCP Server ⭐
> Transcript extraction and summarization

**What I Built**: Simple MCP server for YouTube video analysis - fetches transcripts, extracts metadata, and persists summaries as Markdown files.

| Skill | Implementation |
|-------|----------------|
| **MCP Protocol** | Basic server with 5 tools |
| **YouTube Integration** | Transcript extraction with language support |
| **Document Persistence** | Markdown output with YAML frontmatter |

**Technologies**: `MCP Protocol` `YouTube Transcript API` `uv`

---

## Architecture Patterns Demonstrated

| Pattern | K8s Monitor | OnCall API | RAG Server |
|---------|:-----------:|:----------:|:----------:|
| Multi-Agent Orchestration | ✅ | - | - |
| Long-Context Sessions | ✅ | - | - |
| HTTP API Design | - | ✅ | ✅ |
| Custom Tool Development | ✅ | ✅ | ✅ |
| MCP Protocol | - | - | ✅ |
| Vector Search | - | - | ✅ |
| Rate Limiting | - | ✅ | - |
| Service Catalog | ✅ | ✅ | - |

---

## Quick Start

```bash
# K8s Monitor - Continuous monitoring with trend detection
cd k8s-monitor && pip install -r requirements.txt && ./start.sh

# OnCall API - HTTP endpoints for n8n integration
cd oncall && pip install -r requirements.txt && ./run_api_server.sh

# RAG Server - Semantic search MCP server
cd rag-mcp-server && docker compose up -d
```

---

## Tech Stack

**AI/ML**: Claude Agent SDK, Anthropic API, FastEmbed, Vector Databases

**Backend**: Python 3.11+, FastAPI, Pydantic, AsyncIO

**Infrastructure**: Kubernetes, Docker, PostgreSQL, Qdrant

**Integrations**: Slack, GitHub, AWS (Secrets Manager, ECR), Datadog

**Protocols**: MCP (Model Context Protocol), REST, SSE

---

MIT License
