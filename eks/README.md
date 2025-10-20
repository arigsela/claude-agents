# EKS Monitoring Agent

An autonomous Kubernetes monitoring system powered by Claude Agent SDK that continuously monitors your EKS cluster and automatically remediates common issues.

## Features

- **Continuous Monitoring**: Automatically detects cluster health issues every 5-15 minutes
- **Intelligent Diagnostics**: Uses specialized subagents for root cause analysis
- **GitOps-Ready**: ConfigMap-driven configuration - update agent behavior via Git without rebuilding images
- **Safe Remediation**: Human-approved actions with comprehensive safety hooks
- **Jira Integration**: Automatic ticket creation and smart comment management (anti-spam logic)
- **GitHub Integration**: Deployment correlation and configuration PRs
- **Microsoft Teams Notifications**: Rich cycle summaries with critical issues, Jira tickets, and actions
- **MCP Integration**: Uses Kubernetes, GitHub, and Atlassian MCP servers for structured operations
- **Cost Optimization**: Identifies over-provisioned resources
- **External Secrets**: AWS Secrets Manager integration for credential management

## Architecture

```
Main Orchestrator (monitor_daemon.py)
├── k8s-diagnostics     → Efficient bulk health checks (all namespaces in one call)
├── k8s-remediation     → Safe rolling restarts (2+ replica deployments only)
├── k8s-log-analyzer    → Root cause analysis from logs and events
├── k8s-cost-optimizer  → Resource utilization and cost savings
├── k8s-github          → Deployment correlation and config PRs
└── k8s-jira            → Smart ticket management with anti-spam logic

MCP Servers:
├── Kubernetes MCP (Go binary)      → Structured cluster operations
├── GitHub MCP (Go binary)          → GitHub API operations
└── Atlassian MCP (Docker container) → Jira ticket management
```

## Prerequisites

- **Python 3.10+** - Core runtime
- **Node.js** - Required for Kubernetes and GitHub MCP servers
- **Docker** - Required for Atlassian MCP server (Jira integration)
- **kubectl** - Configured with cluster access
- **Anthropic API key** - Required for Claude LLM
- **GitHub Personal Access Token** - Required for deployment correlation and PR creation
- **Jira API Token** - Optional, for automatic ticket management (Cloud or Data Center)

## Quick Start

```bash
# 1. Clone and install dependencies
cd eks-monitoring-agent
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with required credentials:
#   - ANTHROPIC_API_KEY (required)
#   - GITHUB_PERSONAL_ACCESS_TOKEN (required)
#   - JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN (optional)
#   - TEAMS_WEBHOOK_URL (optional)

# 3. Customize cluster context
vi .claude/CLAUDE.md
# Update: cluster name, critical namespaces, SOPs, escalation criteria

# 4. Run the daemon
python monitor_daemon.py

# 5. Monitor output
tail -f /tmp/eks-monitoring-daemon.log              # Daemon logs
ls -lah /tmp/eks-monitoring-reports/                # Cycle reports
```

**First Run Checklist:**
- ✅ Verify MCP servers connect (kubernetes, github, atlassian)
- ✅ Check first cycle completes successfully
- ✅ Confirm all critical namespaces are checked
- ✅ Test Jira ticket creation (if enabled)
- ✅ Verify Teams notifications received (if enabled)

## Installation

### 1. Clone and Setup

