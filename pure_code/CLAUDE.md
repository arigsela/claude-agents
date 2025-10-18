# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains the **Intelligent On-Call Troubleshooting Agent** - a production-ready Kubernetes monitoring system that uses Claude LLM for automated incident analysis and remediation recommendations.

**Key Capabilities**:
- Monitors dev-eks cluster health (pod status, restarts, failures) every 60 seconds
- Analyzes incidents using Claude LLM with two-turn investigation methodology
- Verifies AWS infrastructure (Secrets Manager, ECR images)
- Correlates incidents with GitHub deployment activities
- Sends intelligent remediation via Microsoft Teams notifications

**Architecture**: Direct API integration (kubernetes-python, PyGithub, boto3) with Claude LLM for analysis via Anthropic API, eliminating MCP intermediary overhead.

## Quick Start

```bash
# Navigate to project
cd oncall-agent-poc

# Activate virtual environment
source venv/bin/activate

# Install dependencies (if needed)
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with: ANTHROPIC_API_KEY, GITHUB_TOKEN, AWS credentials

# Run daemon (production mode)
docker compose up
```

## Common Commands

### Running the Agent

**Continuous Monitoring** (production):
```bash
# Docker (recommended)
docker compose up              # Foreground with logs
docker compose up -d           # Background daemon
docker compose logs -f         # Watch logs
docker compose down            # Stop

# Local Python daemon
python3 oncall-agent-poc/src/integrations/orchestrator.py

# Background daemon (macOS)
./oncall-agent-poc/run_daemon.sh start
./oncall-agent-poc/run_daemon.sh logs
./oncall-agent-poc/run_daemon.sh stop
```

**Interactive Query Mode** (development/testing):
```bash
./oncall-agent-poc/run_agent.sh --query "What services are you monitoring?"
python oncall-agent-poc/src/agent/oncall_agent.py --dev
```

### Testing

**Note**: Test infrastructure is configured but tests are not yet implemented.

```bash
# Quick validation
./oncall-agent-poc/test_agent.sh

# When tests are implemented:
pytest oncall-agent-poc/tests/
pytest --cov=oncall-agent-poc/src --cov-report=html
```

### Code Quality

```bash
cd oncall-agent-poc
black src/                     # Format code
ruff check src/                # Lint code
mypy src/                      # Type checking
```

### Container Operations

```bash
cd oncall-agent-poc
docker build -t oncall-agent .
./build.sh                     # Helper script

# Generate kubeconfig for containers
./scripts/generate_container_kubeconfig.sh
```

## Project Structure

```
claude-agents/
└── oncall-agent-poc/           # Main agent implementation
    ├── src/
    │   ├── agent/              # Core agent implementation
    │   │   ├── oncall_agent.py        # Claude Agent SDK wrapper
    │   │   └── incident_triage.py     # Two-turn LLM investigation engine
    │   ├── integrations/       # Monitoring and coordination
    │   │   ├── orchestrator.py        # MAIN ENTRY POINT for daemon mode
    │   │   └── k8s_event_watcher.py   # Proactive health monitoring + events
    │   ├── tools/              # Helper modules (not MCP servers)
    │   │   ├── k8s_analyzer.py        # Kubernetes analysis helpers
    │   │   ├── github_integrator.py   # GitHub deployment correlation
    │   │   └── aws_integrator.py      # AWS verification (Secrets, ECR)
    │   └── notifications/      # Teams integration
    │       └── teams_notifier.py      # Adaptive Cards
    ├── config/                 # Configuration files
    │   ├── service_mapping.yaml       # Service → GitHub repo + criticality
    │   ├── k8s_monitoring.yaml        # Alert rules and filters
    │   └── notifications.yaml         # Teams notification config
    ├── tests/                  # Test suite (infrastructure ready)
    ├── scripts/                # Utility scripts
    ├── k8s/                    # Kubernetes deployment manifests
    └── docs/                   # Documentation
```

## Architecture Deep Dive

### Core Components

**`src/integrations/orchestrator.py`** - Main entry point
- Coordinates all monitoring and incident handling
- Implements incident correlation (30-min window)
- Reduces LLM API costs by ~75% through deduplication

**`src/agent/incident_triage.py`** - Two-turn LLM investigation
- **Turn 1**: Claude assesses severity and creates investigation plan
- **Data Collection**: Pod logs, events, AWS resources, GitHub deployments
- **Turn 2**: Claude provides root cause analysis and specific remediation

