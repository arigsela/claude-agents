# K8s Monitoring Agent

Multi-agent Kubernetes monitoring system with long-context trend detection using Claude Agent SDK.

---

## Skills Demonstrated

| Skill | Implementation |
|-------|----------------|
| **Multi-Agent Orchestration** | 4 specialized subagents coordinating via task delegation |
| **Claude Agent SDK** | Subagent definitions with model selection and tool restrictions |
| **Long-Context Management** | 120k token sessions preserving conversation history across cycles |
| **Smart Pruning** | Automatic context reduction while preserving critical findings |
| **Session Persistence** | JSON-based state save/restore for continuous monitoring |
| **Cost Optimization** | Haiku model selection achieving ~$0.90-$1.50/year operational cost |
| **Service Tier Modeling** | P0/P1/P2 criticality with max downtime thresholds |
| **Trend Detection** | Cross-cycle pattern recognition (escalation trends, recovery patterns) |

---

## Architecture

```
.claude/
├── CLAUDE.md              # Cluster context & service catalog
└── agents/
    ├── k8s-analyzer.md    # Health inspection subagent
    ├── escalation-manager.md  # Severity assessment
    ├── slack-notifier.md  # Alert dispatch
    └── github-reviewer.md # Deployment correlation

src/
├── main.py                # Entry point
├── orchestrator/
│   ├── persistent_monitor.py  # Long-context session management
│   └── monitor.py         # Subagent coordination
├── sessions/
│   └── session_manager.py # State persistence
└── models/
    └── findings.py        # Pydantic data models
```

---

## Subagent Workflow

```
┌─────────────────┐
│  k8s-analyzer   │  Check pods, deployments, events, nodes
└────────┬────────┘
         │ findings
         ▼
┌─────────────────┐
│ github-reviewer │  Correlate with recent deployments (if issues)
└────────┬────────┘
         │ correlation
         ▼
┌─────────────────┐
│escalation-mgr   │  Assess severity using P0/P1/P2 tiers
└────────┬────────┘
         │ severity
         ▼
┌─────────────────┐
│ slack-notifier  │  Dispatch SEV-1/SEV-2 alerts
└─────────────────┘
```

---

## Long-Context Mode

Enable persistent sessions for trend detection across monitoring cycles:

```bash
ENABLE_LONG_CONTEXT=true
MAX_CONTEXT_TOKENS=120000
```

**Capabilities**:
- Track escalation trends (5 → 13 → 56 issues)
- Identify recovery patterns
- Detect recurring issues
- Correlate incidents over time

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Set: ANTHROPIC_API_KEY, KUBECONFIG, SLACK_BOT_TOKEN

# Run single cycle
./run_once.sh

# Run continuous monitoring
./start.sh
```

---

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
KUBECONFIG=/path/to/kubeconfig
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL=C01234567

# Long-Context Settings
ENABLE_LONG_CONTEXT=true
MAX_CONTEXT_TOKENS=120000
MONITORING_INTERVAL_HOURS=1

# Optional
GITHUB_TOKEN=ghp_...
```

---

## Service Criticality Tiers

| Tier | Max Downtime | Examples |
|------|--------------|----------|
| **P0** | 0 minutes | Customer-facing apps, databases |
| **P1** | 5-15 minutes | Infrastructure (vault, cert-manager) |
| **P2-P3** | Hours to days | Support services, monitoring |

---

## Technologies

`Claude Agent SDK` `Python` `Kubernetes` `Slack API` `GitHub API` `Pydantic` `Docker`

---

MIT License
