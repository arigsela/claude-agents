#!/usr/bin/env python3
"""
EKS Monitoring Daemon with Claude Agent SDK

This daemon continuously monitors your EKS cluster and automatically
remediates common issues using specialized subagents.

Architecture:
- Main orchestrator coordinates 6 specialized subagents
- Uses kubectl via Bash tool for cluster operations
- Uses gh CLI via Bash tool for GitHub operations
- No MCP servers (simplified, cost-effective with Haiku)
- Safety hooks validate all operations before execution
- Persistent conversation maintains context across monitoring cycles
"""
import asyncio
import os
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional
# No SDK MCP imports needed - using external MCP servers via npx

# Load .env file FIRST before anything else
env_file = Path(__file__).parent / '.env'
if env_file.exists():
    print(f"Loading environment from: {env_file}")
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
except ImportError:
    print("Error: claude-agent-sdk not installed", file=sys.stderr)
    print("Install with: pip install claude-agent-sdk", file=sys.stderr)
    sys.exit(1)

# Configuration from environment (NOW these will see the .env values!)
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 300))  # 5 minutes default
REPORT_DIR = Path(os.getenv('REPORT_DIR', '/tmp/eks-monitoring-reports'))
LOG_FILE = Path(os.getenv('LOG_FILE', '/tmp/eks-monitoring-daemon.log'))

# Cluster name - read from environment or auto-detect from kubectl
CLUSTER_NAME = os.getenv('CLUSTER_NAME', '')  # User can override in .env

# Kubernetes context - specify which cluster to monitor (for local development)
KUBE_CONTEXT = os.getenv('KUBE_CONTEXT', '')  # User can specify context explicitly

# Log level configuration
# SILENT: No logs (only errors)
# MINIMAL: Only critical events (cycle start/end, errors, completions)
# NORMAL: Standard logging (INFO level)
# VERBOSE: All details including DEBUG (default)
LOG_LEVEL = os.getenv('LOG_LEVEL', 'NORMAL').upper()

# Map log levels to numeric values
LOG_LEVELS = {
    'SILENT': 40,   # ERROR only
    'MINIMAL': 30,  # WARNING and ERROR
    'NORMAL': 20,   # INFO, WARNING, ERROR
    'VERBOSE': 10,  # DEBUG, INFO, WARNING, ERROR
}
CURRENT_LOG_LEVEL = LOG_LEVELS.get(LOG_LEVEL, LOG_LEVELS['NORMAL'])

# File logging configuration
# When false, all logs go to stdout only (for Datadog/external collectors)
# When true, logs written to both stdout and LOG_FILE
LOG_TO_FILE = os.getenv('LOG_TO_FILE', 'true').lower() == 'true'


class ClusterChangeException(Exception):
    """Raised when the monitored cluster changes and conversation state needs reset"""
    pass


