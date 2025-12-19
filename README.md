# Claude Agents Repository

**Learning Lab for AI Agent Integration Patterns**

A collection of production-ready AI agents demonstrating different approaches to building intelligent automation with Anthropic's Claude AI.

## What You'll Learn

This repository showcases different Anthropic integration patterns, helping you understand:

1. **Claude Agent SDK** vs **Direct Anthropic API**
2. **Multi-agent architecture** vs **Single-agent architecture**
3. **MCP (Model Context Protocol)** vs **Direct API libraries**
4. **Tradeoffs**: Flexibility vs simplicity, cost vs capability

---

## Projects

### 🤖 [K8s Monitoring Agent](./k8s-monitor/)

**Architecture**: Multi-Agent + Claude SDK + MCP

Autonomous monitoring agent with persistent memory, specialized subagents, and long-context trend detection.

**Highlights**:
- 4 specialized subagents (analyzer, escalation, slack, github)
- Long-context monitoring with 120k token session management
- Smart pruning preserves critical messages
- Cost-optimized: All Haiku 4.5 (~$0.90-$1.50/year)

```bash
cd k8s-monitor && ./start.sh  # Continuous monitoring
```

---

### 🚨 [OnCall Troubleshooting Agent](./oncall/)

**Architecture**: FastAPI + Direct Anthropic API

HTTP API for Kubernetes troubleshooting with service catalog awareness and n8n integration.

**Highlights**:
- 8 RESTful endpoints with Swagger UI
- 18 custom tools (K8s, GitHub, AWS, Datadog)
- Session-based conversations (30-min TTL)
- Built-in service catalog with priority classification

```bash
cd oncall && ./run_api_server.sh
open http://localhost:8000/docs
```

---

### 📚 [RAG MCP Server](./rag-mcp-server/)

**Architecture**: MCP Server + Vector Database

Custom MCP server for semantic search with Qdrant/pgvector backend.

**Highlights**:
- Dual vector backend support
- Playbook and runbook storage
- Claude-integrated semantic search

---

### 🎬 [YouTube MCP Server](./youtube-mcp/)

**Architecture**: MCP Server

MCP server for YouTube transcript extraction and summarization.

---

## Architecture Comparison

| Aspect | K8s Monitor (Agent SDK) | OnCall (Direct API) |
|--------|------------------------|---------------------|
| **Context Management** | Automatic (persistent) | Manual (sessions) |
| **Tool Access** | MCP Servers | Direct Python libs |
| **Architecture** | Multi-agent | Single-agent |
| **Memory** | Persists across cycles | Stateless per request |
| **Best For** | Autonomous monitoring | HTTP API wrappers |

## When to Use Each Pattern

### Use Claude Agent SDK When:
- Agent needs memory across multiple interactions
- Complex workflows require specialized subagents
- You want MCP integration for structured tool access
- Configuration-driven behavior is preferred

### Use Direct Anthropic API When:
- Stateless analysis with external context management
- Building HTTP APIs for integrations
- Simple, focused tasks
- Performance-critical applications

---

## Quick Start

### K8s Monitor
```bash
cd k8s-monitor
pip install -r requirements.txt
cp .env.example .env
./run_once.sh  # Single cycle
```

### OnCall API
```bash
cd oncall
pip install -r requirements.txt
cp .env.example .env
./run_api_server.sh
```

## Prerequisites

- Python 3.11+
- Anthropic API key
- kubectl with cluster access (for K8s agents)
- Docker (optional, for containerized deployment)

## Repository Structure

```
claude-agents/
├── k8s-monitor/        # Multi-agent monitoring (Claude SDK)
│   ├── .claude/        # Agent definitions
│   └── src/            # Source code
│
├── oncall/             # HTTP API agent (Direct Anthropic)
│   └── src/api/        # FastAPI server
│
├── rag-mcp-server/     # RAG MCP server
├── youtube-mcp/        # YouTube MCP server
│
└── docs/               # Shared documentation
    └── examples/       # Claude SDK tutorials
```

## License

MIT

---

**Built with Claude AI** | Demonstrating AI Agent Patterns for DevOps Automation
