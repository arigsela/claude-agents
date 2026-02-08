# CLAUDE.md

This file provides guidance for Claude Code when working with this repository.

## Repository Overview

**AI Agent Learning Lab** - A collection of production-ready AI agents demonstrating different Anthropic integration patterns for Kubernetes automation.

## Projects

| Project | Architecture | Key Features |
|---------|--------------|--------------|
| **cluster-scanner/** | Ralph Orchestrator (3 hats) | Scans via oncall-agent-api, severity analysis, Slack alerts |
| **k8s-monitor/** | Multi-Agent + Claude SDK | Long-context monitoring, trend detection, Slack alerts |
| **oncall-agent-api/** | FastAPI + Anthropic API | HTTP API, Slack /oncall, GitOps PRs, incident memory |
| **youtube-mcp/** | MCP Server | YouTube transcript extraction and summarization |

## Quick Commands

```bash
# Cluster Scanner (replaces k8s-monitor)
cd cluster-scanner && ./test-local.sh  # Local test (needs port-forwarded oncall-api)

# K8s Monitor (legacy)
cd k8s-monitor && ./run_once.sh       # Single monitoring cycle
cd k8s-monitor && ./start.sh          # Continuous monitoring

# OnCall Agent API
cd oncall-agent-api && source venv/bin/activate && uvicorn src.api.api_server:app --reload --port 8000
curl http://localhost:8000/docs       # Interactive docs

# Tests
pytest tests/ -v                      # Run tests
```

## Architecture Patterns Demonstrated

1. **Multi-Agent Orchestration** (k8s-monitor)
   - Subagents defined in `.claude/agents/*.md`
   - Long-context session management with smart pruning
   - MCP servers for Kubernetes and Slack

2. **Stateless API** (oncall-agent-api)
   - Direct Anthropic API + custom tools
   - Session-based conversations (30-min TTL)
   - Service catalog embedded in system prompt
   - GitOps PR creation, Slack integration

3. **Ralph Orchestrator** (cluster-scanner)
   - 3-hat event flow: scanner → analyzer → notifier
   - Queries oncall-agent-api instead of direct kubectl
   - Ralph memories for trend detection across cycles

4. **MCP Server Development** (youtube-mcp)
   - Custom MCP server implementations

## Code Quality

```bash
black src/                # Format
ruff check src/           # Lint
pytest tests/ -v          # Test
```

## Key Files

- `*/README.md` - Project documentation
- `*/.claude/agents/*.md` - Subagent definitions
- `*/src/` - Source code
- `*/tests/` - Test suites