```bash
cd eks-monitoring-agent
cp .env.example .env
# Edit .env with your API keys and configuration
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Cluster Context

Edit `.claude/CLAUDE.md` with your cluster-specific information:
- Cluster name and region
- Critical namespaces (infrastructure + applications)
- Known issues and patterns
- Standard operating procedures
- Escalation criteria
- Approved auto-remediation actions

## Configuration

### Environment Variables

See `.env.example` for all configuration options:

**Required:**
- **ANTHROPIC_API_KEY**: Claude API key from console.anthropic.com
- **GITHUB_PERSONAL_ACCESS_TOKEN**: GitHub PAT with `repo, read:org` scopes

**Model Configuration** (all models configurable per subagent):
- **ORCHESTRATOR_MODEL**: Main coordinator (default: `claude-sonnet-4-20250514`)
- **DIAGNOSTIC_MODEL**: Fast health checks (default: `claude-sonnet-4-20250514`)
- **REMEDIATION_MODEL**: Safety-critical operations (default: `claude-sonnet-4-20250514`)
- **LOG_ANALYZER_MODEL**: Complex pattern recognition (default: `claude-sonnet-4-5-20250929`)
- **COST_OPTIMIZER_MODEL**: Resource analysis (default: `claude-sonnet-4-20250514`)
- **GITHUB_AGENT_MODEL**: Professional communication (default: `claude-sonnet-4-20250514`)
- **JIRA_AGENT_MODEL**: Jira ticket management (default: `claude-sonnet-4-5-20250929`)

**Monitoring Configuration:**
- **CLUSTER_NAME**: Explicit cluster name (default: auto-detect from kubectl context)
- **CHECK_INTERVAL**: Health check frequency in seconds (default: 300)
- **LOG_LEVEL**: SILENT | MINIMAL | NORMAL | VERBOSE (default: NORMAL)
- **LOG_TO_FILE**: Write logs to files (true) or stdout only (false)

**Jira Integration** (optional):
- **JIRA_URL**: Jira instance URL (e.g., https://yourorg.atlassian.net)
- **JIRA_USERNAME**: Jira email address
- **JIRA_API_TOKEN**: Jira API token (create at Jira → Account Settings → Security)
- **JIRA_PROJECTS_FILTER**: Project key for tickets (e.g., DEVOPS, INFRA)
- **JIRA_READ_ONLY**: Set to "true" for testing (prevents ticket creation)

**Microsoft Teams** (optional):
- **TEAMS_WEBHOOK_URL**: Incoming webhook URL from Teams channel
- **TEAMS_NOTIFICATIONS_ENABLED**: Enable/disable cycle summaries (true/false)

**GitHub Configuration** (optional):
- **GITHUB_DEFAULT_ORG**: Organization for issue tracking
- **GITHUB_INCIDENT_REPO**: Repository for infrastructure incidents
- **GITHUB_TOOLSETS**: Comma-separated toolsets to enable

### Model Selection Strategy

- **Haiku**: Fast, cost-effective for routine diagnostics and cost analysis
- **Sonnet**: Balanced performance for complex analysis and safety-critical operations
- **Opus**: Maximum capability for the most complex issues (optional)

## Usage

### Local Development (Python)

```bash
# Run daemon directly
python monitor_daemon.py

# View logs
tail -f /tmp/eks-monitoring-daemon.log
tail -f /tmp/claude-k8s-agent-actions.log
ls -la /tmp/eks-monitoring-reports/
```

### Docker (Recommended for Production)

```bash
# Build image
./build.sh

# Run with docker-compose (recommended)
docker compose up -d

# View logs
docker compose logs -f

# Stop daemon
docker compose down

# Rebuild after changes
docker compose build
docker compose up -d
```

**Docker Prerequisites:**
- Docker socket access (for Atlassian MCP server)
- Kubeconfig mounted at `/root/.kube/config`
- Environment variables in `.env` file

### Deploy to AWS ECR

```bash
# Build and push to ECR
./deploy-to-ecr.sh v1.0.0

# This will:
# 1. Create ECR repository (if needed)
# 2. Build AMD64 image for EKS
# 3. Tag and push to ECR
# 4. Verify images in repository
```

**ECR Configuration:**
- Registry: `082902060548.dkr.ecr.us-east-1.amazonaws.com`
- Repository: `eks-monitoring-agent`
- Platform: `linux/amd64` (for EKS nodes)

### Kubernetes Deployment (GitOps-Ready)

**Key Innovation: ConfigMap-Driven Agent Behavior** 🎯

All agent configuration is managed via **ConfigMaps and External Secrets** - update behavior via Git without rebuilding images!

```bash
# Deploy to EKS
kubectl apply -f k8s/

