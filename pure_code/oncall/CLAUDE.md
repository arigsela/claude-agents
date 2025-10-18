# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **Intelligent On-Call Troubleshooting Agent** built with Claude Agent SDK. It monitors Kubernetes clusters (dev-eks), analyzes incidents using Claude LLM with multi-turn investigation, and provides intelligent remediation recommendations via Teams notifications.

**Key Architecture**: The agent uses **direct API access** (kubernetes, PyGithub, boto3) rather than MCP intermediaries, with Claude LLM providing intelligent analysis through the Anthropic API.

## Development Environment Setup

### Initial Setup
```bash
# Navigate to project
cd /Users/ari.sela/git/olympus/oncall-agent-poc

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with: ANTHROPIC_API_KEY, GITHUB_TOKEN, AWS credentials
```

### Required Environment Variables
- `ANTHROPIC_API_KEY`: Claude API key for LLM analysis
- `GITHUB_TOKEN`: GitHub PAT with repo and workflow access
- `K8S_CONTEXT`: Must be "dev-eks" (cluster protection enforced)
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: For EKS authentication (Docker containers)
- `DATADOG_API_KEY` / `DATADOG_APP_KEY`: Datadog credentials for metrics queries (optional)
- `TEAMS_WEBHOOK_URL`: Teams incoming webhook (optional, for notifications)

## Common Commands

### Running the Agent

**Interactive Query Mode** (ad-hoc troubleshooting):
```bash
./run_agent.sh --query "What services are monitoring?"
python src/agent/oncall_agent.py --dev  # Interactive REPL
```

**Continuous Monitoring Mode** (production):
```bash
# Docker (recommended)
docker compose up              # Foreground with logs
docker compose up -d           # Background daemon
docker compose logs -f         # Watch logs
docker compose down            # Stop

# Local Python daemon (development)
python3 src/integrations/orchestrator.py

# Background daemon (macOS)
./run_daemon.sh start          # Start in background
./run_daemon.sh status         # Check if running
./run_daemon.sh logs           # Watch logs
./run_daemon.sh stop           # Stop daemon
```

### Testing

**Note**: Test infrastructure is configured but tests are not yet implemented.

```bash
# Run quick validation tests
./test_agent.sh

# When tests are implemented:
pytest                                    # Run all tests
pytest --cov=src --cov-report=html       # With coverage
pytest tests/test_agent.py               # Specific test
```

### Code Quality
```bash
black src/                     # Format code
ruff check src/                # Lint code
mypy src/                      # Type checking
```

### Container Operations
```bash
# Build container
docker build -t oncall-agent .
./build.sh                     # Helper script

# Generate kubeconfig for containers
./scripts/generate_container_kubeconfig.sh
```

## Project Architecture

### Core Components

**`src/agent/`** - Main agent implementation
- `oncall_agent.py`: Claude Agent SDK client wrapper
- `incident_triage.py`: **Two-turn LLM investigation engine** (Anthropic API)
  - Turn 1: Initial severity assessment and investigation plan
  - Turn 2: Refined analysis with specific remediation steps

**`src/integrations/`** - Monitoring and coordination
- `orchestrator.py`: **Main entry point** for daemon mode - coordinates all components
- `k8s_event_watcher.py`: Proactive pod health monitoring (every 60s) + event watching

**`src/tools/`** - Helper modules (not MCP servers)
- `k8s_analyzer.py`: Kubernetes cluster analysis helpers
- `github_integrator.py`: GitHub deployment correlation logic
- `datadog_integrator.py`: Datadog metrics queries for historical analysis
- `nat_gateway_analyzer.py`: NAT gateway traffic analysis
- `zeus_job_correlator.py`: Zeus refresh job correlation

**`src/notifications/`** - Teams integration
- `teams_notifier.py`: Adaptive Cards for incident notifications

**`config/`** - Configuration files
- `service_mapping.yaml`: Service → GitHub repo mapping + criticality levels
- `k8s_monitoring.yaml`: Alert rules and cluster/namespace filters
- `notifications.yaml`: Teams notification configuration
- `mcp_servers.json`: (Legacy) MCP server config - **not actively used in daemon mode**

### Data Flow

