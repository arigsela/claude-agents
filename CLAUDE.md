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
| **pr-triage/** | GitHub composite action + Anthropic API + Jev | Labels PRs review:skip/skim/read from policy rules; calibration CLI |
| **skills/pr-explainer/**, **skills/review-retro/** | Claude Code plugin skills | GitOps PR explainer (Artifact); retro of /code-review sessions |

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

# PR Triage (needs TYPESAFE_API_KEY and ANTHROPIC_API_KEY)
uv run --project pr-triage python -m pr_triage features --repo arigsela/kubernetes --pr 650
uv run --project pr-triage python -m pr_triage run --repo arigsela/kubernetes --pr 650 --dry-run
uv run --project pr-triage python -m pr_triage calibrate --repo arigsela/kubernetes --limit 200 --out pr-triage/calibration/<name>.md

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

5. **Risk-Based PR Triage** (pr-triage, pr-explainer, review-retro)
   - Deterministic policy rules first, then Jev for a calibrated decision, then Claude only when Jev is unsure
   - The policy is read at the PR's base commit; every failure falls back to `review:read`
   - Skills produce grounded facts with scripts; the model only writes text that is verified before use
   - The workflow in arigsela/kubernetes pins the action by commit SHA, so bump it after changing `pr-triage/`

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
- `pr-triage/calibration/*.md` - Triage calibration reports (re-run after changing thresholds, questions or the Jev model)
- `docs/superpowers/specs/2026-09-30-pr-review-toolkit-design.md` - PR review toolkit design, with its plan under `docs/superpowers/plans/`