**`src/integrations/k8s_event_watcher.py`** - Proactive monitoring
- Checks pod health every 60 seconds
- Detects restarts, failures, stuck pods
- Watches Kubernetes warning events

### Data Flow

```
Proactive Health Check (every 60s)
    ↓
Pod Status Analysis (restarts, failures, stuck)
    ↓
Alert Rule Evaluation (config/k8s_monitoring.yaml)
    ↓
Incident Detected → orchestrator.py.handle_incident()
    ↓
Service Enrichment (service_mapping.yaml → GitHub repo, criticality)
    ↓
Turn 1: Claude Initial Assessment (severity, investigation plan)
    ↓
Data Collection (logs, events, AWS verification, GitHub correlation)
    ↓
Turn 2: Claude Refined Analysis (root cause, specific remediation)
    ↓
Teams Notification (Adaptive Card with analysis + ArgoCD links)
```

### Key Design Patterns

**Two-Turn LLM Investigation** (`incident_triage.py:172`):
- Separates triage from detailed analysis
- First turn decides if full investigation is needed
- Second turn provides actionable remediation with exact values

**Incident Correlation** (`orchestrator.py:85`):
- Groups related incidents within 30-minute window
- Deduplicates notifications and LLM calls
- Cost optimization: ~75% reduction in API usage

**Cluster Protection** (Hard-coded safety):
```python
ALLOWED_CLUSTERS = ["dev-eks"]
PROTECTED_CLUSTERS = ["prod-eks", "staging-eks"]
```
Any protected cluster access raises `PermissionError`.

**Service Mapping** (`config/service_mapping.yaml`):
- Maps K8s pod names → GitHub repositories
- Defines criticality levels (critical/high/medium)
- Enables GitHub deployment correlation

## Configuration

### Environment Variables

Required in `.env`:
```bash
# Claude LLM
ANTHROPIC_API_KEY=sk-ant-...

# GitHub integration
GITHUB_TOKEN=ghp_...
GITHUB_ORG=artemishealth

# Kubernetes
K8S_CONTEXT=dev-eks                    # MUST be dev-eks (enforced)

# AWS (for EKS authentication in Docker)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# Teams notifications
TEAMS_WEBHOOK_URL=https://...
TEAMS_NOTIFICATIONS_ENABLED=true

# Optional tuning
AGENT_LOG_LEVEL=INFO
AGENT_MAX_THINKING_TOKENS=12000
```

### Configuration Files

**`config/service_mapping.yaml`** - Service definitions:
```yaml
service_mappings:
  proteus:
    github_repo: artemishealth/proteus
    criticality: critical
    health_check_endpoint: /api/proteus/.well-known/ready
```

**`config/k8s_monitoring.yaml`** - Alert rules:
```yaml
monitoring:
  clusters:
    - name: dev-eks
      namespaces: [proteus-dev, hermes-dev, ...]
  alert_rules:
    - name: oom-killer-active
      conditions:
        event_reason: ["OOMKilled"]
      severity: critical
```

**`config/notifications.yaml`** - Teams settings:
```yaml
teams_notifications:
  notification_rules:
    severity_threshold: critical  # or high
  rate_limiting:
    cooldown_minutes: 5
```

## Key Concepts

### Severity Classification

Defined in `IncidentTriageEngine`:
- **Critical**: Service outage, OOMKilled with 10+ restarts, immediate action required
- **High**: CrashLoopBackOff, 3+ restarts, automated remediation recommended
- **Medium**: Warning signs, 1-2 restarts, queue for review
- **Low**: Informational, document and learn

### Deployment Modes

**Daemon Mode** (Production) - `orchestrator.py`:
- Direct API access (kubernetes-python, PyGithub, boto3)
- Anthropic API for LLM analysis
- Continuous monitoring with 60s health checks
- **Recommended deployment method**

**Interactive Mode** (Development) - `oncall_agent.py`:
- Uses Claude Agent SDK
- Ad-hoc queries and testing
- REPL interface for experimentation

### AWS Integration

The agent verifies AWS resources during incident diagnosis:
- **Secrets Manager**: Validates ExternalSecret references exist
- **ECR**: Checks container images are available (ImagePullBackOff diagnosis)

Requires AWS credentials in environment for boto3 client.

### Teams Notifications

Sends Adaptive Cards with:
1. **Immediate Alert**: Critical/high incidents detected
2. **Diagnosis Complete**: Claude's analysis and remediation steps
3. **Cluster-aware ArgoCD links**: Direct links to relevant deployments