```
Proactive Monitoring (every 60s)
    ↓
Pod Health Check (restarts, failures, stuck)
    ↓
Alert Rule Evaluation (config/k8s_monitoring.yaml)
    ↓
Incident Detected → Orchestrator.handle_incident()
    ↓
Enrichment (service_mapping.yaml for GitHub repo, criticality)
    ↓
Triage Engine → Claude LLM Turn 1 (severity, investigation plan)
    ↓
Data Collection (logs, events, AWS resources, GitHub deployments)
    ↓
Claude LLM Turn 2 (root cause, specific remediation)
    ↓
Teams Notification (Adaptive Card with analysis)
```

### Key Design Patterns

**1. Two-Turn LLM Investigation** (`incident_triage.py`):
- **Turn 1**: Claude assesses severity and plans investigation
- **Data Collection**: Gather pod logs, events, AWS resources
- **Turn 2**: Claude refines analysis with specific remediation

**2. Incident Correlation** (`orchestrator.py`):
- Groups related incidents within 30-minute window
- Reduces duplicate LLM calls by ~75%

**3. Cluster Protection** (Hard-coded safety):
- `ALLOWED_CLUSTERS = ["dev-eks"]`
- `PROTECTED_CLUSTERS = ["prod-eks", "staging-eks"]`
- Any protected cluster access raises `PermissionError`

**4. Service Mapping** (`config/service_mapping.yaml`):
- Maps K8s pod names → GitHub repositories
- Defines criticality levels (critical/high/medium)
- Used for enrichment and correlation

## Important Concepts

### The Agent SDK vs Direct APIs

This project uses **both**:
- **Claude Agent SDK** (`src/agent/oncall_agent.py`): For interactive queries and legacy MCP integration
- **Anthropic API** (`incident_triage.py`): For daemon mode LLM analysis (production)
- **Direct K8s/GitHub APIs**: kubernetes-python, PyGithub for monitoring (no MCP overhead)

The daemon mode (`orchestrator.py`) is the **recommended deployment** and uses direct APIs + Anthropic client.

### Severity Classification

Defined in `IncidentTriageEngine`:
- **Critical**: Service outage, OOMKilled with 10+ restarts, immediate action
- **High**: CrashLoopBackOff, 3+ restarts, automated remediation
- **Medium**: Warning signs, 1-2 restarts, queue for review
- **Low**: Informational, document and learn

### AWS Integration

The agent verifies AWS resources when diagnosing incidents:
- **Secrets Manager**: Checks if ExternalSecret references exist
- **ECR**: Verifies container images exist (ImagePullBackOff diagnosis)
- **CloudWatch**: NAT gateway traffic metrics

Requires AWS credentials in environment for boto3 access.

### Datadog Integration

The agent queries Datadog for historical Kubernetes metrics:
- **CPU/Memory Trends**: Track resource usage over time (hours to weeks)
- **Network Traffic**: Analyze pod-level network patterns
- **Memory Leak Detection**: Identify gradual memory increases
- **Performance Correlation**: Compare metrics before/after deployments

**Available Tools**:
- `query_datadog_metrics`: Query any Datadog metric with filtering
- `get_resource_usage_trends`: Batch query CPU/memory for trend analysis
- `check_network_traffic`: Network TX/RX with totals in GB

Requires `DATADOG_API_KEY` and `DATADOG_APP_KEY` in environment. See `docs/datadog-integration.md` for full guide.

### Teams Notifications

Sends Adaptive Cards with:
1. **Immediate Alert**: Incident detected (critical/high only)
2. **Diagnosis Complete**: Claude's analysis and remediation steps
3. **Cluster-aware ArgoCD links**: Links to relevant ArgoCD deployment

Configure via `TEAMS_WEBHOOK_URL` and `TEAMS_NOTIFICATIONS_ENABLED`.

## Testing Strategy

When implementing tests:
- **Unit Tests**: Test individual triage rules, severity classification
- **Integration Tests**: Mock Anthropic API responses, K8s events
- **E2E Tests**: Use pytest fixtures for full incident workflows
- **Coverage Target**: Focus on `incident_triage.py` and `orchestrator.py`

Use `pytest-asyncio` for async test support.

## Deployment Modes

