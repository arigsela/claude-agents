# K8s Monitoring Agent

Multi-agent monitoring system for Kubernetes clusters using Claude Agent SDK with long-context trend detection.

## Key Features

- **Multi-Agent Architecture** - 4 specialized subagents (analyzer, escalation, slack, github)
- **Long-Context Monitoring** - Persistent conversation history with trend detection
- **Smart Pruning** - Automatic context management at 120k token limit
- **Cost Optimized** - All agents use Haiku 4.5 (~$0.90-$1.50/year)
- **GitOps Ready** - Docker and Kubernetes deployment support

## Quick Start

```bash
# Setup
pip install -r requirements.txt
cp .env.example .env
# Edit .env with: ANTHROPIC_API_KEY, KUBECONFIG, SLACK_BOT_TOKEN

# Run single cycle
./run_once.sh

# Run continuous monitoring
./start.sh

# Debug mode
./run_debug.sh
```

## Architecture

```
.claude/
├── CLAUDE.md                    # Cluster context (service catalog)
└── agents/
    ├── k8s-analyzer.md          # Health inspector
    ├── escalation-manager.md    # Severity assessor
    ├── slack-notifier.md        # Alert dispatcher
    └── github-reviewer.md       # Deployment correlator

src/
├── main.py                      # Entry point
├── orchestrator/
│   ├── persistent_monitor.py    # Long-context mode
│   └── stateless_monitor.py     # Cost-optimized mode
├── sessions/
│   └── session_manager.py       # Context persistence
└── models/
    └── findings.py              # Data models
```

## Monitoring Workflow

1. **k8s-analyzer** - Check cluster health, inspect pods/deployments/events
2. **github-reviewer** - Correlate issues with recent deployments (if issues found)
3. **escalation-manager** - Assess severity using service criticality tiers
4. **slack-notifier** - Send alerts for SEV-1/SEV-2 issues

## Long-Context Mode

Enable persistent session tracking for trend detection:

```bash
ENABLE_LONG_CONTEXT=true
MAX_CONTEXT_TOKENS=120000
```

Detects patterns across monitoring cycles:
- Escalation trends (5 → 13 → 56 issues)
- Recovery patterns
- Recurring issues

## Service Criticality

| Tier | Services | Max Downtime |
|------|----------|--------------|
| P0 | Customer-facing apps, databases | 0 minutes |
| P1 | Infrastructure (vault, cert-manager) | 5-15 minutes |
| P2-P3 | Support services | Hours to days |

## Deployment

### Docker

```bash
docker-compose up -d
docker-compose logs -f k8s-monitor
```

### Kubernetes

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/deployment.yaml
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
KUBECONFIG=/path/to/kubeconfig
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL=C01234567

# Optional
GITHUB_TOKEN=ghp_...
MONITORING_INTERVAL_HOURS=1
ENABLE_LONG_CONTEXT=true
```

## Testing

```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=html
```

## License

MIT