# Verify
kubectl get pods -n eks-monitoring
kubectl logs -f deployment/eks-monitoring-agent -n eks-monitoring
```

**What's GitOps-Managed:**

| Component | Type | Hot-Reload | Update Method |
|-----------|------|------------|---------------|
| API Keys, Tokens | ExternalSecret | ❌ | Update AWS Secrets Manager → Restart pod |
| Model Names, Check Interval | ConfigMap (`agent-config`) | ❌ | Edit ConfigMap in Git → Restart pod |
| **Cluster Context (CLAUDE.md)** | ConfigMap (`cluster-context`) | **✅ YES** | **Edit in Git → Auto-applies next cycle** |
| Subagent Definitions | ConfigMap (`subagents`) | ❌ | Edit in Git → Restart pod |
| Hooks Config (settings.json) | ConfigMap (`settings`) | ❌ | Edit in Git → Restart pod |

**GitOps Workflow Example:**
```bash
# Add new namespace to monitor (NO IMAGE REBUILD!)
vi k8s/configmaps/cluster-context.yaml
# Add "artemis-prod" under Critical Application Namespaces

git commit -m "Monitor artemis-prod namespace"
git push

# ArgoCD syncs ConfigMap (30 seconds)
# Next monitoring cycle picks up change (< 15 minutes)
# NO POD RESTART NEEDED! ✨
```

**See:** `k8s/GITOPS-SETUP.md` for complete GitOps workflow and environment overlays

## Safety Features

### Safety Hooks

The system includes multiple safety layers that intercept tool calls **before execution**:

1. **Safety Validator** (`.claude/hooks/safety_validator.py`)
   - Blocks dangerous operations (namespace deletion, PV deletion)
   - Validates operations on protected namespaces (kube-system, production)
   - Prevents bulk deletions (`--all-namespaces`, `-A`)
   - Blocks GitHub commits with secrets in filename

2. **Action Logger** (`.claude/hooks/action_logger.py`)
   - Logs all tool usage for audit trail
   - Creates timestamped action log at `/tmp/claude-k8s-agent-actions.log`
   - Respects `LOG_TO_FILE` setting (can be disabled for stdout-only mode)

3. **Teams Notifier** (`.claude/hooks/teams_notifier.py`)
   - **Hook notifications**: Pod deletions, restarts, scaling operations (real-time)
   - **Filtered**: Blocks ALL read-only operations (pods_list, events_list, jira_search, etc.)
   - **Anti-spam**: Does NOT notify on diagnostic queries (only actual actions)
   - **Cycle summaries**: Sent by orchestrator after cycle completes (separate from hook)

### Approved Auto-Remediation

As defined in `.claude/CLAUDE.md` (for DEV clusters - more permissive than production):

**Safe Operations:**
- Rolling restarts of deployments with **2+ replicas** (non-disruptive)
- Clear Failed/Evicted pods in any namespace
- Scale deployments by ±2 replicas
- Pod deletions in non-system namespaces (karpenter, datadog-operator-dev, etc.)

**Still Blocked:**
- Namespace deletions (requires human approval)
- PersistentVolume deletions (data loss risk)
- Operations on `kube-system` namespace (safety hooks enforce)

### Escalation Criteria

Human approval required for:
- Any operation on `kube-system` namespace
- PersistentVolume or PersistentVolumeClaim deletion
- More than 5 pods failing in same namespace
- Single-replica deployments (restart would cause downtime)

## Subagents

### k8s-diagnostics (Haiku - Fast & Efficient)
**Key Innovation: Bulk Query Strategy**
- Uses `pods_list(all_namespaces=true)` for **single-call cluster-wide checks**
- Eliminates timeout issues on large clusters (40+ nodes, 20+ namespaces)
- Filters unhealthy pods in-memory (restarts, failures, pending)
- Targeted deep-dive only on problematic pods
- **Performance**: 20+ namespace checks in <30 seconds vs 3+ minutes before

### k8s-remediation (Sonnet - Safety-Critical)
- Rolling restarts via deployment annotation patching
- **Safety constraint**: Only deployments with 2+ replicas (zero-downtime)
- Uses `kubectl.kubernetes.io/restartedAt` annotation for Kubernetes-native restart
- Validates against approved auto-remediation rules in CLAUDE.md
- Respects namespace protection (kube-system, production blocked)

### k8s-log-analyzer (Sonnet - Complex Analysis)
- Retrieves pod logs with `previous: true` for CrashLoopBackOff
- Pattern detection for common errors (OOMKilled, ImagePullBackOff, startup failures)
- Timeline correlation with Kubernetes events
- Root cause reports with specific remediation recommendations

### k8s-cost-optimizer (Haiku - Cost-Effective)
- Resource utilization analysis via `pods_top`
- Identifies over/under-provisioned workloads
- Calculates potential cost savings
- Right-sizing recommendations with specific resource values

### k8s-github (Sonnet - Professional)
- **Supporting role**: Deployment correlation (not primary incident tracking)
- Finds recent commits/PRs that may have caused issues
- Creates configuration change PRs (requires human review)
- Code change analysis for Jira ticket context

### k8s-jira (Sonnet - Smart Ticket Management)
**Key Features: Anti-Spam & Intelligent Filtering**
- **24-hour comment rule**: Only adds comments if (24+ hours since last update OR status changed) AND significant change detected
- **Significant change threshold**: 10+ restarts, status change, new errors, remediation attempted
- **Result**: Maximum 1-2 comments per day (not 96!) for ongoing issues
- **Ticket filtering**: Only creates tickets for CRITICAL severity (skips CPU/memory warnings)
- **Duplicate prevention**: Always searches before creating (JQL: `project = DEVOPS AND status != Closed AND summary ~ '[cluster] component'`)
- **Structured format**: Includes diagnostic findings, root cause, remediation attempts

## MCP Integration

The agent uses **3 MCP servers** for external system operations:

### Kubernetes MCP Server (Go Binary)
**Structured cluster operations** - no kubectl required:
- `mcp__kubernetes__pods_list`: List pods with filters (supports `all_namespaces: true` for bulk queries)
- `mcp__kubernetes__pods_get`: Get pod details
- `mcp__kubernetes__pods_log`: Retrieve pod logs (supports `previous: true` for crashed containers)
- `mcp__kubernetes__pods_top`: Resource usage metrics
- `mcp__kubernetes__events_list`: Cluster events
- `mcp__kubernetes__nodes_list`: Node status
- `mcp__kubernetes__resources_create_or_update`: Update resources (used for rolling restarts)

**Configuration:**
- Set `K8S_MCP_READ_ONLY=true` to block all write operations (testing mode)
- Set `K8S_MCP_DISABLE_DESTRUCTIVE=true` to allow create but block delete/update

### GitHub MCP Server (Go Binary)
**GitHub API operations** - deployment correlation and PRs:
- `mcp__github__search_code`: Find deployment commits and config changes
- `mcp__github__list_commits`: Correlate deployments with incidents
- `mcp__github__get_file_contents`: Retrieve deployment manifests
- `mcp__github__create_pull_request`: Config change PRs (requires human approval)
- `mcp__github__list_pull_requests`: Find recent deployments

**Note**: GitHub issue creation is **deprecated** - Jira is primary incident tracking.

### Atlassian MCP Server (Docker Container)
**Jira ticket management** - automatic incident tracking:
- `mcp__atlassian__jira_search`: Find existing tickets (prevents duplicates)
- `mcp__atlassian__jira_create_issue`: Create incident tickets
- `mcp__atlassian__jira_get_issue`: Retrieve ticket details and last comments
- `mcp__atlassian__jira_add_comment`: Smart commenting (only on significant changes)
- `mcp__atlassian__jira_transition_issue`: Status transitions (Open → In Progress → Resolved)
- `mcp__atlassian__jira_link_to_epic`: Link tickets to epics
- `mcp__atlassian__jira_create_issue_link`: Relate incidents

**Smart Features:**
- Compares current metrics vs last comment before adding updates
- Only creates tickets for CRITICAL severity (skips performance warnings)
- JQL syntax validation (project key, no ORDER BY clauses)
- Supports both Jira Cloud and Data Center

## Development

### Project Structure

```
eks-monitoring-agent/
├── .claude/
│   ├── CLAUDE.md              # Cluster context and SOPs
│   ├── settings.json          # Hooks configuration
│   ├── agents/                # Subagent definitions
│   │   ├── k8s-diagnostics.md
│   │   ├── k8s-remediation.md
│   │   ├── k8s-log-analyzer.md
│   │   ├── k8s-cost-optimizer.md
│   │   └── k8s-github.md
│   └── hooks/                 # Safety hooks
│       ├── safety_validator.py
│       ├── action_logger.py
│       └── teams_notifier.py
├── monitor_daemon.py          # Main orchestrator
├── pyproject.toml
├── requirements.txt
└── README.md
```

### Adding Custom Rules

Edit `.claude/CLAUDE.md` to add:
- New known issues and patterns
- Custom escalation criteria
- Additional approved auto-remediation actions
- Team-specific SOPs

### Customizing Subagents

Subagent definitions are in `.claude/agents/`. Modify:
- Tool permissions
- System prompts
- Model selection
- Behavior guidelines

## Troubleshooting

### MCP Connection Issues

**Kubernetes/GitHub MCP not starting:**
```bash
# Test MCP servers manually
npx -y @modelcontextprotocol/server-kubernetes
npx -y @modelcontextprotocol/server-github

