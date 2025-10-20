# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a **Learning Lab for Anthropic AI Integration Patterns** - a repository demonstrating different approaches to building intelligent automation agents with Anthropic's Claude AI. The repository contains two production-ready implementations of the same use case (Kubernetes monitoring) using different architectural patterns.

## Key Learning Objectives

This repository helps teams understand:
1. **When to use Claude Agent SDK** vs **when to use Anthropic API directly**
2. **Multi-agent architecture** vs **single-agent architecture**
3. **MCP (Model Context Protocol)** vs **direct API libraries**
4. **Tradeoffs**: Flexibility vs simplicity, scalability vs overhead, context management vs stateless

## Repository Structure

```
claude-agents/
├── eks/                       # Claude Agent SDK + Multi-Agent + MCP
│   ├── .claude/               # Agent configuration (institutional memory)
│   │   ├── CLAUDE.md          # Cluster context (reloaded each cycle)
│   │   ├── settings.json      # Safety hooks configuration
│   │   ├── agents/            # 6 specialized subagent definitions
│   │   └── hooks/             # Safety validator, logger, Teams notifier
│   ├── monitor_daemon.py      # Main orchestrator (single entry point)
│   ├── pyproject.toml
│   └── requirements.txt
│
├── oncall/                    # Anthropic API + Single-Agent + FastAPI
│   ├── src/
│   │   ├── agent/             # Claude Agent SDK wrapper
│   │   ├── api/               # FastAPI server (n8n integration)
│   │   ├── integrations/      # Daemon mode orchestrator
│   │   └── tools/             # K8s/GitHub/AWS helpers
│   ├── setup.py
│   └── requirements.txt
│
└── docs/                      # Shared documentation and examples
```

## Project-Specific Commands

### EKS Monitoring Agent (Claude Agent SDK)

**Setup:**
```bash
cd eks
pip install -r requirements.txt
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, GITHUB_PERSONAL_ACCESS_TOKEN
```

**Run:**
```bash
# Local development
python monitor_daemon.py

# Docker (recommended for production)
./build.sh
docker compose up -d

# Deploy to AWS ECR
./deploy-to-ecr.sh v1.0.0

# Deploy to Kubernetes (GitOps-ready)
kubectl apply -f k8s/
```

**Logs:**
```bash
tail -f /tmp/eks-monitoring-daemon.log        # Daemon logs
tail -f /tmp/claude-k8s-agent-actions.log     # Action audit trail
ls -la /tmp/eks-monitoring-reports/           # Cycle reports
```

**Testing:**
```bash
# Test MCP servers
npx -y @modelcontextprotocol/server-kubernetes
npx -y @modelcontextprotocol/server-github

# Check subagent health
./check_all_namespaces.sh
```

### OnCall Troubleshooting Agent (Anthropic API)

**Setup:**
```bash
cd oncall
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, GITHUB_TOKEN, AWS credentials
```

**Run:**
```bash
# API server (n8n integration)
./run_api_server.sh
open http://localhost:8000/docs  # Interactive API documentation

# Daemon mode (monitoring)
docker compose up -d

# Both modes
docker compose up  # Runs daemon + API together
```

**Testing:**
```bash
# API tests
pytest tests/api/ -v
pytest --cov=src/api --cov-report=html

# Quick test
./test_query.sh
curl http://localhost:8000/health
```

**Deploy to Kubernetes:**
```bash
kubectl apply -f k8s/                        # Both daemon and API
kubectl apply -f k8s/deployment.yaml         # Daemon only
kubectl apply -f k8s/api-deployment.yaml     # API only
```

## Architecture Comparison

### EKS Agent (Claude Agent SDK)

**Pattern:** Autonomous agent with persistent memory and multi-agent coordination

**When to Use:**
- Persistent conversational agents that maintain state across interactions
- Complex workflows requiring multiple specialized subagents
- Tool-heavy operations where MCP provides structured access
- Dynamic context that changes over time (institutional memory)
- Safety-critical operations needing pre-execution validation hooks

**Key Technologies:**
- Claude Agent SDK - Core framework
- MCP Servers - Kubernetes, GitHub, Atlassian (Jira)
- Multi-agent coordination via `Task` tool
- Configuration-driven behavior (`.claude/` directory)
- Python 3.10+ and Node.js (for MCP servers)

**Entry Point:** `eks/monitor_daemon.py`

**Subagents:**
1. `k8s-diagnostics` - Bulk health checks (all namespaces in one call)
2. `k8s-remediation` - Safe rolling restarts (2+ replica deployments only)
3. `k8s-log-analyzer` - Root cause analysis from logs
4. `k8s-cost-optimizer` - Resource utilization analysis
5. `k8s-github` - Deployment correlation and config PRs
6. `k8s-jira` - Smart ticket management with anti-spam logic