### Local Development
```bash
./run_agent.sh --query "..."     # Ad-hoc queries
python src/agent/oncall_agent.py --dev  # Interactive
```

### Continuous Monitoring (Local)
```bash
docker compose up                # Containerized (recommended)
./run_daemon.sh start            # Background process
```

### Production (Kubernetes)
```bash
# See k8s/ directory for manifests
kubectl apply -f k8s/
kubectl logs -f deployment/oncall-agent -n oncall-agent
```

Requires:
- Kubernetes RBAC (serviceAccount with read access)
- AWS IAM authentication (for EKS)
- Secrets for ANTHROPIC_API_KEY, GITHUB_TOKEN

## Safety and Guardrails

**Hard-coded Cluster Protection**:
- Only `dev-eks` is allowed for operations
- `prod-eks`, `staging-eks` are protected
- Check enforced in multiple layers

**Rate Limiting**:
- Incident grouping (30-min correlation window)
- LLM call deduplication
- Teams notification cooldown (5 min per service)

**Audit Trail**:
- All actions logged with timestamps
- Teams notifications document decisions
- GitOps workflow (no automated rollbacks)

## Configuration Files

### `config/service_mapping.yaml`
Maps service names to GitHub repos and criticality:
```yaml
service_mappings:
  proteus:
    github_repo: artemishealth/proteus
    criticality: critical
    health_check_endpoint: /api/proteus/.well-known/ready
```

### `config/k8s_monitoring.yaml`
Defines alert rules and monitoring scope:
```yaml
monitoring:
  clusters:
    - name: dev-eks
      namespaces: [proteus-dev, hermes-dev, ...]
  alert_rules:
    - name: oom-killer-active
      trigger: OOMKilled event
      severity: critical
```

### `config/notifications.yaml`
Teams notification rules:
```yaml
teams_notifications:
  notification_rules:
    severity_threshold: critical  # or high
  rate_limiting:
    cooldown_minutes: 5
```

## Common Patterns

### Adding a New Service to Monitor

1. **Add to service mapping** (`config/service_mapping.yaml`):
   ```yaml
   new-service:
     github_repo: artemishealth/new-service
     criticality: high
     health_check_endpoint: /health
   ```

2. **Update monitoring config** (`config/k8s_monitoring.yaml`):
   - Add namespace if needed
   - Service will be auto-detected by pod name matching

3. **Test**: `./test_agent.sh` to verify configuration loads

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

The triage engine will automatically evaluate new rules.

## Troubleshooting

### "Import errors" when running agent
```bash
# Ensure PYTHONPATH includes src/
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
# Or run from project root
cd /Users/ari.sela/git/olympus/oncall-agent-poc
```

### "Permission denied" for cluster
- Check `K8S_CONTEXT` is set to `dev-eks`
- Verify you're not targeting protected clusters
- Review cluster protection in `orchestrator.py`

### "ANTHROPIC_API_KEY not found"
- Ensure `.env` file exists with valid key
- In daemon mode, this is required for LLM analysis
- In interactive mode, Claude SDK uses its own config

### Docker container can't access EKS
- Set AWS credentials in `.env`: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- Generate container kubeconfig: `./scripts/generate_container_kubeconfig.sh`
- Mount kubeconfig in docker-compose.yml

## Important Notes

1. **Project Location**: Currently nested in `/Users/ari.sela/git/olympus/oncall-agent-poc`. Will be moved to separate `artemishealth` repository for team collaboration.

2. **Daemon Mode is Production**: The `orchestrator.py` daemon with direct APIs is the recommended deployment. Interactive SDK mode is for development/testing.

3. **No Automated Rollbacks**: Agent provides recommendations only. Human approval required for destructive actions.

4. **Cost Optimization**: Incident correlation reduces LLM API costs by ~75% through deduplication.

5. **Dry-run Mode**: Set `DRY_RUN=true` for testing without sending Teams notifications.

## References

- Claude Agent SDK: https://github.com/anthropics/anthropic-agent-sdk
- FastAPI Docs: https://fastapi.tiangolo.com/
- Kubernetes Python Client: https://github.com/kubernetes-client/python
- PyGithub: https://pygithub.readthedocs.io/