# Verify Node.js is installed
node --version  # Should be v18+
```

**Atlassian MCP not connecting:**
```bash
# Check if Docker is running
docker ps

# Check for orphaned containers
docker ps -a | grep mcp-atlassian

# Clean up orphaned containers
docker rm -f $(docker ps -a -q --filter "ancestor=ghcr.io/sooperset/mcp-atlassian:latest")

# Test Atlassian MCP manually
./bin/run-atlassian-mcp.sh

# Check logs
docker logs mcp-atlassian-xxxxx
```

### Jira Integration Issues

**"You do not have permission to create issues in this project":**
- Verify `JIRA_API_TOKEN` has "Create Issues" permission in the DEVOPS project
- Contact Jira admin to grant permissions to `JIRA_USERNAME`
- Test token: `curl -u email:token https://yourorg.atlassian.net/rest/api/2/myself`

**"Error in the JQL Query: Expecting ')' but got 'ORDER'":**
- k8s-jira agent was generating invalid JQL (now fixed)
- Do NOT add ORDER BY clauses in JQL - MCP server handles sorting
- Restart daemon to load updated k8s-jira.md configuration

**Jira tickets getting 96 comments per day:**
- Old behavior before smart commenting fix
- Upgrade to latest k8s-jira.md configuration
- Smart commenting only updates when metrics change significantly