class EKSMonitoringDaemon:
    """
    Main orchestrator that coordinates all subagents.

    SDK Concepts Used:
    - ClaudeSDKClient: Persistent conversation across monitoring cycles
    - setting_sources: Loads .claude/CLAUDE.md, agents/, settings.json
    - mcp_servers: Configures Kubernetes, GitHub, and Atlassian MCP servers
    - Task tool: Invokes specialized subagents
    """

    def __init__(self, check_interval: int = CHECK_INTERVAL):
        self.check_interval = check_interval
        self.client: Optional[ClaudeSDKClient] = None
        self.running = False
        self.cycle_count = 0
        self.cluster_name = self._detect_cluster_name()
        self.last_cluster_name = None  # Track cluster changes

        # Ensure directories exist
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _detect_cluster_name(self) -> str:
        """
        Detect cluster name from environment or kubeconfig context.

        Priority:
        1. CLUSTER_NAME environment variable (explicit override)
        2. KUBE_CONTEXT environment variable (use specified context)
        3. Current kubectl context name (auto-detect)
        4. Fallback to 'unknown-cluster'
        """
        # Check environment variable first
        if CLUSTER_NAME:
            return CLUSTER_NAME

        # Check if KUBE_CONTEXT is specified
        context_to_check = KUBE_CONTEXT if KUBE_CONTEXT else None

        # Try to get from kubectl context
        try:
            import subprocess

            # If KUBE_CONTEXT is set, use that; otherwise get current context
            if context_to_check:
                # Use the specified context
                context_name = context_to_check
            else:
                # Get current context
                result = subprocess.run(
                    ['kubectl', 'config', 'current-context'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    context_name = result.stdout.strip()
                else:
                    return 'unknown-cluster'

            # Context might be like "arn:aws:eks:us-east-1:123:cluster/dev-eks"
            # Extract just the cluster name
            if '/' in context_name:
                cluster_name = context_name.split('/')[-1]
            else:
                cluster_name = context_name
            return cluster_name
        except Exception:
            pass  # Fall through to default

        # Fallback
        return 'unknown-cluster'

    def log(self, message: str, level: str = "INFO"):
        """Log message to stdout and optionally to file (respects LOG_LEVEL and LOG_TO_FILE)"""
        # Map string levels to numeric values
        level_map = {
            'DEBUG': 10,
            'INFO': 20,
            'WARN': 30,
            'WARNING': 30,
            'ERROR': 40,
            'CRITICAL': 50,
        }

        msg_level = level_map.get(level.upper(), 20)

        # Skip if below current log level
        if msg_level < CURRENT_LOG_LEVEL:
            return

        timestamp = datetime.now(UTC).isoformat()
        log_entry = f"[{timestamp}] [{level}] {message}"

        # Always print to stdout (for Datadog/external collectors to capture)
        print(log_entry)
        sys.stdout.flush()

        # Optionally write to file (disable for Datadog-only setups)
        if LOG_TO_FILE:
            with open(LOG_FILE, 'a') as f:
                f.write(log_entry + '\n')

    async def initialize_client(self):
        """
        Initialize the Claude SDK client with MCP servers.

        SDK Configuration:
        1. Loads .claude/CLAUDE.md for cluster context (institutional memory)
        2. Loads .claude/agents/*.md for subagent definitions
        3. Loads .claude/settings.json for hooks
        4. Spawns MCP server processes (Kubernetes and GitHub)
        5. Registers tools with mcp__<server>__<tool> naming
        """
        self.log("Initializing Claude Agent SDK client (no MCP servers)...")

        # Get project root directory
        project_root = Path(__file__).parent.absolute()

        # No MCP servers - using direct kubectl via Bash tool
        self.log(f"[DEBUG] Using kubectl via Bash tool (no MCP servers)...", level="INFO")

        # Verify GitHub token is set (for GitHub operations via Bash/gh CLI)
        if not os.getenv('GITHUB_PERSONAL_ACCESS_TOKEN'):
            self.log("WARNING: GITHUB_PERSONAL_ACCESS_TOKEN not set - GitHub operations will fail", level="WARN")

        # Verify Jira credentials are set (optional)
        if not os.getenv('JIRA_URL'):
            self.log("INFO: JIRA_URL not set - Jira integration disabled", level="INFO")

        # Load orchestrator model from environment
        orchestrator_model = os.getenv('ORCHESTRATOR_MODEL', 'claude-sonnet-4-20250514')
        self.log(f"Using orchestrator model: {orchestrator_model}")
        self.log(f"[DEBUG] Creating ClaudeAgentOptions...", level="INFO")

        # Create SDK options
        options = ClaudeAgentOptions(
            model=orchestrator_model,

            # Working directory (where .claude/ is located)
            cwd=str(project_root),

            # CRITICAL: Load .claude/ configuration
            # This loads:
            # - .claude/CLAUDE.md (cluster context - reloaded each cycle!)
            # - .claude/agents/*.md (subagent definitions)
            # - .claude/settings.json (hooks configuration)
            setting_sources=["project"],

            # No MCP servers - using Bash tool for kubectl and gh commands
            mcp_servers={},

            # Tools available to orchestrator and subagents
            allowed_tools=[
                # Core SDK tools
                "Task",        # REQUIRED to invoke subagents
                "Read",        # File reading
                "Write",       # Report generation
                "Grep",        # Pattern searching
                "Bash",        # Shell commands (kubectl, gh CLI)
                "Glob",        # File pattern matching

                # No MCP tools - everything done via Bash (kubectl, gh CLI)
            ],

            # Permission mode
            # - "bypassPermissions": Fully autonomous (hooks still provide safety layer)
            # - "acceptEdits": Accepts edits but may prompt for other operations
            # - "default": Default Claude Code behavior with prompts
            # - "plan": Plan mode only (no execution)
            permission_mode="bypassPermissions",

            # System prompt for main orchestrator
            # This is the "brain" that coordinates everything
            system_prompt=f"""You are the main orchestrator for an EKS cluster monitoring system.

**Monitoring Cluster:** {self.cluster_name}

Your role is to coordinate specialized subagents to maintain cluster health.

## Available Subagents

You have access to 6 specialized subagents (invoke via Task tool):

1. **k8s-diagnostics** (Haiku - fast)
   - Health checks and issue detection
   - Uses Kubernetes MCP tools for cluster analysis
   - Returns structured diagnostic reports

2. **k8s-remediation** (Sonnet - careful)
   - Performs safe rolling restarts of deployments
   - Uses deployment annotation patching (non-disruptive)
   - Only operates on deployments with 2+ replicas

3. **k8s-log-analyzer** (Sonnet - complex)
   - Root cause analysis from pod logs and events
   - Pattern detection and error correlation
   - Timeline analysis

4. **k8s-cost-optimizer** (Haiku - cost-effective)
   - Resource utilization analysis
   - Identifies over/under-provisioned workloads
   - Cost savings recommendations

5. **k8s-github** (Sonnet - professional)
   - Deployment correlation (find recent commits/PRs)
   - Configuration change PRs
   - Code change analysis (for Jira ticket context)

6. **k8s-jira** (Sonnet - professional)
   - Jira incident ticket management
   - Searches for existing tickets before creating
   - Updates tickets with diagnostic findings
   - Links related incidents and epics

## Critical Context: CLAUDE.md

You have access to .claude/CLAUDE.md which contains:
- Critical namespaces to monitor (kube-system, karpenter, datadog-operator-test)
- Known chronic infrastructure failures (AWS LB Controller, Karpenter, Datadog - 35+ days old)
- Standard Operating Procedures (SOPs)
- Escalation criteria (when to alert humans)
- Approved auto-remediation actions (more permissive for test cluster)
- Team contacts

This file is YOUR institutional memory - refer to it frequently!
The cluster name and environment are CRITICAL - use them in all GitHub issues and reports!

## Monitoring Workflow

For each health check cycle:

1. **Start with diagnostics**
   ```
   Use k8s-diagnostics subagent to perform comprehensive health check
   ```

2. **If issues detected:**
   - **For CrashLoopBackOff/OOMKilled**: Invoke k8s-log-analyzer for root cause
   - **For CRITICAL severity ONLY**: Proceed with incident tracking (Jira)
   - **For HIGH severity**: Log and monitor, but do NOT create Jira tickets (warnings only)
   - **Check CLAUDE.md**: Is this a known recurring issue? Any special SOPs?

3. **Determine remediation approach:**
   - **Safe to auto-remediate?** Check CLAUDE.md escalation criteria
   - **Deployment has 2+ replicas?** Safe for rolling restart
   - **Protected namespace?** Never remediate kube-system

4. **Execute remediation (if approved):**
   ```
   Use k8s-remediation subagent to perform rolling restart
   ```

5. **Update tracking:**
   - Update Jira ticket with remediation results and status transition
   - Save diagnostic report to /tmp/eks-monitoring-reports/

6. **Periodic cost analysis:**
   - Every 10th cycle: Invoke k8s-cost-optimizer for resource review

## IMPORTANT RULES

### Safety First
1. **Always start with k8s-diagnostics** - Never skip diagnosis
2. **Never skip log analysis** for CrashLoopBackOff/OOMKilled
3. **Respect escalation criteria** from CLAUDE.md
4. **Safety hooks will block** dangerous operations - trust them
5. **Protected namespaces** (kube-system, kube-public, kube-node-lease, production) have restrictions

### Rolling Restarts
1. **Only deployments with 2+ replicas** (avoid downtime)
2. **Use annotation patching** via mcp__kubernetes__resources_create_or_update
3. **Annotation:** `kubectl.kubernetes.io/restartedAt: "<timestamp>"`
4. **Never delete pods directly** in protected namespaces

### Jira Integration

**⚠️ CRITICAL FILTERING RULE:**
- **ONLY invoke k8s-jira subagent for CRITICAL severity incidents**
- **DO NOT invoke k8s-jira for HIGH, MEDIUM, or LOW severity**
- HIGH severity = warnings/degradation (log in Teams, skip Jira)
- CRITICAL severity = service outages, failures, CrashLoopBackOff with 3+ restarts

**When to create tickets:**
1. **Create tickets for CRITICAL severity ONLY** in DEVOPS project
2. **Always search first** to prevent duplicates
3. **Use structured ticket format** with diagnostic findings
4. **Add comments** only when: (24+ hours since last update OR status changed) AND significant change
5. **Transition status** (Open → In Progress → Resolved)
6. **Never auto-close** tickets (Resolved → Closed requires human verification)

### GitHub Integration (Supporting Role)
1. **Correlate deployments** (find recent commits/PRs that may have caused issues)
2. **Create PRs** for permanent config changes (require human review)
3. **NO issue creation** - Jira is primary incident tracking

### Error Handling
If a subagent fails:
1. Log the failure details
2. Try alternative approach if available
3. Create GitHub issue to track the problem
4. Escalate to humans if critical
5. Never retry dangerous operations

### Context Management
- Each subagent runs in **isolated context**
- Subagents only see **their system prompt** + **your query**
- They **cannot see** each other or main conversation
- Pass diagnostic reports explicitly to downstream subagents

## Output Requirements

After each cycle, provide a summary with TWO sections:

### Section 1: Infrastructure & Application Health Status

Provide a quick health summary of the critical namespaces listed in CLAUDE.md:

**Critical Infrastructure:**
- kube-system: [✅ Healthy / ⚠️ Degraded / ❌ Critical] - [brief status]
- karpenter: [✅ Healthy / ⚠️ Degraded / ❌ Critical] - [brief status]
- datadog-operator-dev: [✅ Healthy / ⚠️ Degraded / ❌ Critical] - [brief status]
- (continue for all critical infrastructure namespaces)

**Critical Applications:**
- artemis-preprod: [✅ Healthy / ⚠️ Degraded / ❌ Critical] - [brief status]
- proteus-*: [✅ Healthy / ⚠️ Degraded / ❌ Critical] - [brief status]
- (continue for all critical application namespaces)

### Section 2: Issues & Actions

```
Cycle #X completed at [timestamp]

Overall Health Status: [HEALTHY|DEGRADED|CRITICAL]

Issues Detected: [count]

1. [SEVERITY] namespace/component-name - Brief description
   Root Cause: [one-line summary]
   Impact: [one-line summary]
   Restarts: [count] | Duration: [time]
   Jira: [TICKET-KEY or "Not created"]

2. [SEVERITY] namespace/component-name - Brief description
   Root Cause: [one-line summary]
   Impact: [one-line summary]

... [repeat for all issues]

Actions Taken:
- [action 1]
- [action 2]

Jira Tickets:
- DEVOPS-1234 (created/updated)

Recommendations:
P0 (Immediate):
  - [action 1]
  - [action 2]

P1 (This Week):
  - [action 1]

Node Status: X/Y Ready

Next Check: [timestamp]
```

**CRITICAL FORMAT REQUIREMENTS for Teams notification parsing:**
1. Each issue MUST start with: "[SEVERITY] namespace/component - description"
2. Sub-details should be indented with 2-3 spaces
3. Use this exact format for best Teams notification rendering
4. **DO NOT include bash commands or tool calls in your text output** - Teams notifications should only show:
   - Health status summaries
   - Issues detected
   - Actions taken (descriptions only, not commands)
   - Recommendations (what to do, not how - commands go in Jira tickets only)
   - Metadata (timestamps, counts)
5. Tool use (Bash, kubectl commands, file writes) happens "behind the scenes" - don't narrate it

Be concise - detailed reports are saved to files.
Remember: You are autonomous but cautious. Safety first, automation second.
"""
        )

        # Create the client
        self.log(f"[DEBUG] Creating ClaudeSDKClient instance...", level="INFO")
        self.client = ClaudeSDKClient(options)
        self.log("Claude SDK client initialized successfully")
        self.log(f"[DEBUG] Client created, entering async context...", level="INFO")

        # Log MCP server configuration
        mcp_summary = []
        if os.getenv('JIRA_URL'):
            mcp_summary.append("atlassian (Docker)")
        self.log(f"MCP servers: None (using Bash for kubectl/gh operations)")

    def send_teams_notification(self, title: str, summary: str, severity: str = "info",
                                critical_issues: list = None, jira_tickets: list = None,
                                actions_taken: list = None, full_summary: str = None,
                                cluster_metrics: dict = None, recommendations: dict = None):
        """
        Send Teams notification for cycle summary or critical issues.

        This is SEPARATE from the hook-based notifications.
        Hook notifications are for individual tool calls (deletions, restarts, etc.)
        This method is for high-level cycle summaries.

        Args:
            title: Notification title
            summary: Brief summary text
            severity: critical|warning|info|success
            critical_issues: List of issue dicts with severity, component, namespace, etc.
            jira_tickets: List of Jira ticket dicts with key, url, summary, action
            actions_taken: List of action description strings
            full_summary: Complete summary text from agent (for parsing additional data)
            cluster_metrics: Dict with node_count, pod_count, healthy_namespaces, degraded_namespaces
            recommendations: Dict with p0, p1, p2 lists of recommendation strings
        """
        teams_webhook = os.getenv('TEAMS_WEBHOOK_URL', '')
        teams_enabled = os.getenv('TEAMS_NOTIFICATIONS_ENABLED', 'false').lower() == 'true'

        if not teams_webhook or not teams_enabled:
            return

        try:
            import requests
            import re  # Import re module for regex parsing

            # Teams themeColor codes
            colors = {
                "critical": "FF0000",  # Red
                "warning": "FFA500",   # Orange
                "info": "36A64F",      # Green
                "success": "36A64F"    # Green
            }

            # Build message sections
            sections = []

            # Executive Summary section (ALWAYS show this first - provides context even if parsing fails)
            exec_summary_text = ""

            # Try multiple patterns to extract issue summary
            # Pattern 1: "Issues Detected: X" followed by detailed issue blocks
            # Look for the full "Issues Detected:" section including all sub-issues
            issues_section_match = re.search(
                r'Issues Detected:\s*(\d+)(?:\s+CRITICAL,\s+\d+\s+WARNINGS?)?.*?\n\n(.*?)(?=\n\n(?:Actions Taken|Jira Ticket|Recommended|GitHub Issues|Next Check)|$)',
                full_summary, re.IGNORECASE | re.DOTALL
            )
            if issues_section_match:
                issue_count_text = issues_section_match.group(1)
                full_issues_text = issues_section_match.group(2).strip()

                # Count actual issues in the text (numbered issues: "1. [SEVERITY]")
                actual_issue_count = len(re.findall(r'\n\d+\.\s*\[(?:CRITICAL|HIGH|MEDIUM)\]', full_issues_text, re.IGNORECASE))

                # Use actual count if found, otherwise use extracted number
                if actual_issue_count > 0:
                    issue_count = str(actual_issue_count)
                else:
                    issue_count = issue_count_text

                # Extract just the issue summaries (first line of each issue)
                # Pattern: starts with number, emoji, or "Root Cause:", or component name
                issue_lines = []
                for line in full_issues_text.split('\n')[:30]:  # First 30 lines
                    line = line.strip()

                    # Skip unwanted lines
                    skip_patterns = [
                        'Command:',           # Bash commands
                        'cat >',              # File operations
                        'kubectl ',           # kubectl commands
                        'echo ',              # Echo commands
                        'EOFMARKER',          # Heredoc markers
                        '========',           # Separator lines
                        'Report Generated',   # Metadata
                        '  -',                # Indented details
                        'Impact:',            # Field labels (keep in details section only)
                        'Started:',
                        'Restart Count:',
                        'Duration:',
                        'Brief:',
                    ]

                    if not line or any(pattern in line for pattern in skip_patterns):
                        continue

                    # Keep main issue lines (numbered or with key status indicators)
                    if line[0].isdigit() and '.' in line[:3]:  # "1. [SEVERITY]" or "1. Component"
                        issue_lines.append(line)
                    elif any(keyword in line for keyword in ['[CRITICAL]', '[HIGH]', '[MEDIUM]', 'Root Cause:', 'Jira:']):
                        # Indent sub-details for readability
                        if not line.startswith('['):
                            issue_lines.append(f"   {line}")
                        else:
                            issue_lines.append(line)
                    elif len(issue_lines) > 0 and len(issue_lines) < 50:  # Continue adding context if we've started
                        # Only add if it looks like issue content
                        if not any(x in line.lower() for x in ['actions taken', 'jira tickets:', 'next check', 'recommendations']):
                            issue_lines.append(f"   {line}")

                if issue_lines:
                    exec_summary_text = f"**{issue_count} Issue(s) Detected:**\n" + "\n".join(f"• {line}" for line in issue_lines[:10])
                else:
                    exec_summary_text = f"**{issue_count} Issue(s) Detected** (see details below)"

            # Pattern 2: "**🚨 HIGH SEVERITY ISSUE**" or "**🔴 CRITICAL ISSUE**"
            elif re.search(r'\*\*[🚨🔴🟠]\s*(HIGH|CRITICAL|MEDIUM)\s+SEVERITY\s+ISSUE', full_summary, re.IGNORECASE):
                # Extract all severity sections
                severity_issues = []
                for match in re.finditer(r'\*\*[🚨🔴🟠🟡]\s*(HIGH|CRITICAL|MEDIUM)\s+SEVERITY\s+ISSUE\*\*\s*\n\s*\n\*\*Resource\*\*:\s*([^\n]+)', full_summary, re.IGNORECASE):
                    sev = match.group(1)
                    resource = match.group(2)
                    severity_issues.append(f"{sev}: {resource}")

                if severity_issues:
                    exec_summary_text = f"**{len(severity_issues)} Issue(s):**\n" + "\n".join(f"• {issue}" for issue in severity_issues)

            # Pattern 3: Check overall status for generic message
            elif 'degraded' in full_summary.lower():
                exec_summary_text = "⚠️ Cluster degraded - see details below"
            elif 'critical' in full_summary.lower():
                exec_summary_text = "🔴 Critical issues detected - immediate attention required"
            else:
                exec_summary_text = "✅ No critical issues detected"

            # Always add executive summary
            sections.append({
                "activityTitle": "📋 Executive Summary",
                "text": exec_summary_text
            })

            # Cycle summary section (main overview with cluster metrics)
            cycle_facts = [
                {"name": "Cluster Health", "value": summary},
                {"name": "Timestamp", "value": datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}
            ]

            # Add cluster metrics if provided
            if cluster_metrics:
                if 'node_count' in cluster_metrics:
                    nodes_ready = cluster_metrics.get('nodes_ready', cluster_metrics['node_count'])
                    cycle_facts.append({
                        "name": "Nodes",
                        "value": f"{nodes_ready}/{cluster_metrics['node_count']} Ready"
                    })
                if 'pod_count' in cluster_metrics:
                    pods_running = cluster_metrics.get('pods_running', cluster_metrics['pod_count'])
                    cycle_facts.append({
                        "name": "Pods",
                        "value": f"{pods_running}/{cluster_metrics['pod_count']} Running"
                    })
                if 'healthy_namespaces' in cluster_metrics and 'total_namespaces' in cluster_metrics:
                    cycle_facts.append({
                        "name": "Namespaces",
                        "value": f"{cluster_metrics['healthy_namespaces']}/{cluster_metrics['total_namespaces']} Healthy"
                    })

            # Count issues if provided
            issues_to_count = critical_issues if critical_issues else []
            if issues_to_count:
                cycle_facts.append({"name": "Issues Detected", "value": str(len(issues_to_count))})

            sections.append({
                "activityTitle": f"🔍 Monitoring Cycle #{self.cycle_count} Complete",
                "activitySubtitle": f"Cluster: **{self.cluster_name}**",
                "facts": cycle_facts
            })

            # ALL issues section (CRITICAL, HIGH, MEDIUM) with detailed information
            if critical_issues:
                issue_details = []
                for i, issue in enumerate(critical_issues[:10], 1):  # Show up to 10 issues (all severities)
                    component = issue.get('component', 'Unknown')
                    namespace = issue.get('namespace', 'Unknown')
                    severity_level = issue.get('severity', 'Unknown')
                    status = issue.get('status', 'Unknown')
                    root_cause = issue.get('root_cause', '')
                    restart_count = issue.get('restart_count', '')
                    jira_ticket = issue.get('jira_ticket', False)
                    impact = issue.get('impact', '')
                    duration = issue.get('duration', '')

                    # Emoji for severity
                    severity_emoji = {
                        'CRITICAL': '🔴',
                        'HIGH': '🟠',
                        'MEDIUM': '🟡'
                    }.get(severity_level, '⚪')

                    issue_text = f"{severity_emoji} **{i}. {namespace}/{component}**\n"
                    issue_text += f"- **Severity:** {severity_level}"

                    # Indicate if Jira ticket created
                    if jira_ticket:
                        issue_text += " 🎫\n"
                    else:
                        issue_text += "\n"

                    issue_text += f"- **Status:** {status}\n"

                    if restart_count:
                        issue_text += f"- **Restarts:** {restart_count}\n"

                    if duration:
                        issue_text += f"- **Duration:** {duration}\n"

                    if impact:
                        # Truncate long impact descriptions
                        impact_short = impact[:150] + "..." if len(impact) > 150 else impact
                        issue_text += f"- **Impact:** {impact_short}\n"

                    if root_cause:
                        # Truncate long root causes
                        root_cause_short = root_cause[:200] + "..." if len(root_cause) > 200 else root_cause
                        issue_text += f"- **Root Cause:** {root_cause_short}\n"

                    issue_details.append(issue_text)

                # Count by severity for title
                critical_count = len([i for i in critical_issues if i['severity'] == 'CRITICAL'])
                high_count = len([i for i in critical_issues if i['severity'] == 'HIGH'])
                medium_count = len([i for i in critical_issues if i['severity'] == 'MEDIUM'])

                title_parts = []
                if critical_count > 0:
                    title_parts.append(f"{critical_count} Critical")
                if high_count > 0:
                    title_parts.append(f"{high_count} High")
                if medium_count > 0:
                    title_parts.append(f"{medium_count} Medium")

                issue_title = f"Issues Detected ({', '.join(title_parts)})" if title_parts else f"Issues Detected ({len(critical_issues)})"

                sections.append({
                    "activityTitle": f"🚨 {issue_title}",
                    "text": "\n\n".join(issue_details)
                })

            # Jira tickets section (improved with ticket details)
            if jira_tickets:
                ticket_details = []
                for ticket in jira_tickets[:5]:  # Limit to 5
                    ticket_key = ticket.get('key', 'Unknown')
                    ticket_url = ticket.get('url', '')
                    ticket_summary = ticket.get('summary', 'Unknown')
                    action = ticket.get('action', 'Unknown')  # created/updated
                    ticket_status = ticket.get('status', '')
                    ticket_priority = ticket.get('priority', '')

                    # Use actual summary instead of just ticket key
                    ticket_text = f"**[{ticket_key}]({ticket_url})** - {ticket_summary}\n"
                    ticket_text += f"- **Action:** {action.title()}"

                    if ticket_status:
                        ticket_text += f" | **Status:** {ticket_status}"
                    if ticket_priority:
                        ticket_text += f" | **Priority:** {ticket_priority}"

                    ticket_details.append(ticket_text)

                sections.append({
                    "activityTitle": f"🎫 Jira Tickets ({len(jira_tickets)})",
                    "text": "\n\n".join(ticket_details)
                })

            # Actions taken section (clean up duplicate checkmarks)
            if actions_taken:
                # Remove leading checkmarks/emojis if present (we'll add them consistently)
                cleaned_actions = []
                for action in actions_taken[:10]:
                    # Strip leading checkmarks and whitespace
                    cleaned = action.lstrip('✅✓❌⏭️ ')
                    if cleaned:
                        cleaned_actions.append(cleaned)

                actions_text = "\n".join([f"✅ {action}" for action in cleaned_actions])
                sections.append({
                    "activityTitle": f"⚡ Actions Taken ({len(cleaned_actions)})",
                    "text": actions_text
                })

            # Recommendations section (P0/P1/P2 prioritized)
            if recommendations:
                rec_sections = []

                if recommendations.get('p0'):
                    rec_sections.append(f"**🔥 P0 - Immediate (Next 2-4 hours):**\n" +
                                      "\n".join([f"- {rec}" for rec in recommendations['p0'][:3]]))

                if recommendations.get('p1'):
                    rec_sections.append(f"**⚠️ P1 - This Week:**\n" +
                                      "\n".join([f"- {rec}" for rec in recommendations['p1'][:3]]))

                if recommendations.get('p2'):
                    rec_sections.append(f"**📋 P2 - Next 1-2 Weeks:**\n" +
                                      "\n".join([f"- {rec}" for rec in recommendations['p2'][:3]]))

                if rec_sections:
                    sections.append({
                        "activityTitle": "💡 Recommendations",
                        "text": "\n\n".join(rec_sections)
                    })

            # Microsoft Teams Message Card format
            payload = {
                "@type": "MessageCard",
                "@context": "https://schema.org/extensions",
                "themeColor": colors.get(severity, colors["info"]),
                "summary": f"{title} - {self.cluster_name}",
                "sections": sections
            }

            # Add action buttons for quick access
            potential_actions = []

            # Jira ticket links
            if jira_tickets:
                for ticket in jira_tickets[:2]:  # Top 2 tickets
                    if ticket.get('url'):
                        potential_actions.append({
                            "@type": "OpenUri",
                            "name": f"🎫 {ticket.get('key', 'Ticket')}",
                            "targets": [{"os": "default", "uri": ticket.get('url', '')}]
                        })

            # ArgoCD link for dev-eks cluster
            if self.cluster_name == 'dev-eks':
                potential_actions.append({
                    "@type": "OpenUri",
                    "name": "🚀 ArgoCD (dev-eks)",
                    "targets": [{"os": "default", "uri": "https://argocd-dev.nomihealth.com/applications"}]
                })

            # Datadog link for cluster monitoring
            potential_actions.append({
                "@type": "OpenUri",
                "name": "📊 Datadog Cluster View",
                "targets": [{"os": "default", "uri": f"https://app.datadoghq.com/containers?query=kube_cluster_name%3A{self.cluster_name}"}]
            })

            # AWS Console link
            aws_region = os.getenv('AWS_REGION', 'us-east-1')
            potential_actions.append({
                "@type": "OpenUri",
                "name": "☁️ AWS EKS Console",
                "targets": [{"os": "default", "uri": f"https://console.aws.amazon.com/eks/home?region={aws_region}#/clusters/{self.cluster_name}"}]
            })

            # View full report link (if accessible)
            report_file = REPORT_DIR / f"cycle-{self.cycle_count:04d}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.txt"
            if os.getenv('REPORT_VIEWER_URL'):  # Optional: if you host reports via web server
                potential_actions.append({
                    "@type": "OpenUri",
                    "name": "📄 Full Report",
                    "targets": [{"os": "default", "uri": f"{os.getenv('REPORT_VIEWER_URL')}/{report_file.name}"}]
                })

            if potential_actions:
                payload["potentialAction"] = potential_actions

            response = requests.post(teams_webhook, json=payload, timeout=5)
            response.raise_for_status()
            self.log(f"[TEAMS] Cycle summary notification sent", level="INFO")

        except Exception as e:
            self.log(f"[TEAMS] Failed to send notification: {e}", level="WARN")

    async def perform_health_check(self):
        """
        Perform a single health check cycle using subagents.

        This is the core monitoring logic that coordinates all subagents.
        """
        # Check if cluster has changed (re-detect on each cycle)
        current_cluster = self._detect_cluster_name()
        if self.last_cluster_name and current_cluster != self.last_cluster_name:
            self.log(f"[CLUSTER CHANGE] Detected switch: {self.last_cluster_name} → {current_cluster}", level="WARN")
            self.log("[CLUSTER CHANGE] Resetting conversation state (clearing old cluster context)", level="WARN")

            # Exit the current client context (this will close MCP servers)
            # The run() method will need to handle re-initialization
            raise ClusterChangeException(f"Cluster changed from {self.last_cluster_name} to {current_cluster}")

        # Update tracking
        self.last_cluster_name = current_cluster
        self.cluster_name = current_cluster

        self.cycle_count += 1
        self.log(f"=== Starting Health Check Cycle #{self.cycle_count} ===")

        try:
            # Build the prompt for this cycle
            prompt = f"""
Perform comprehensive health check cycle #{self.cycle_count} for cluster: {self.cluster_name}

**CRITICAL: IGNORE ALL PREVIOUS CLUSTER DATA**
- This is cycle #{self.cycle_count} monitoring {self.cluster_name}
- ONLY use fresh data from THIS cycle's queries
- Do NOT reference restart counts or issues from previous cycles unless they're from THIS cluster query
- Verify cluster name in all MCP tool responses

1. **Diagnostics**: Use k8s-diagnostics subagent to check cluster health
   - Focus on: pod failures, resource constraints, node issues
   - Check ALL critical namespaces from CLAUDE.md (both infrastructure AND application)
   - VERIFY: Cluster being queried is {self.cluster_name}
   - Provide health status for EACH critical namespace listed in CLAUDE.md

2. **If issues found**:
   - Use k8s-log-analyzer for CrashLoopBackOff/OOMKilled issues
   - Cross-reference with "Known Issues & Patterns" in CLAUDE.md
   - Determine severity based on impact

3. **Incident tracking (CRITICAL severity ONLY)**:
   - **CRITICAL RULE**: Only invoke k8s-jira for incidents with severity = CRITICAL
   - **DO NOT create Jira tickets for**:
     - HIGH severity (these are warnings - monitor but don't ticket)
     - CPU spikes (unless causing pod failures)
     - Memory warnings (unless causing OOMKilled)
     - Performance warnings without service impact
   - **DO create Jira tickets for**:
     - CrashLoopBackOff with 3+ restarts (CRITICAL)
     - OOMKilled causing service outage (CRITICAL)
     - ImagePullBackOff blocking deployments (CRITICAL)
     - Infrastructure component failures (CRITICAL)

   **When creating/updating tickets:**
   - ALWAYS search for existing tickets first to prevent duplicates
   - Jira search JQL: "project = DEVOPS AND status != Closed AND summary ~ '[{self.cluster_name}] <component>'"
   - If existing ticket found: Add comment ONLY if (24+ hours since last update OR status changed) AND significant change
   - If not found: Create new ticket with priority and labels
   - ALWAYS include cluster name "{self.cluster_name}" in title (e.g., "[{self.cluster_name}] Component: Issue Description")
   - Include diagnostic findings and log analysis in ticket body
   - OPTIONAL: Use k8s-github to correlate with recent deployments (add deployment info to Jira ticket)

4. **Remediation decision**:
   - Check "Approved Auto-Remediation" rules in CLAUDE.md
   - Verify deployment has 2+ replicas before restart
   - Only proceed if within approved scope

5. **If remediation approved**:
   - Use k8s-remediation subagent for rolling restart
   - Update GitHub issue with remediation results

6. **Cost analysis** (every 10th cycle):
   {"- Use k8s-cost-optimizer for resource review" if self.cycle_count % 10 == 0 else "- Skipped this cycle"}

Save summary report to: /tmp/eks-monitoring-reports/cycle-{self.cycle_count:04d}.txt

Timestamp: {datetime.now(UTC).isoformat()}
"""

            # Start the query
            self.log("Sending query to orchestrator...", level="INFO")
            await self.client.query(prompt)

            # Process response messages
            self.log("Waiting for orchestrator response...", level="INFO")
            summary_parts = []
            tool_count = 0
            subagent_count = 0
            message_count = 0
            last_activity = datetime.now(UTC)

            async for message in self.client.receive_response():
                last_activity = datetime.now(UTC)
                message_count += 1

                # Get message type safely (handle different message object types)
                msg_type = message.__class__.__name__

                # Log heartbeat every 5 messages to show progress
                if message_count % 5 == 0:
                    elapsed = (datetime.now(UTC) - last_activity).total_seconds()
                    self.log(f"[STATUS] Active - {message_count} messages, {tool_count} tools, {subagent_count} subagents", level="INFO")

                if msg_type == "AssistantMessage":
                    # Extract content from AssistantMessage
                    content = getattr(message, 'content', [])

                    # Log that we received a message immediately
                    if content:
                        self.log(f"Received assistant message with {len(content)} content item(s)", level="DEBUG")

                    for item in content:
                        # Get type from either .type attribute or class name
                        if hasattr(item, 'type'):
                            item_type = item.type
                        elif hasattr(item, '__class__'):
                            item_type = item.__class__.__name__.lower().replace('block', '')
                        else:
                            item_type = None

                        self.log(f"Content item: {item_type} | {type(item).__name__}", level="DEBUG")

                        # Text content
                        if item_type == 'text' or hasattr(item, 'text'):
                            text = getattr(item, 'text', str(item))
                            summary_parts.append(text)
                            # Log concise preview immediately
                            preview = text[:150].replace('\n', ' ')
                            self.log(f"[AGENT] {preview}...", level="INFO")

                        # Tool use - try multiple ways to detect
                        elif item_type == 'tool_use' or hasattr(item, 'tool_use_id') or hasattr(item, 'name'):
                            tool_count += 1
                            tool_name = getattr(item, 'name', 'unknown')

                            # Log immediately
                            self.log(f"[TOOL #{tool_count}] {tool_name}", level="INFO")

                            # Check if this is a Task tool (subagent invocation)
                            if tool_name == "Task":
                                subagent_count += 1
                                tool_input = getattr(item, 'input', {})
                                subagent_type = tool_input.get('subagent_type', 'unknown')
                                description = tool_input.get('description', '')
                                self.log(f"[SUBAGENT #{subagent_count}] {subagent_type} - {description[:50]}", level="INFO")
                        else:
                            # Log unknown types for debugging
                            self.log(f"[WARNING] Unknown content item: {item_type} | attrs: {dir(item)[:5]}", level="DEBUG")

                elif msg_type == "UserMessage":
                    # User messages are from hooks or system - usually not needed in summary
                    pass

                elif msg_type == "SystemMessage":
                    # System initialization message
                    if hasattr(message, 'subtype') and message.subtype == 'init':
                        # Log MCP server connection status
                        data = getattr(message, 'data', {})
                        mcp_servers = data.get('mcp_servers', [])
                        for server in mcp_servers:
                            self.log(f"[MCP] Server '{server['name']}': {server['status']}", level="INFO")

                        # Log available agents
                        agents = data.get('agents', [])
                        custom_agents = [a for a in agents if not a.startswith('general-purpose') and not a.startswith('output-')]
                        if custom_agents:
                            self.log(f"[AGENTS] Custom subagents loaded: {', '.join(custom_agents)}", level="INFO")

                else:
                    # Log unexpected message types for debugging
                    self.log(f"[WARNING] Unexpected message type: {msg_type}", level="DEBUG")

            # Response stream complete
            self.log("[COMPLETE] Response stream completed", level="INFO")
            self.log(f"Subagents invoked: {subagent_count}", level="INFO")
            self.log(f"Total tools used: {tool_count}", level="INFO")

            # Compile full summary
            full_summary = '\n'.join(summary_parts)

            # Build full report content
            report_content = (
                f"=== EKS Monitoring Cycle #{self.cycle_count} ===\n"
                f"Timestamp: {datetime.now(UTC).isoformat()}\n"
                f"Subagents Invoked: {subagent_count}\n"
                f"Tools Used: {tool_count}\n"
                f"\n"
                f"{full_summary}\n"
            )

            # Save summary report to file
            report_file = REPORT_DIR / f"cycle-{self.cycle_count:04d}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.txt"
            with open(report_file, 'w') as f:
                f.write(report_content)

            self.log(f"[CYCLE] Health check cycle #{self.cycle_count} completed successfully", level="INFO")
            self.log(f"[REPORT] Saved to: {report_file}", level="INFO")

            # Parse summary for issues, Jira tickets, actions, metrics, and recommendations
            import re

            all_issues = []  # All issues (CRITICAL, HIGH, MEDIUM) for Teams
            critical_issues = []  # CRITICAL only (for backwards compatibility)
            jira_tickets = []
            actions_taken = []
            cluster_metrics = {}
            recommendations = {'p0': [], 'p1': [], 'p2': []}
            overall_status = "HEALTHY"

            # Determine overall status
            summary_lower = full_summary.lower()
            if 'critical' in summary_lower or '❌' in full_summary:
                overall_status = "CRITICAL"
                severity = "critical"
            elif 'degraded' in summary_lower or '⚠️' in full_summary:
                overall_status = "DEGRADED"
                severity = "warning"
            else:
                overall_status = "HEALTHY"
                severity = "success"

            # Extract ALL issues (CRITICAL, HIGH, MEDIUM) for Teams notification
            # Try multiple patterns to match different output formats:
            # Pattern 1: "**🚨 HIGH SEVERITY ISSUE**" (new narrative format)
            # Pattern 2: "- CRITICAL: AWS Cluster Autoscaler CrashLoopBackOff (568 restarts)"
            # Pattern 3: "1. CRITICAL: namespace/component - description"

            # Primary pattern: Narrative severity section format
            severity_section_pattern = r'\*\*[🚨🔴🟠🟡]\s*(CRITICAL|HIGH|MEDIUM)\s+SEVERITY\s+ISSUE\*\*\s*\n\s*\n\*\*Resource\*\*:\s*([^\n]+)\s*\n\*\*Status\*\*:\s*([^\n]+)'
            for match in re.finditer(severity_section_pattern, full_summary, re.IGNORECASE):
                severity_level = match.group(1).upper()
                resource = match.group(2).strip()  # e.g., "kube-system/aws-cluster-autoscaler-656879949-kqfwt"
                status = match.group(3).strip()

                # Parse namespace/component from resource
                if '/' in resource:
                    namespace, component = resource.split('/', 1)
                else:
                    namespace = 'Unknown'
                    component = resource

                # Look for additional context after the match
                issue_start = match.end()
                issue_section = full_summary[issue_start:issue_start+1000]

                # Extract all the details
                restart_match = re.search(r'Restart Count\*\*:\s*(\d+)', issue_section, re.IGNORECASE)
                restart_count = restart_match.group(1) if restart_match else ""

                duration_match = re.search(r'over\s+(\d+\+?\s*(?:day|hour|minute)s?)', issue_section, re.IGNORECASE)
                duration = duration_match.group(1) if duration_match else ""

                impact_match = re.search(r'\*\*Impact\*\*:([^\*]+?)(?:\*\*|$)', issue_section, re.IGNORECASE | re.DOTALL)
                if impact_match:
                    impact_lines = [line.strip() for line in impact_match.group(1).split('\n') if line.strip() and not line.strip().startswith('-')]
                    impact = ' '.join(impact_lines[:3])  # First 3 lines
                else:
                    impact = ""

                root_cause_match = re.search(r'\*\*Root Cause\*\*:([^\*]+?)(?:\*\*|$)', issue_section, re.IGNORECASE | re.DOTALL)
                root_cause = root_cause_match.group(1).strip() if root_cause_match else ""

                jira_ticket_created = severity_level == 'CRITICAL'

                all_issues.append({
                    'severity': severity_level,
                    'component': component,
                    'namespace': namespace,
                    'status': status,
                    'restart_count': restart_count,
                    'duration': duration,
                    'impact': impact,
                    'root_cause': root_cause,
                    'jira_ticket': jira_ticket_created
                })

            # Secondary pattern: bullet list format
            if not all_issues:
                issue_pattern_bullet = r'[-•]\s*(CRITICAL|HIGH|MEDIUM):?\s*([^()\n]+?)(?:\s+CrashLoopBackOff|\s+OOMKilled|\s+ImagePullBackOff|\s+Failed)?\s*\(([^)]+)\)'
                for match in re.finditer(issue_pattern_bullet, full_summary, re.IGNORECASE):
                    severity_level = match.group(1).upper()
                    component_text = match.group(2).strip()
                    context_info = match.group(3).strip()  # e.g., "568 restarts, exit code 255"

                    # Extract namespace if present (format: "namespace/component" or just "component")
                    if '/' in component_text:
                        namespace, component = component_text.split('/', 1)
                    else:
                        # Try to infer namespace from context
                        namespace_match = re.search(r'\b(kube-system|karpenter|datadog-operator-dev|artemis-preprod|chronos-preprod|delivery-preprod|proteus-\w+)\b',
                                                   full_summary[max(0, match.start()-200):match.end()+200], re.IGNORECASE)
                        namespace = namespace_match.group(1) if namespace_match else 'Unknown'
                        component = component_text

                    # Look for additional context after the issue line
                    issue_start = match.end()
                    issue_section = full_summary[issue_start:issue_start+800]

                    # Extract restart count
                    restart_match = re.search(r'(\d+)\s*restarts?', context_info, re.IGNORECASE)
                    restart_count = restart_match.group(1) if restart_match else ""

                    # Extract duration
                    duration_match = re.search(r'(\d+\+?\s*(?:day|hour|minute)s?)', issue_section, re.IGNORECASE)
                    duration = duration_match.group(1) if duration_match else ""

                    # Extract impact
                    impact_match = re.search(r'Impact:?\s*([^\n]+)', issue_section, re.IGNORECASE)
                    impact = impact_match.group(1).strip() if impact_match else ""

                    # Extract root cause
                    root_cause_match = re.search(r'Root Cause:?\s*([^\n]+)', issue_section, re.IGNORECASE)
                    root_cause = root_cause_match.group(1).strip() if root_cause_match else context_info

                    # Determine status from component text or context
                    if 'crashloopbackoff' in component_text.lower() or 'crashloopbackoff' in context_info.lower():
                        status = 'CrashLoopBackOff'
                    elif 'oomkilled' in component_text.lower() or 'oomkilled' in context_info.lower():
                        status = 'OOMKilled'
                    elif 'imagepullbackoff' in component_text.lower() or 'imagepullbackoff' in context_info.lower():
                        status = 'ImagePullBackOff'
                    else:
                        status = 'Failed'

                    jira_ticket_created = severity_level == 'CRITICAL'

                    all_issues.append({
                        'severity': severity_level,
                        'component': component,
                        'namespace': namespace,
                        'status': status,
                        'restart_count': restart_count,
                        'duration': duration,
                        'impact': impact,
                        'root_cause': root_cause,
                        'jira_ticket': jira_ticket_created
                    })

            # Tertiary pattern: New structured numbered format
            # "1. [HIGH] namespace/component - description"
            if not all_issues:
                issue_pattern_structured = r'(\d+)\.\s*\[(CRITICAL|HIGH|MEDIUM)\]\s+([^/\n]+)/([^\n-]+)\s*-\s*([^\n]+)'
                for match in re.finditer(issue_pattern_structured, full_summary, re.IGNORECASE | re.MULTILINE):
                    severity_level = match.group(2).upper()
                    namespace = match.group(3).strip()
                    component = match.group(4).strip()
                    description = match.group(5).strip()

                    # Look for additional context after the issue line
                    issue_start = match.end()
                    issue_section = full_summary[issue_start:issue_start+800]

                    # Extract details with specific field names
                    restart_match = re.search(r'Restarts?:\s*(\d+)', issue_section, re.IGNORECASE)
                    restart_count = restart_match.group(1) if restart_match else ""

                    duration_match = re.search(r'Duration:\s*([^\n|]+)', issue_section, re.IGNORECASE)
                    duration = duration_match.group(1).strip() if duration_match else ""

                    impact_match = re.search(r'Impact:\s*([^\n]+)', issue_section, re.IGNORECASE)
                    impact = impact_match.group(1).strip() if impact_match else ""

                    root_cause_match = re.search(r'Root Cause:\s*([^\n]+)', issue_section, re.IGNORECASE)
                    root_cause = root_cause_match.group(1).strip() if root_cause_match else description

                    jira_match = re.search(r'Jira:\s*(DEVOPS-\d+|INFRA-\d+|Not created)', issue_section, re.IGNORECASE)
                    jira_ticket_created = jira_match and 'Not created' not in jira_match.group(1) if jira_match else severity_level == 'CRITICAL'

                    all_issues.append({
                        'severity': severity_level,
                        'component': component,
                        'namespace': namespace,
                        'status': description,  # Brief description used as status
                        'restart_count': restart_count,
                        'duration': duration,
                        'impact': impact,
                        'root_cause': root_cause,
                        'jira_ticket': jira_ticket_created
                    })

            # Fallback: Original numbered list pattern
            if not all_issues:
                issue_pattern_numbered = r'(\d+)\.\s*(CRITICAL|HIGH|MEDIUM):?\s*([^/\n]+)/([^\n-]+)(?:\s*-\s*([^\n]+))?'
                for match in re.finditer(issue_pattern_numbered, full_summary, re.IGNORECASE | re.MULTILINE):
                    severity_level = match.group(2).upper()
                    namespace = match.group(3).strip()
                    component = match.group(4).strip()
                    description = match.group(5).strip() if match.group(5) else ""

                    # Look for additional context after the issue line
                    issue_start = match.end()
                    issue_section = full_summary[issue_start:issue_start+500]

                    # Extract restart count if present
                    restart_match = re.search(r'(\d+)\s*restarts?', issue_section, re.IGNORECASE)
                    restart_count = restart_match.group(1) if restart_match else ""

                    # Extract duration if present (e.g., "2 days", "35+ days")
                    duration_match = re.search(r'(\d+\+?\s*(?:day|hour|minute)s?)', issue_section, re.IGNORECASE)
                    duration = duration_match.group(1) if duration_match else ""

                    # Extract impact if present
                    impact_match = re.search(r'Impact:?\s*([^\n]+)', issue_section, re.IGNORECASE)
                    impact = impact_match.group(1).strip() if impact_match else ""

                    # Extract root cause if present
                    root_cause_match = re.search(r'Root Cause:?\s*([^\n]+)', issue_section, re.IGNORECASE)
                    root_cause = root_cause_match.group(1).strip() if root_cause_match else description

                    # Determine if Jira ticket will be created (CRITICAL only)
                    jira_ticket_created = severity_level == 'CRITICAL'

                    all_issues.append({
                        'severity': severity_level,
                        'component': component,
                        'namespace': namespace,
                        'status': 'CrashLoopBackOff' if 'crash' in issue_section.lower() else 'Failed',
                        'restart_count': restart_count,
                        'duration': duration,
                        'impact': impact,
                        'root_cause': root_cause,
                        'jira_ticket': jira_ticket_created  # Flag if Jira ticket will be created
                    })

            # Filter issues for Teams notification
            # Include CRITICAL and HIGH severity (not just CRITICAL)
            # MEDIUM/LOW are logged but not sent to Teams to reduce noise
            critical_issues = [issue for issue in all_issues if issue['severity'] in ['CRITICAL', 'HIGH']]

            # Extract Jira tickets
            # Pattern: "DEVOPS-1234" or "Jira ticket: DEVOPS-1234"
            jira_pattern = r'(?:DEVOPS|INFRA)-(\d+)'
            jira_matches = re.finditer(jira_pattern, full_summary)
            seen_tickets = set()

            for match in jira_matches:
                ticket_key = match.group(0)
                if ticket_key in seen_tickets:
                    continue
                seen_tickets.add(ticket_key)

                # Look for context around the ticket
                context_start = max(0, match.start() - 200)
                context_end = min(len(full_summary), match.end() + 200)
                context = full_summary[context_start:context_end]

                # Determine action (created/updated)
                action = "created" if "created" in context.lower() or "new ticket" in context.lower() else "updated"

                # Try to extract ticket summary
                summary_match = re.search(r'\[dev-eks\]\s*([^\n:]+)', context)
                ticket_summary = summary_match.group(1).strip() if summary_match else ticket_key

                jira_tickets.append({
                    'key': ticket_key,
                    'url': f"https://artemishealth.atlassian.net/browse/{ticket_key}",
                    'summary': ticket_summary,
                    'action': action
                })

            # Extract actions taken
            # Pattern: "✅ action" or "Actions Taken:" section
            actions_section_match = re.search(r'Actions Taken:([^#]+?)(?:\n\n|Next Check|Recommendations|Jira Tickets|$)', full_summary, re.IGNORECASE | re.DOTALL)
            if actions_section_match:
                actions_text = actions_section_match.group(1)
                # Extract bullet points or checkmarks
                action_lines = re.findall(r'(?:✅|✓|-|\*)\s*([^\n]+)', actions_text)
                actions_taken = [action.strip() for action in action_lines if action.strip()]

            # Extract cluster metrics
            # Node status: "39/40 Ready" or "Node Status: 39/40 Ready"
            node_status_match = re.search(r'Node(?:\s+Status)?:\s*(\d+)/(\d+)\s*Ready', full_summary, re.IGNORECASE)
            if node_status_match:
                cluster_metrics['nodes_ready'] = int(node_status_match.group(1))
                cluster_metrics['node_count'] = int(node_status_match.group(2))

            # Pod counts: "Total: X, Running: Y, Failed: Z"
            pod_total_match = re.search(r'(?:Total|Pods):\s*(\d+)', full_summary, re.IGNORECASE)
            pod_running_match = re.search(r'Running:\s*(\d+)', full_summary, re.IGNORECASE)
            if pod_total_match:
                cluster_metrics['pod_count'] = int(pod_total_match.group(1))
            if pod_running_match:
                cluster_metrics['pods_running'] = int(pod_running_match.group(1))

            # Namespace health: count from Section 1 (multiple patterns)
            # Pattern 1: "- ✅ **namespace**: HEALTHY"
            healthy_ns_pattern1 = len(re.findall(r'[-•]\s*✅\s*\*\*[^:]+\*\*:\s*HEALTHY', full_summary, re.IGNORECASE))
            total_ns_pattern1 = len(re.findall(r'[-•]\s*[✅⚠️❌]\s*\*\*[^:]+\*\*:\s*(?:HEALTHY|DEGRADED|CRITICAL|NO PODS)', full_summary, re.IGNORECASE))

            # Pattern 2: "kube-system: ✅ Healthy" or "- **kube-system**: ✅ **Healthy**"
            healthy_ns_pattern2 = len(re.findall(r'(?:^|\n)\s*[-•]?\s*\*?\*?[a-z][-a-z0-9]+\*?\*?:\s*✅', full_summary, re.MULTILINE))
            total_ns_pattern2 = len(re.findall(r'(?:^|\n)\s*[-•]?\s*\*?\*?[a-z][-a-z0-9]+\*?\*?:\s*[✅⚠️❌]', full_summary, re.MULTILINE))

            # Use whichever pattern found more results
            if total_ns_pattern1 > total_ns_pattern2:
                healthy_ns_count = healthy_ns_pattern1
                total_ns_count = total_ns_pattern1
            else:
                healthy_ns_count = healthy_ns_pattern2
                total_ns_count = total_ns_pattern2

            if total_ns_count > 0:
                cluster_metrics['healthy_namespaces'] = healthy_ns_count
                cluster_metrics['total_namespaces'] = total_ns_count

            # Extract recommendations (supports both P0/P1/P2 and Priority 1/2/3 formats)
            # Pattern 1: "P0 (Next 2-4 hours):" or "P0:" followed by list
            p0_section_match = re.search(r'(?:P0|Priority\s+1)\s*\([^)]+\):?((?:\n\s*[0-9.•-]+\s*[🔴🟠🟢]?\s*[^\n]+)+)', full_summary, re.IGNORECASE | re.MULTILINE)
            if p0_section_match:
                p0_text = p0_section_match.group(1)
                p0_items = re.findall(r'[0-9.•-]+\s*[🔴🟠🟢]?\s*([^\n]+)', p0_text)
                recommendations['p0'] = [item.strip() for item in p0_items if item.strip()]

            p1_section_match = re.search(r'(?:P1|Priority\s+2)\s*\([^)]+\):?((?:\n\s*[0-9.•-]+\s*[🔴🟠🟢]?\s*[^\n]+)+)', full_summary, re.IGNORECASE | re.MULTILINE)
            if p1_section_match:
                p1_text = p1_section_match.group(1)
                p1_items = re.findall(r'[0-9.•-]+\s*[🔴🟠🟢]?\s*([^\n]+)', p1_text)
                recommendations['p1'] = [item.strip() for item in p1_items if item.strip()]

            p2_section_match = re.search(r'(?:P2|Priority\s+3)\s*\([^)]+\):?((?:\n\s*[0-9.•-]+\s*[🔴🟠🟢]?\s*[^\n]+)+)', full_summary, re.IGNORECASE | re.MULTILINE)
            if p2_section_match:
                p2_text = p2_section_match.group(1)
                p2_items = re.findall(r'[0-9.•-]+\s*[🔴🟠🟢]?\s*([^\n]+)', p2_text)
                recommendations['p2'] = [item.strip() for item in p2_items if item.strip()]

            # Send Teams notification with full details
            if overall_status != "HEALTHY" or critical_issues or jira_tickets:
                # Send notification for degraded/critical status or any issues/tickets found
                self.send_teams_notification(
                    title=f"EKS Monitoring - {overall_status}",
                    summary=f"Cluster Health: {overall_status}",
                    severity=severity,
                    critical_issues=critical_issues if critical_issues else None,
                    jira_tickets=jira_tickets if jira_tickets else None,
                    actions_taken=actions_taken if actions_taken else None,
                    full_summary=full_summary,
                    cluster_metrics=cluster_metrics if cluster_metrics else None,
                    recommendations=recommendations if any(recommendations.values()) else None
                )
            else:
                # Send healthy status notification (info level, less urgent)
                self.send_teams_notification(
                    title="EKS Monitoring - Healthy",
                    summary="All systems operational",
                    severity="success",
                    full_summary=full_summary,
                    cluster_metrics=cluster_metrics if cluster_metrics else None
                )

            # Print full report to stdout (for Datadog to capture)
            # Controlled by LOG_LEVEL:
            # - MINIMAL: Only print completion notice (report too verbose)
            # - NORMAL/VERBOSE: Print full report
            if CURRENT_LOG_LEVEL <= LOG_LEVELS['NORMAL']:
                print("\n" + "="*80)
                print("DETAILED CYCLE REPORT")
                print("="*80)
                print(report_content)
                print("="*80 + "\n")
                sys.stdout.flush()

        except KeyboardInterrupt:
            raise  # Propagate interrupt
        except Exception as e:
            self.log(f"Error during health check cycle #{self.cycle_count}: {e}", level="ERROR")
            # Don't raise - continue monitoring

    async def run(self):
        """
        Main daemon loop - continuous monitoring.

        Runs health checks every CHECK_INTERVAL seconds indefinitely.
        """
        self.log("=" * 60)
        self.log("EKS Monitoring Daemon Starting")
        self.log("=" * 60)
        self.log(f"Cluster: {self.cluster_name}")
        if KUBE_CONTEXT:
            self.log(f"Kubectl context: {KUBE_CONTEXT} (explicit)")
        else:
            self.log(f"Kubectl context: auto-detect from current context")
        self.log(f"Check interval: {self.check_interval} seconds")
        self.log(f"Report directory: {REPORT_DIR}")
        self.log(f"Log level: {LOG_LEVEL}")
        self.log(f"File logging: {'enabled' if LOG_TO_FILE else 'disabled (stdout only)'}")
        if not LOG_TO_FILE:
            self.log(f"NOTE: All logs go to stdout/stderr for Datadog to capture")
        self.log("")

        self.running = True

        # Main monitoring loop with cluster change detection
        while self.running:
            try:
                # Initialize the SDK client (creates ClaudeSDKClient instance)
                await self.initialize_client()

                # Use client as async context manager (handles MCP server lifecycle)
                self.log("[DEBUG] Entering client context manager...", level="INFO")
                async with self.client:
                    self.log("[DEBUG] Client context entered successfully!", level="INFO")
                    self.log("SDK client connected successfully")
                    self.log("SDK client ready (no MCP servers)")

                    # Health check loop for current cluster
                    while self.running:
                        try:
                            await self.perform_health_check()
                        except ClusterChangeException as e:
                            # Cluster changed - need to recreate client with fresh conversation
                            self.log(f"[CLUSTER CHANGE] {e}", level="WARN")
                            self.log("[CLUSTER CHANGE] Closing current client and reinitializing...", level="WARN")
                            self.cycle_count = 0  # Reset cycle count for new cluster
                            break  # Exit async context (closes MCP servers), will re-initialize
                        except KeyboardInterrupt:
                            self.log("Received interrupt signal, shutting down...")
                            self.running = False
                            break

                        # Wait for next cycle
                        if self.running:
                            next_check = datetime.now(UTC).timestamp() + self.check_interval
                            next_check_time = datetime.fromtimestamp(next_check, UTC).strftime('%H:%M:%S')
                            self.log(f"Next check at {next_check_time} (in {self.check_interval} seconds)")
                            await asyncio.sleep(self.check_interval)

                # If we broke out of loop due to cluster change, continue to re-initialize
                if not self.running:
                    break  # Exit main loop

            except KeyboardInterrupt:
                self.log("Received interrupt signal, shutting down...")
                self.running = False
                break
            except Exception as e:
                self.log(f"Fatal error in client initialization: {e}", level="ERROR")
                self.log("Will retry in next cycle...", level="WARN")
                await asyncio.sleep(30)  # Wait before retrying

        # Shutdown after exiting main loop
        await self.shutdown()

    async def shutdown(self):
        """Graceful shutdown - cleanup MCP servers and close client"""
        self.log("Shutting down EKS Monitoring Daemon...")
        self.running = False

        # Note: SDK client cleanup is handled by the async context manager
        # in the run() method, so we don't need to manually close it here

        self.log("=" * 60)
        self.log(f"Daemon stopped after {self.cycle_count} monitoring cycles")
        self.log("=" * 60)


async def main():
    """Entry point for daemon"""
    # Note: .env is already loaded at module import time (top of file)
    daemon = EKSMonitoringDaemon()

    try:
        # Run the daemon (handles async context manager internally)
        await daemon.run()
    except KeyboardInterrupt:
        print("\n\nShutdown requested by user (Ctrl+C)")
    except Exception as e:
        print(f"\n\nFatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())
