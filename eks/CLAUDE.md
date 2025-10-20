# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is an **EKS Monitoring Agent** - an autonomous Kubernetes monitoring system built with the Claude Agent SDK. It uses a multi-agent architecture with specialized subagents to continuously monitor, diagnose, and remediate issues in EKS clusters.

## Key Technologies

- **Claude Agent SDK** - Core framework for building the multi-agent system
- **Python 3.10+** - Primary language
- **MCP (Model Context Protocol)** - External tool integration layer
  - Kubernetes MCP Server - Structured K8s operations (replaces kubectl)
  - GitHub MCP Server - GitHub API operations
- **Node.js** - Required for MCP server runtime

## Installation & Setup

```bash
# Install Python dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with API keys: ANTHROPIC_API_KEY, GITHUB_TOKEN (optional)

# Test MCP connectivity (requires Node.js)
npx -y @modelcontextprotocol/server-kubernetes
npx -y @modelcontextprotocol/server-github
```

## Running the System

```bash
# Start monitoring daemon (once implemented in Phase 4)
python monitor_daemon.py

# View logs
tail -f /tmp/eks-monitoring-daemon.log        # Main daemon log
tail -f /tmp/claude-k8s-agent-actions.log     # Action audit trail
ls -la /tmp/eks-monitoring-reports/           # Diagnostic reports
```

## Architecture Overview

### Multi-Agent System

The system uses a **main orchestrator** (`monitor_daemon.py`) that coordinates **5 specialized subagents**:

```
Main Orchestrator (ClaudeSDKClient with persistent state)
├── k8s-diagnostics    → Health checks, issue detection
├── k8s-remediation    → Safe cluster fixes
├── k8s-log-analyzer   → Root cause analysis from logs
├── k8s-cost-optimizer → Resource utilization analysis
└── k8s-github         → Incident tracking, config PRs
```

### Agent Communication Pattern

1. **Orchestrator** invokes subagent via `Task` tool
2. **Subagent** runs in isolated context with limited tools
3. **Subagent** returns structured report
4. **Orchestrator** decides next action based on report

Subagents cannot see each other's context - only their final outputs.

### Configuration Architecture

The `.claude/` directory contains all agent configuration:

```
.claude/
├── CLAUDE.md         # Cluster-specific context (namespaces, SOPs, known issues)
├── settings.json     # Hooks configuration (safety validators, loggers)
├── agents/           # Subagent definitions (markdown files)
│   ├── k8s-diagnostics.md
│   ├── k8s-remediation.md
│   ├── k8s-log-analyzer.md
│   ├── k8s-cost-optimizer.md
│   └── k8s-github.md
└── hooks/            # Safety hooks (Python scripts)
    ├── safety_validator.py
    ├── action_logger.py
    └── teams_notifier.py
```

**Critical**: `.claude/CLAUDE.md` acts as "institutional memory" - it's loaded into the orchestrator's context on every monitoring cycle.

## MCP vs Bash Commands

**ALWAYS prefer MCP tools over Bash/kubectl commands:**

```python
# ❌ OLD WAY (avoid)
await client.query("Run: kubectl get pods -n production")

# ✅ NEW WAY (use this)
await client.query("Use mcp__kubernetes__pods_list with namespace=production")
```

**Why MCP?**
- Type-safe structured input/output
- Better error handling
- No shell injection vulnerabilities
- Easier to validate in safety hooks
- Consistent across Kubernetes versions

### MCP Tool Naming Convention

`mcp__<server_name>__<tool_name>`

Examples:
- `mcp__kubernetes__pods_list`
- `mcp__kubernetes__pods_delete`
- `mcp__github__create_issue`
- `mcp__github__create_pull_request`

## Safety Hooks System

### How Hooks Work

Hooks intercept tool calls **before execution**:

1. Subagent calls tool (e.g., `mcp__kubernetes__pods_delete`)
2. SDK pauses and triggers `PreToolUse` hook
3. Hook script receives tool data via stdin (JSON)
4. Hook returns decision via stdout (JSON)
5. SDK either allows or blocks based on response

### Hook Response Format

**Allow:**
```json
{}
```

**Deny:**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Blocked: Dangerous operation"
  }
}
```

### Hook Chain Execution

Multiple hooks run in sequence. If any denies, execution stops:
1. `safety_validator.py` - Blocks dangerous operations
2. `action_logger.py` - Logs to audit trail
3. `teams_notifier.py` - Sends Teams notification

### Protected Resources

Safety validator blocks:
- Namespace deletion
- PersistentVolume deletion
- Operations on `kube-system`, `production`, `prod`
- Bulk deletions (`--all-namespaces`, `-A`)
- GitHub commits with secrets in filename

## Model Selection Strategy

Each agent can use different models (configured via environment variables):

| Agent | Default Model | Rationale |
|-------|--------------|-----------|
| Orchestrator | Sonnet | Needs context management, decision-making |
| Diagnostics | Haiku | Fast, routine health checks |
| Remediation | Sonnet | Safety-critical, requires careful reasoning |
| Log Analyzer | Sonnet | Complex pattern recognition |
| Cost Optimizer | Haiku | Arithmetic calculations, cost-effective |
| GitHub | Sonnet | Professional communication, PR writing |

**Change models via environment variables** - no code rebuild needed:
```bash
export DIAGNOSTIC_MODEL=claude-sonnet-4-20250514  # Upgrade to Sonnet
export COST_OPTIMIZER_MODEL=claude-haiku-4-20250514  # Use Haiku
```

## Subagent Development

### Creating a New Subagent

1. Create `.claude/agents/my-subagent.md`:
```markdown
---
name: my-subagent
description: When to use this subagent (orchestrator decides based on this)
tools: Read, Write, mcp__kubernetes__pods_list
model: $MY_SUBAGENT_MODEL
---