Configure via `TEAMS_WEBHOOK_URL` and severity threshold in `notifications.yaml`.

## Common Tasks

### Adding a New Service to Monitor

1. Add to `config/service_mapping.yaml`:
```yaml
new-service:
  github_repo: artemishealth/new-service
  criticality: high
  health_check_endpoint: /health
```

2. Update `config/k8s_monitoring.yaml` if new namespace needed

3. Test: `./test_agent.sh` to verify configuration loads

### Extending Alert Rules

Edit `config/k8s_monitoring.yaml`:
```yaml
alert_rules:
  - name: custom-rule
    conditions:
      event_reason: ["CustomError"]
      restart_count_threshold: 5
    severity: high
    investigation_priority: 2
```

The triage engine automatically evaluates new rules.

### Debugging Agent Behavior

1. Check logs:
```bash
# Docker
docker compose logs -f

# Local daemon
./run_daemon.sh logs

# Tail log file
tail -f logs/agent.log
```

2. Verify configuration:
```bash
python3 -c "
from src.integrations.orchestrator import Orchestrator
o = Orchestrator()
print(o.config)
"
```

3. Test triage logic:
```bash
./test_agent.sh --verbose
```

## Safety and Guardrails

**Cluster Protection**:
- Only `dev-eks` allowed for operations
- `prod-eks`, `staging-eks` are protected
- Multiple enforcement layers

**Rate Limiting**:
- Incident grouping (30-min correlation window)
- LLM call deduplication
- Teams notification cooldown (5 min per service)

**Audit Trail**:
- All actions logged with timestamps and reasoning
- Teams notifications document decisions
- GitOps workflow (no automated rollbacks)

**Dry-run Mode**: Set `DRY_RUN=true` for testing without sending Teams notifications.

## Deployment

### Local Development
```bash
./run_agent.sh --query "..."              # Ad-hoc queries
python src/agent/oncall_agent.py --dev    # Interactive REPL
```

### Continuous Monitoring (Local)
```bash
docker compose up                         # Containerized (recommended)
./run_daemon.sh start                     # Background process
```

### Production (Kubernetes)
```bash
cd k8s/
kubectl apply -f .
kubectl logs -f deployment/oncall-agent -n oncall-agent
```

Requires:
- Kubernetes RBAC (serviceAccount with read-only access)
- AWS IAM authentication for EKS
- Secrets for ANTHROPIC_API_KEY, GITHUB_TOKEN, TEAMS_WEBHOOK_URL

See `k8s/README.md` for complete deployment guide.

## Troubleshooting

### "Import errors" when running agent
```bash
# Ensure running from project root
cd /Users/ari.sela/git/claude-agents/oncall-agent-poc

# Or set PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
```

### "Permission denied" for cluster
- Verify `K8S_CONTEXT=dev-eks` in `.env`
- Check not targeting protected clusters
- Review cluster protection in `orchestrator.py:45`

### "ANTHROPIC_API_KEY not found"
- Ensure `.env` file exists with valid key
- Required for daemon mode LLM analysis
- Interactive mode uses Claude SDK config separately

### Docker container can't access EKS
- Set AWS credentials in `.env`
- Generate container kubeconfig: `./scripts/generate_container_kubeconfig.sh`
- Verify kubeconfig mounted in `docker-compose.yml`

### Agent not detecting incidents
- Check monitoring config: `config/k8s_monitoring.yaml`
- Verify service mapping: `config/service_mapping.yaml`
- Review logs for configuration errors
- Test with: `kubectl get events --all-namespaces`

## Important Notes

1. **Project Location**: Currently at `/Users/ari.sela/git/claude-agents/oncall-agent-poc`. Parent repository is `claude-agents` (may contain other agent POCs in future).

2. **Daemon Mode is Production**: The `orchestrator.py` with direct APIs is the recommended deployment. Interactive SDK mode is for development/testing only.

3. **No Automated Rollbacks**: Agent provides recommendations only. Human approval required for destructive actions (GitOps workflow).

4. **Cost Optimization**: Incident correlation reduces LLM API costs by ~75% through intelligent deduplication.

5. **Test Suite Status**: Infrastructure configured but tests not yet implemented. When adding tests, focus on `incident_triage.py` and `orchestrator.py` with pytest-asyncio.

## References

- Claude Agent SDK: https://github.com/anthropics/anthropic-agent-sdk
- Kubernetes Python Client: https://github.com/kubernetes-client/python
- PyGithub: https://pygithub.readthedocs.io/
- Anthropic API: https://docs.anthropic.com/