### Teams Notification Spam

**Getting 50+ "Card - access it on..." messages per cycle:**
- Old behavior before hook filtering fix
- Update `.claude/hooks/teams_notifier.py` to latest version
- Hook now blocks ALL read-only operations (pods_list, events_list, etc.)
- Restart daemon to load updated hook

### Diagnostic Timeouts

**"NOT CHECKED - Time constraints" for many namespaces:**
- Old behavior before bulk query optimization
- Update `.claude/agents/k8s-diagnostics.md` to use bulk query strategy
- Agent now checks ALL namespaces in one call
- Restart daemon to load updated configuration

### Hook Execution Errors

Check hook permissions:
```bash
chmod +x .claude/hooks/*.py

# Test hook manually
echo '{"tool_name":"mcp__kubernetes__pods_list","tool_input":{"namespace":"default"}}' | \
  python .claude/hooks/teams_notifier.py
```

### Authentication Issues

Ensure environment variables are set:
```bash
echo $ANTHROPIC_API_KEY
echo $GITHUB_PERSONAL_ACCESS_TOKEN  # Note: Not GITHUB_TOKEN
echo $JIRA_API_TOKEN

# Verify .env is loaded
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('API Key:', os.getenv('ANTHROPIC_API_KEY')[:10] + '...')"
```