### OnCall Agent (Anthropic API)

**Pattern:** Stateless analysis with HTTP API wrapper for external integrations

**When to Use:**
- Stateless analysis where external system manages context (n8n, web UI)
- HTTP API wrappers for third-party integrations
- Simple, focused tasks that don't need persistent memory
- Performance-critical applications avoiding SDK/MCP overhead
- Quick prototyping without architectural complexity

**Key Technologies:**
- Anthropic API (Direct) - Messages API
- FastAPI - HTTP API server
- Direct Python libraries - kubernetes, PyGithub, boto3
- Two-turn investigation pattern
- Python 3.11+

**Entry Points:**
- `oncall/src/integrations/orchestrator.py` - Daemon mode (monitoring)
- `oncall/src/api/api_server.py` - API mode (n8n integration)

**Dual Modes:**
1. **Daemon Mode** - Proactive monitoring → Teams alerts
2. **API Mode** - HTTP endpoints → n8n interactive troubleshooting

## Critical Architecture Patterns

### EKS Agent: Multi-Agent Coordination

The orchestrator delegates to specialized subagents:
```python
# Orchestrator invokes subagent
await client.query("Use Task tool to invoke k8s-diagnostics subagent")

# Subagent runs in isolated context
# Returns structured report

# Orchestrator decides next action
```

**Subagents cannot see each other's context** - only their final outputs.

### EKS Agent: MCP vs Bash Commands

**ALWAYS prefer MCP tools over Bash/kubectl:**
```python
# ❌ BAD
await client.query("Run: kubectl get pods -n production")

# ✅ GOOD
await client.query("Use mcp__kubernetes__pods_list with namespace=production")
```

### EKS Agent: Safety Hooks

Hooks intercept tool calls **before execution**:
1. Subagent calls tool (e.g., `mcp__kubernetes__pods_delete`)
2. SDK triggers `PreToolUse` hook
3. Hook script validates via stdin/stdout JSON
4. SDK allows or blocks based on response

**Hook Chain:**
1. `safety_validator.py` - Blocks dangerous operations
2. `action_logger.py` - Logs to audit trail
3. `teams_notifier.py` - Sends Teams notification

### EKS Agent: GitOps-Ready Configuration

**ConfigMap-driven behavior** - update agent without rebuilding images:

| Component | Type | Hot-Reload | Update Method |
|-----------|------|------------|---------------|
| API Keys | ExternalSecret | ❌ | Update AWS Secrets → Restart pod |
| Model Names | ConfigMap | ❌ | Edit ConfigMap → Restart pod |
| **Cluster Context** | ConfigMap | **✅ YES** | **Edit in Git → Auto-applies next cycle** |
| Subagent Definitions | ConfigMap | ❌ | Edit in Git → Restart pod |

**Example GitOps Workflow:**
```bash
# Add new namespace to monitor (NO IMAGE REBUILD!)
vi k8s/configmaps/cluster-context.yaml
git commit -m "Monitor artemis-prod namespace"
git push
# ArgoCD syncs ConfigMap (30 seconds)
# Next monitoring cycle picks up change (< 15 minutes)
# NO POD RESTART NEEDED!
```

### OnCall Agent: Two-Turn Investigation

The daemon uses **two-turn LLM investigation**:
1. **Turn 1**: Claude assesses severity and plans investigation
2. **Data Collection**: Gather pod logs, events, AWS resources
3. **Turn 2**: Claude refines analysis with specific remediation

**Incident Correlation**: Groups related incidents within 30-minute window, reducing LLM calls by ~75%.

### OnCall Agent: API Endpoints

**8 HTTP endpoints for n8n integration:**
- `POST /query` - Send queries to the agent
- `POST /incident` - Report K8s incidents
- `POST /session` - Create session for multi-turn conversations
- `GET /session/{id}` - Retrieve session with history
- `DELETE /session/{id}` - Delete session
- `GET /sessions/stats` - Session statistics
- `GET /health` - Health check
- `GET /docs` - Interactive Swagger UI

**Features:**
- Session-based conversations (30-min TTL)
- API key authentication (dev mode when API_KEYS not set)
- Rate limiting (60/30/10 req/min per endpoint)
- Cluster protection (dev-eks only)

## Model Selection Strategy

Both projects support flexible model configuration:

### EKS Agent Models
```bash
ORCHESTRATOR_MODEL=claude-sonnet-4-20250514    # Context management
DIAGNOSTIC_MODEL=claude-sonnet-4-20250514      # Fast health checks
REMEDIATION_MODEL=claude-sonnet-4-20250514     # Safety-critical
LOG_ANALYZER_MODEL=claude-sonnet-4-5-20250929  # Pattern recognition
COST_OPTIMIZER_MODEL=claude-sonnet-4-20250514  # Cost analysis
GITHUB_AGENT_MODEL=claude-sonnet-4-20250514    # Professional communication
JIRA_AGENT_MODEL=claude-sonnet-4-5-20250929    # Ticket management
```

