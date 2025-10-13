# EKS Monitoring Agent

An autonomous Kubernetes monitoring system powered by Claude Agent SDK that continuously monitors your EKS cluster and automatically remediates common issues.

## Features

- **Continuous Monitoring**: Automatically detects cluster health issues
- **Intelligent Diagnostics**: Uses specialized subagents for root cause analysis
- **Safe Remediation**: Human-approved actions with safety hooks
- **Cost Optimization**: Identifies over-provisioned resources
- **GitHub Integration**: Creates incident issues and configuration PRs
- **MCP Integration**: Uses Kubernetes MCP and GitHub MCP for structured operations

## Architecture

```
Main Orchestrator (monitor_daemon.py)
├── Diagnostic Subagent (Kubernetes health checks)
├── Remediation Subagent (Fixes common issues)
├── Log Analyzer Subagent (Root cause analysis)
├── Cost Optimizer Subagent (Resource optimization)
└── GitHub Subagent (Incident tracking and PRs)
```

## Prerequisites

- Python 3.10+
- Node.js (for MCP servers)
- kubectl configured with cluster access
- Anthropic API key
- GitHub token (optional, for GitHub operations)

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
- Critical namespaces
- Known issues and patterns
- Standard operating procedures
- Escalation criteria

## Configuration

### Environment Variables

See `.env.example` for all configuration options:

- **ANTHROPIC_API_KEY**: Required for Claude API access
- **ORCHESTRATOR_MODEL**: Model for main orchestrator (default: sonnet)
- **DIAGNOSTIC_MODEL**: Model for diagnostics (default: haiku)
- **REMEDIATION_MODEL**: Model for remediation (default: sonnet)
- **LOG_ANALYZER_MODEL**: Model for log analysis (default: sonnet)
- **COST_OPTIMIZER_MODEL**: Model for cost optimization (default: haiku)
- **GITHUB_AGENT_MODEL**: Model for GitHub operations (default: sonnet)
- **TEAMS_WEBHOOK_URL**: Optional Microsoft Teams notifications
- **CHECK_INTERVAL**: Monitoring interval in seconds (default: 300)
- **GITHUB_TOKEN**: Optional GitHub token for issue/PR creation

### Model Selection Strategy

- **Haiku**: Fast, cost-effective for routine diagnostics and cost analysis
- **Sonnet**: Balanced performance for complex analysis and safety-critical operations
- **Opus**: Maximum capability for the most complex issues (optional)

## Usage

### Run the Monitoring Daemon

```bash
python monitor_daemon.py
```

The daemon will:
1. Perform initial cluster health check
2. Monitor cluster every CHECK_INTERVAL seconds
3. Automatically remediate approved issues
4. Create GitHub issues for incidents (if configured)
5. Log all actions to `/tmp/eks-monitoring-daemon.log`

### View Logs

```bash
# Daemon logs
tail -f /tmp/eks-monitoring-daemon.log

# Action audit log
tail -f /tmp/claude-k8s-agent-actions.log

# Monitoring reports
ls -la /tmp/eks-monitoring-reports/
```

## Safety Features

### Safety Hooks

The system includes multiple safety layers:

1. **Safety Validator** (`.claude/hooks/safety_validator.py`)
   - Blocks dangerous operations (namespace deletion, PV deletion)
   - Validates operations on protected namespaces
   - Prevents bulk deletions

2. **Action Logger** (`.claude/hooks/action_logger.py`)
   - Logs all tool usage for audit trail
   - Creates timestamped action log

3. **Teams Notifier** (`.claude/hooks/teams_notifier.py`)
   - Sends real-time notifications to Microsoft Teams
   - Alerts on critical operations

### Approved Auto-Remediation

As defined in `.claude/CLAUDE.md`:
- Restart single pods in non-production namespaces
- Clear Failed/Evicted pods
- Scale deployments by ±2 replicas

### Escalation Criteria

Human approval required for:
- Operations on `kube-system` namespace
- PersistentVolume or PersistentVolumeClaim deletion
- More than 5 pods failing in same namespace

## Subagents

### Diagnostic Subagent
- Uses Kubernetes MCP tools for health checks
- Detects CrashLoopBackOff, OOMKilled, Pending pods
- Analyzes node and cluster-level issues
- Provides structured diagnostic reports

### Remediation Subagent
- Executes safe remediation actions
- Uses Kubernetes MCP for resource operations
- Validates actions against safety rules
- Logs all changes with audit trail

### Log Analyzer Subagent
- Retrieves and analyzes pod logs using Kubernetes MCP
- Identifies error patterns and root causes
- Correlates logs with Kubernetes events
- Provides root cause analysis reports

### Cost Optimizer Subagent
- Analyzes resource utilization using Kubernetes MCP
- Identifies over-provisioned and under-provisioned workloads
- Calculates potential cost savings
- Provides right-sizing recommendations

### GitHub Subagent
- Creates incident issues for critical problems
- Updates issues with remediation progress
- Creates PRs for configuration changes
- Searches code for debugging patterns

## MCP Integration

### Kubernetes MCP Server

Provides structured Kubernetes operations:
- `mcp__kubernetes__pods_list`: List pods with filters
- `mcp__kubernetes__pods_get`: Get pod details
- `mcp__kubernetes__pods_log`: Retrieve pod logs
- `mcp__kubernetes__pods_delete`: Delete pods safely
- `mcp__kubernetes__resources_create_or_update`: Update resources
- And more...

### GitHub MCP Server

Provides GitHub operations:
- `mcp__github__list_issues`: List repository issues
- `mcp__github__create_issue`: Create incident issues
- `mcp__github__create_pull_request`: Create config PRs
- `mcp__github__search_code`: Search for patterns
- And more...

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

If MCP servers fail to connect:
```bash
# Test Kubernetes MCP manually
npx -y @modelcontextprotocol/server-kubernetes

# Test GitHub MCP manually
npx -y @modelcontextprotocol/server-github
```

### Hook Execution Errors

Check hook permissions:
```bash
chmod +x .claude/hooks/*.py
```

### Authentication Issues

Ensure environment variables are set:
```bash
echo $ANTHROPIC_API_KEY
echo $GITHUB_TOKEN
```

## Monitoring and Alerts

### Logs Location
- Daemon log: `/tmp/eks-monitoring-daemon.log`
- Action audit: `/tmp/claude-k8s-agent-actions.log`
- Reports: `/tmp/eks-monitoring-reports/`

### Microsoft Teams Integration

Set `TEAMS_WEBHOOK_URL` in `.env` to receive notifications for:
- Pod deletions
- Scaling operations
- Deployment restarts
- Critical incidents

## Contributing

1. Follow the implementation plan in `docs/implementations/kubernetes-sre-agent-implementation-plan.md`
2. Test changes with non-production clusters first
3. Update `.claude/CLAUDE.md` with new patterns or rules
4. Add tests for new subagents or hooks

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