### Configuration Not Loading

**Subagent instructions not being followed:**
- Configuration files in `.claude/agents/*.md` are loaded at daemon startup
- Changes require daemon restart to take effect
- Verify `setting_sources=["project"]` in monitor_daemon.py:250

**CLAUDE.md changes not applied:**
- `.claude/CLAUDE.md` is reloaded on EVERY monitoring cycle (no restart needed)
- Wait for next cycle to see changes
- Check daemon logs for "Cluster: [name]" to confirm context loaded

## Monitoring and Alerts

### Logs Location

**When `LOG_TO_FILE=true` (default):**
- Daemon log: `/tmp/eks-monitoring-daemon.log`
- Action audit: `/tmp/claude-k8s-agent-actions.log`
- Cycle reports: `/tmp/eks-monitoring-reports/cycle-NNNN-YYYYMMDD-HHMMSS.txt`

**When `LOG_TO_FILE=false` (Datadog mode):**
- Daemon log: **stdout** (capture with container/systemd logs)
- Action audit: **stderr** (no file created)
- Cycle reports: `/tmp/eks-monitoring-reports/` (still saved)

**Viewing Logs:**
```bash
# Real-time daemon logs
tail -f /tmp/eks-monitoring-daemon.log

# OR for stdout-only mode
docker compose logs -f                    # Docker
journalctl -u eks-monitoring -f           # systemd

# Action audit trail
tail -f /tmp/claude-k8s-agent-actions.log

# List all cycle reports
ls -lah /tmp/eks-monitoring-reports/

# View latest cycle report
cat /tmp/eks-monitoring-reports/cycle-*.txt | tail -100
```

### Microsoft Teams Integration

**Two Types of Notifications:**

#### 1. Hook-Based Notifications (Real-Time Actions)
Sent when agent performs **actual cluster operations**:
- ✅ Pod deletions
- ✅ Scaling operations
- ✅ Deployment restarts
- ✅ Jira ticket creation
- ❌ **NOT sent** for read-only queries (pods_list, events_list, etc.)

#### 2. Cycle Summary Notifications (Every Cycle)
Sent **once per monitoring cycle** with comprehensive details:

**Sections Included:**
- **Cycle Overview**: Overall health status, timestamp, issue count
- **Critical Issues**: Detailed list with namespace, component, severity, restart count, root cause
- **Jira Tickets**: Ticket keys, summaries, actions (created/updated), clickable links
- **Actions Taken**: All diagnostic steps, remediation attempts, report locations

**Color Coding:**
- 🔴 **Red (CRITICAL)**: Service outages, multiple failures
- 🟠 **Orange (DEGRADED)**: Warnings, single failures
- 🟢 **Green (HEALTHY)**: All systems operational