### OnCall Agent Models
```bash
ANTHROPIC_MODEL=claude-sonnet-4-20250514       # Main analysis model
```

## Safety and Cluster Protection

Both agents enforce **hard-coded cluster protection**:

```python
ALLOWED_CLUSTERS = ["dev-eks"]
PROTECTED_CLUSTERS = ["prod-eks", "staging-eks"]
```

Any protected cluster access raises `PermissionError`.

### EKS Agent Additional Safety

**Protected Resources** (safety validator blocks):
- Namespace deletion
- PersistentVolume deletion
- Operations on `kube-system`, `production`, `prod`
- Bulk deletions (`--all-namespaces`, `-A`)

**Approved Auto-Remediation** (for dev-eks):
- Rolling restarts of deployments with **2+ replicas** (non-disruptive)
- Clear Failed/Evicted pods in any namespace
- Scale deployments by ±2 replicas
- Pod deletions in non-system namespaces

### OnCall Agent Additional Safety

**API Security:**
- API key authentication via `X-API-Key` header
- Rate limiting per endpoint
- Dev mode support (no auth when API_KEYS not set)
- CORS configuration

## Configuration Files

### EKS Agent Configuration

**`.claude/CLAUDE.md`** - Cluster-specific context (reloaded every cycle):
- Cluster name, region, version
- Critical namespaces to monitor
- Known recurring issues
- Team-specific SOPs
- Escalation criteria
- Approved auto-remediation actions

**`.claude/settings.json`** - Safety hooks configuration:
```json
{
  "hooks": {
    "PreToolUse": [
      {"path": ".claude/hooks/safety_validator.py"},
      {"path": ".claude/hooks/action_logger.py"},
      {"path": ".claude/hooks/teams_notifier.py"}
    ]
  }
}
```

**`.claude/agents/*.md`** - Subagent definitions:
```markdown
---
name: k8s-diagnostics
description: Fast bulk health checks
tools: mcp__kubernetes__pods_list, mcp__kubernetes__events_list
model: $DIAGNOSTIC_MODEL
---
[Detailed instructions, tool usage examples]
```

### OnCall Agent Configuration

**`oncall/config/service_mapping.yaml`** - Service → GitHub repo mapping:
```yaml
service_mappings:
  proteus:
    github_repo: artemishealth/proteus
    criticality: critical
    health_check_endpoint: /api/proteus/.well-known/ready
```

**`oncall/config/k8s_monitoring.yaml`** - Alert rules:
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

**`oncall/config/notifications.yaml`** - Teams notification rules:
```yaml
teams_notifications:
  notification_rules:
    severity_threshold: critical
  rate_limiting:
    cooldown_minutes: 5
```

## Testing Strategy

### EKS Agent Testing

```bash
# Test MCP servers
npx -y @modelcontextprotocol/server-kubernetes
npx -y @modelcontextprotocol/server-github

# Test hooks manually
echo '{"tool_name":"mcp__kubernetes__pods_list","tool_input":{}}' | \
  python .claude/hooks/safety_validator.py

# Verify agent starts
python monitor_daemon.py  # Should load .claude/ configuration
```

### OnCall Agent Testing

```bash
# Unit tests
pytest tests/api/ -v

# Coverage
pytest tests/api/ --cov=src/api --cov-report=html

# API tests
./test_query.sh
curl http://localhost:8000/health
```

## Performance Metrics

Based on production usage with **dev-eks cluster** (40 nodes, 20+ namespaces, 200+ pods):

### EKS Monitoring Agent
- **Cycle time**: 45-90 seconds (full cluster scan)
- **MCP calls**: 3-5 per cycle (bulk queries)
- **Namespace coverage**: 100% (all 20+ namespaces checked)
- **Jira noise**: ~5 comments/day per ticket (smart filtering)
- **Teams notifications**: 1 per cycle (comprehensive summary)
- **Token usage**: ~15K tokens/cycle

### OnCall Agent
- **Cycle time**: 60-180 seconds (often timeouts)
- **K8s API calls**: 20+ per cycle (sequential namespaces)
- **Namespace coverage**: ~30-40% (timeouts after 8 namespaces)
- **Teams notifications**: 1 per incident (simpler format)
- **Token usage**: ~8K tokens/cycle (less complex analysis)
- **Incident correlation**: ~75% reduction in LLM calls

**Why the difference?**
- EKS agent: Bulk queries + specialized subagents = better coverage, more tokens
- OnCall agent: Sequential queries + simpler = lower coverage, fewer tokens
- **Neither is "better"** - depends on your needs (coverage vs cost)