You are an expert [specialization]...

[Detailed instructions, tool usage examples, output format]
```

2. Add model environment variable to `.env`:
```bash
MY_SUBAGENT_MODEL=claude-sonnet-4-20250514
```

3. Register tools in orchestrator's `allowed_tools`:
```python
allowed_tools=["Task", "mcp__kubernetes__pods_list", ...]
```

4. Main orchestrator will automatically discover subagent via `setting_sources=["project"]`

### Subagent Best Practices

- **Focused responsibility**: Each subagent should have ONE clear purpose
- **Structured output**: Use YAML/JSON format for subagent reports
- **Tool isolation**: Only grant minimum necessary tools
- **MCP over Bash**: Always use MCP tools for Kubernetes operations
- **No cross-subagent state**: Subagents cannot share context, only outputs

## Claude Agent SDK Patterns

### ClaudeSDKClient vs query()

```python
# One-off task (no memory)
from claude_agent_sdk import query
result = await query("Analyze this cluster")

# Continuous conversation (stateful)
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
async with ClaudeSDKClient(options=options) as client:
    await client.query(prompt)
    async for message in client.receive_response():
        # Process messages
```

**For this project**: Use `ClaudeSDKClient` in orchestrator to maintain context across monitoring cycles.

### Loading Configuration

```python
options = ClaudeAgentOptions(
    model=os.getenv("ORCHESTRATOR_MODEL", "claude-sonnet-4-20250514"),

    # CRITICAL: Loads .claude/CLAUDE.md, agents/, settings.json
    setting_sources=["project"],

    # MCP server configuration
    mcp_servers={
        "kubernetes": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-kubernetes"]
        },
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", "")}
        }
    },

    # Main orchestrator needs Task tool to invoke subagents
    allowed_tools=["Task", "Read", "Write", "mcp__kubernetes__*", "mcp__github__*"],

    # Autonomous operation (or use "manual" for approval prompts)
    permission_mode="acceptAll",
)
```

## Implementation Status

**Current Phase: Phase 1 Complete** ✅

The project follows a phased implementation plan in `docs/implementations/kubernetes-sre-agent-implementation-plan.md`:

- ✅ **Phase 1**: Project structure, dependencies, configuration files
- ⬜ **Phase 2**: Subagent definitions (`.claude/agents/*.md`)
- ⬜ **Phase 3**: Safety hooks (`.claude/hooks/*.py`)
- ⬜ **Phase 4**: Main orchestrator (`monitor_daemon.py`)
- ⬜ **Phase 5**: Testing and deployment

When implementing remaining phases, follow the detailed specifications in the implementation plan.

## Customizing for Your Cluster

### Update Cluster Context

Edit `.claude/CLAUDE.md` (NOT this file - that's the cluster-specific context):
- Cluster name, region, version
- Critical namespaces to monitor
- Known recurring issues
- Team-specific SOPs
- Escalation criteria
- Approved auto-remediation actions

This file is loaded on every monitoring cycle - changes take effect immediately without restarting the daemon.

### Adjust Safety Rules

Edit `.claude/hooks/safety_validator.py`:
- Add/remove protected namespaces
- Define dangerous command patterns
- Set validation rules for MCP operations

### Configure Notifications

Set `TEAMS_WEBHOOK_URL` in `.env` for Microsoft Teams alerts on:
- Pod deletions
- Scaling operations
- Deployment restarts
- Critical incidents

## Troubleshooting

### MCP Connection Failures

```bash
# Verify Node.js is installed
node --version

# Test MCP servers manually
npx -y @modelcontextprotocol/server-kubernetes
npx -y @modelcontextprotocol/server-github
```

### Hook Execution Errors

```bash
# Ensure hooks are executable
chmod +x .claude/hooks/*.py

# Test hook manually
echo '{"tool_name":"Bash","tool_input":{"command":"kubectl get pods"}}' | python .claude/hooks/safety_validator.py
```

### Agent Not Loading Context

Verify `setting_sources=["project"]` in `ClaudeAgentOptions` - this loads `.claude/CLAUDE.md` and agent definitions.

## Security Considerations

- **Never commit `.env`** - contains API keys
- **GitHub token**: Minimum scopes: `repo` (private) or `public_repo` (public only)
- **Test with read-only mode first**: Set `permission_mode="manual"` for approval prompts
- **Monitor action logs**: `/tmp/claude-k8s-agent-actions.log` contains audit trail
- **Start with non-production cluster**: Validate behavior before production deployment

## References

- [Claude Agent SDK Python Docs](https://docs.claude.com/en/api/agent-sdk/python)
- [Kubernetes MCP Server](https://github.com/modelcontextprotocol/servers/tree/main/src/kubernetes)
- [GitHub MCP Server](https://github.com/modelcontextprotocol/servers/tree/main/src/github)
- [Implementation Plan](docs/implementations/kubernetes-sre-agent-implementation-plan.md)