**Example Notification:**
```
🔍 Monitoring Cycle #1 Complete
Cluster: dev-eks

Cluster Health: CRITICAL
Issues Detected: 3

🚨 Critical Issues (3 detected)
1. kube-system/aws-cluster-autoscaler
   - Severity: CRITICAL
   - Restarts: 291
   - Root Cause: Version v1.20.0 incompatible with Kubernetes 1.32

🎫 Jira Tickets (3 tickets)
DEVOPS-1234: [dev-eks] aws-cluster-autoscaler: CrashLoopBackOff
- Action: Created
[View DEVOPS-1234] ← Clickable button
```

**Configuration:**
```bash
TEAMS_WEBHOOK_URL=https://yourorg.webhook.office.com/webhookb2/...
TEAMS_NOTIFICATIONS_ENABLED=true  # Enable cycle summaries
```

## Recent Improvements & Best Practices

### Performance Optimizations (October 2025)

**Bulk Query Strategy** (k8s-diagnostics):
- **Before**: 20+ sequential namespace checks → timeout after 6-8 namespaces
- **After**: Single `pods_list(all_namespaces=true)` → complete cluster scan in <30 seconds
- **Impact**: 90% reduction in MCP calls, full cluster visibility

**Smart Jira Commenting** (k8s-jira):
- **Problem**: 96 comments/day per ticket at 15-minute cycles
- **Solution**: Only comment if (24+ hours since last update OR status changed) AND significant change (10+ restarts, new errors, remediation)
- **Strict 24-hour rule**: Maximum 1 comment per 24 hours for ongoing issues
- **Exception**: Status changes (resolved/fixed) can comment immediately
- **Impact**: 99% reduction in Jira noise (1-2 comments/day instead of 96)

**Teams Notification Filtering**:
- **Problem**: 50+ notifications per cycle (one per MCP tool call)
- **Solution**: Block ALL read-only operations in hook, send ONE cycle summary
- **Impact**: 98% reduction in Teams spam

### Best Practices for Production

**Recommended Configuration:**
```bash
CHECK_INTERVAL=900              # 15 minutes (sweet spot for cost vs responsiveness)
DIAGNOSTIC_MODEL=claude-sonnet-4-20250514  # Upgraded from Haiku for accuracy
LOG_LEVEL=NORMAL                # Balance between verbosity and signal
LOG_TO_FILE=false               # Stdout-only for Datadog integration
TEAMS_NOTIFICATIONS_ENABLED=true  # Rich cycle summaries
JIRA_READ_ONLY=false            # Enable automatic ticket management
```

**Cluster Context Tuning** (`.claude/CLAUDE.md`):
- List ALL critical namespaces (infrastructure + applications)
- Document known recurring issues (prevents duplicate analysis)
- Define clear escalation criteria
- Keep approved auto-remediation rules updated

### Deprecations

**GitHub Issue Tracking** → **Jira Primary**
- GitHub issue creation in k8s-github subagent is now **supporting role only**
- Use for deployment correlation and code analysis
- Jira is the primary incident tracking system (better SLA management)

**Per-Namespace Sequential Checks** → **Bulk Query Strategy**
- Old approach caused timeouts on large clusters
- Now only used as fallback if bulk query fails

## Contributing

1. Follow the implementation plan in `docs/implementation-plan.md`
2. Test changes with non-production clusters first
3. Update `.claude/CLAUDE.md` with new patterns or rules
4. Add tests for new subagents or hooks
5. Document performance impacts in this README

## Security Considerations

- Never commit `.env` file with real credentials
- Restrict GitHub token permissions to minimum required
- Review all auto-remediation actions before enabling
- Use read-only mode initially to validate behavior
- Monitor action logs regularly

## License

MIT

## References

- [Claude Agent SDK Documentation](https://docs.claude.com/en/api/agent-sdk/python)
- [Kubernetes MCP Server](https://github.com/modelcontextprotocol/servers/tree/main/src/kubernetes)
- [GitHub MCP Server](https://github.com/modelcontextprotocol/servers/tree/main/src/github)
- [Implementation Plan](docs/implementations/kubernetes-sre-agent-implementation-plan.md)