## Common Development Tasks

### Adding a New Service to Monitor

**EKS Agent:**
1. Edit `eks/.claude/CLAUDE.md` - Add namespace to critical list
2. Changes apply on next monitoring cycle (no restart needed)

**OnCall Agent:**
1. Edit `oncall/config/service_mapping.yaml` - Add service entry
2. Edit `oncall/config/k8s_monitoring.yaml` - Add namespace if needed
3. Restart daemon

### Creating a New Subagent (EKS Only)

1. Create `eks/.claude/agents/my-subagent.md`:
```markdown
---
name: my-subagent
description: When to use this subagent
tools: Read, mcp__kubernetes__pods_list
model: $MY_SUBAGENT_MODEL
---
[Detailed instructions]
```

2. Add model to `eks/.env`:
```bash
MY_SUBAGENT_MODEL=claude-sonnet-4-20250514
```

3. Orchestrator automatically discovers via `setting_sources=["project"]`

### Extending Alert Rules (OnCall Agent)

Edit `oncall/config/k8s_monitoring.yaml`:
```yaml
alert_rules:
  - name: custom-rule
    conditions:
      event_reason: ["CustomError"]
      restart_count_threshold: 5
    severity: high
```

### Customizing Safety Hooks (EKS Agent)

Edit `eks/.claude/hooks/safety_validator.py`:
- Add/remove protected namespaces
- Define dangerous command patterns
- Set validation rules for MCP operations

## Troubleshooting

### EKS Agent Issues

**MCP Connection Failures:**
```bash
# Verify Node.js is installed
node --version

# Test MCP servers manually
npx -y @modelcontextprotocol/server-kubernetes
npx -y @modelcontextprotocol/server-github
```

**Agent Not Loading Context:**
- Verify `setting_sources=["project"]` in `ClaudeAgentOptions`
- Check `.claude/CLAUDE.md` exists and is valid
- Restart daemon to reload subagent definitions

**Hook Execution Errors:**
```bash
# Ensure hooks are executable
chmod +x eks/.claude/hooks/*.py

# Test hook manually
echo '{"tool_name":"Bash","tool_input":{"command":"kubectl get pods"}}' | \
  python eks/.claude/hooks/safety_validator.py
```

### OnCall Agent Issues

**"Permission denied" for cluster:**
- Check `K8S_CONTEXT=dev-eks` in `.env`
- Verify not targeting protected clusters

**Docker container can't access EKS:**
- Set AWS credentials in `.env`
- Generate container kubeconfig: `./scripts/generate_container_kubeconfig.sh`
- Mount kubeconfig in docker-compose.yml

**API not responding:**
```bash
curl http://localhost:8000/health
docker compose logs oncall-agent-api
```

## Comparing Both Approaches

### Use Claude Agent SDK (EKS) When:
1. Agent needs memory across multiple interactions
2. Complex workflows require coordination between specialized agents
3. You want MCP integration for structured tool access
4. Safety is critical and you need pre-execution validation hooks
5. Configuration-driven behavior is preferred

### Use Anthropic API (OnCall) When:
1. Stateless analysis where context is managed externally (n8n)
2. Building HTTP APIs around Claude for integrations
3. Simple, focused tasks that don't need persistent memory
4. Performance matters and you want to avoid MCP overhead
5. Quick prototyping or proof-of-concepts

## Running Both Agents Together

**Both agents can run simultaneously** - they serve complementary purposes:

```bash
# Terminal 1: Start EKS monitoring daemon
cd eks
python monitor_daemon.py
# → Runs every 15 min, creates Jira tickets, sends Teams cycle summaries

# Terminal 2: Start OnCall API for n8n
cd oncall
docker compose up oncall-agent-api -d
# → HTTP API on port 8000, responds to n8n queries
```

**Result:**
- ✅ Autonomous monitoring with Jira tracking (EKS)
- ✅ Interactive troubleshooting via n8n (OnCall)
- ✅ Both monitoring the same cluster, different mechanisms

## Important Notes

1. **Both implementations are production-ready** - choose based on your requirements
2. **No automated rollbacks** - agents provide recommendations only, human approval required
3. **Start with dev-eks** - validate behavior before production deployment
4. **Monitor costs** - token usage varies significantly between approaches
5. **GitOps workflow** - EKS agent supports ConfigMap-driven updates without rebuilding

## References

- [Claude Agent SDK Documentation](https://docs.claude.com/en/api/agent-sdk/python)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Kubernetes MCP Server](https://github.com/modelcontextprotocol/servers/tree/main/src/kubernetes)
- [GitHub MCP Server](https://github.com/modelcontextprotocol/servers/tree/main/src/github)
- [EKS Agent README](./eks/README.md)
- [OnCall Agent README](./oncall/README.md)
- [Main Repository README](./README.md)
