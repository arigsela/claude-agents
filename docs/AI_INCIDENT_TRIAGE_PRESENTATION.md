# AI-Powered Incident Triage: From Hours to Minutes

**A practical demo of Claude Code & MCP for DevOps automation**

*Presenter: Ari Sela*

---

## Table of Contents

1. [The Problem](#part-1-the-problem)
2. [The Solution](#part-2-the-solution)
3. [Live Demo](#part-3-live-demo)
4. [How It Works](#part-4-how-it-works)
5. [Real-World Impact](#part-5-real-world-impact)
6. [Getting Started](#part-6-getting-started)
7. [Q&A and Discussion](#part-7-qa-and-discussion)
8. [Resources](#appendix-resources)

---

## PART 1: The Problem
### "Why we needed this" (5 minutes)

### Current State: Manual Incident Triage is Slow and Repetitive

**Typical incident response workflow:**
- Engineer gets paged at 3am
- Manually checks: pod logs, events, deployments, recent PRs
- Cross-references: Jira tickets, GitHub commits, AWS resources
- Takes **30-60 minutes** just to understand what broke
- Context-switching kills productivity

### The Overhead

**Multiple disconnected tools:**
- `kubectl` commands
- GitHub web interface
- Jira ticket tracking
- AWS Console navigation
- Datadog dashboards

**Manual copy-pasting between systems:**
- Copy pod logs → paste into Jira
- Copy error messages → search in GitHub
- Copy deployment names → check AWS resources

**Same debugging patterns repeated over and over:**
- "Which pods are failing?"
- "What changed recently?"
- "Is this related to that deployment 2 hours ago?"
- "Has this happened before?"

**Knowledge locked in senior engineers' heads:**
- Junior engineers don't know where to start
- Tribal knowledge not documented
- Inconsistent investigation quality

### The Big Question

> **"What if an AI could do the initial triage in 60 seconds?"**

---

## PART 2: The Solution
### "Two ways to use Claude for automation" (5 minutes)

### Approach 1: Autonomous Agent (EKS Monitor)

**Think of it as: "AI teammate that watches your cluster 24/7"**

**What it does:**
- Runs continuously in Kubernetes as a pod
- Proactively monitors cluster health every 15 minutes
- Creates Jira tickets automatically with full context
- Sends Teams notifications with root cause analysis
- Can perform safe auto-remediation (with approval gates)

**When to use:**
- Continuous monitoring needs
- Reduce alert noise with intelligent filtering
- Auto-document incidents in Jira
- Proactive issue detection before users notice

**Key technology:**
- Claude Agent SDK (persistent memory across runs)
- MCP servers (structured access to K8s, GitHub, Jira)
- Multi-agent coordination (6 specialized subagents)

---

### Approach 2: On-Demand API (OnCall Agent)

**Think of it as: "AI assistant you ask questions when something breaks"**

**What it does:**
- HTTP API you can call from anywhere
- Slack bot integration for interactive troubleshooting
- n8n workflow automation
- Simple curl commands for ad-hoc queries
- Session-based conversations (ask follow-up questions)

**When to use:**
- On-demand incident investigation
- Slack bot for team self-service
- Integration with existing tools (PagerDuty, ServiceNow, etc.)
- Quick prototyping and experimentation

**Key technology:**
- Anthropic API (direct, lightweight)
- FastAPI (standard HTTP REST interface)
- Direct Python libraries (kubernetes, PyGithub, boto3)
- No external runtime dependencies

---

### The Key Insight

> **Same AI brain, different deployment patterns for different needs**

Both approaches solve incident triage, but optimized for different workflows:

| Use Case | Recommended Approach |
|----------|---------------------|
| "Watch my cluster and tell me when something's wrong" | **Autonomous Agent** |
| "I have a Slack alert, help me investigate" | **On-Demand API** |
| "Auto-create Jira tickets with context" | **Autonomous Agent** |
| "Let engineers ask questions via Slack bot" | **On-Demand API** |
| "Perform safe auto-remediation" | **Autonomous Agent** |
| "Integrate with n8n workflows" | **On-Demand API** |

**You can run both simultaneously!** They complement each other.

---

## PART 3: Live Demo
### "Show, don't tell" (15 minutes)

### Demo 1: Autonomous Monitoring in Action (5 min)

**Scenario:** The EKS agent detected an issue during its scheduled monitoring cycle

#### Step 1: Show the agent running

```bash
# Check the agent is running
docker compose logs eks-monitoring-daemon --tail=50

# Output shows:
# [2025-10-21 10:15:00] Starting monitoring cycle #47
# [2025-10-21 10:15:02] Invoking k8s-diagnostics subagent
# [2025-10-21 10:15:35] Found 3 issues across 2 namespaces
# [2025-10-21 10:15:36] Invoking k8s-log-analyzer subagent
# [2025-10-21 10:16:12] Root cause identified: OOMKilled in proteus-dev
# [2025-10-21 10:16:15] Creating GitHub issue artemishealth/proteus#453
# [2025-10-21 10:16:18] Posting Teams notification
# [2025-10-21 10:16:20] Cycle complete - 80 seconds
```

#### Step 2: Show what it discovered

```bash
# View the latest monitoring report
cat /tmp/eks-monitoring-reports/2025-10-21-10-15-00.json
```

**Report contents (example):**
```json
{
  "cycle_number": 47,
  "timestamp": "2025-10-21T10:15:00Z",
  "cluster": "dev-eks",
  "issues_found": [
    {
      "namespace": "proteus-dev",
      "severity": "critical",
      "issue_type": "CrashLoopBackOff",
      "affected_pods": ["proteus-api-7d8f9c-xyz"],
      "root_cause": "OOMKilled - container exceeded memory limit (512Mi)",
      "related_deployment": "proteus-api",
      "recent_changes": [
        {
          "type": "github_pr",
          "pr_number": 452,
          "title": "Add caching layer to API",
          "merged_at": "2025-10-21T09:45:00Z",
          "merged_by": "developer@example.com"
        }
      ],
      "recommendations": [
        "Increase memory limit to 1Gi",
        "Review caching implementation for memory leaks",
        "Add memory profiling to staging environment"
      ],
      "auto_remediation_taken": "Restarted deployment (safe: 3 replicas)",
      "github_issue": "https://github.com/artemishealth/proteus/issues/453",
      "jira_ticket": "OPS-1234"
    }
  ]
}
```

#### Step 3: Show the safety hooks in action

```bash
# View the action audit log
tail -f /tmp/claude-k8s-agent-actions.log
```

**Audit log shows:**
```
[2025-10-21 10:15:40] TOOL_CALL: mcp__kubernetes__pods_restart
  Namespace: proteus-dev
  Deployment: proteus-api

[2025-10-21 10:15:40] SAFETY_VALIDATOR: EVALUATING
  Check 1: Is namespace protected? NO (proteus-dev is dev namespace)
  Check 2: Does deployment have 2+ replicas? YES (3 replicas)
  Check 3: Is this a dangerous operation? NO (rolling restart is safe)
  DECISION: ALLOW

[2025-10-21 10:15:41] ACTION_LOGGER: LOGGED
  Action: kubectl rollout restart deployment/proteus-api -n proteus-dev
  Justification: CrashLoopBackOff detected, safe to restart (3 replicas)

[2025-10-21 10:15:42] TEAMS_NOTIFIER: SENT
  Channel: #devops-alerts
  Message: "🤖 Auto-remediation: Restarted proteus-api deployment (3 pods in CrashLoopBackOff)"
```

#### What to highlight:

1. **Autonomous operation** - Ran on schedule, no human intervention
2. **Full context gathering** - Checked pods, logs, recent deployments, GitHub PRs
3. **Root cause analysis** - Identified OOM issue and correlated with recent PR
4. **Safety gates** - Validated operation before execution (3 replicas = safe)
5. **Documentation** - Created GitHub issue and Jira ticket automatically
6. **Team awareness** - Teams notification sent

---

### Demo 2: Interactive Troubleshooting via API (5 min)

**Scenario:** You get a Slack alert and want to investigate

#### Step 1: Open the interactive API documentation

```bash
# Start the OnCall API
docker compose up oncall-agent-api -d

# Open Swagger UI
open http://localhost:8000/docs
```

#### Step 2: Simple query via Swagger UI

Click on `POST /query` endpoint and try:

**Request:**
```json
{
  "message": "What's wrong with proteus-dev namespace right now?"
}
```

**Response (generated in ~15 seconds):**
```json
{
  "response": "I found 3 pods in CrashLoopBackOff state in the proteus-dev namespace:\n\n**Affected Pods:**\n- proteus-api-7d8f9c-xyz (restarted 8 times in last 10 minutes)\n- proteus-api-7d8f9c-abc (restarted 7 times)\n- proteus-api-7d8f9c-def (restarted 6 times)\n\n**Root Cause:**\nAll pods are being OOMKilled (Out of Memory). Current memory limit is 512Mi, but pods are trying to use 650-700Mi.\n\n**Recent Changes:**\nPR #452 'Add caching layer to API' was merged 30 minutes ago by developer@example.com. This likely introduced additional memory usage.\n\n**Recommended Actions:**\n1. Increase memory limit to 1Gi in deployment manifest\n2. Review caching implementation for memory efficiency\n3. Consider adding memory profiling to identify leaks\n4. Rollback PR #452 if issue persists\n\n**AWS Resources:**\nEC2 instances in proteus-dev node group have sufficient capacity (60% memory utilization).",

  "metadata": {
    "query_time": "14.2s",
    "tokens_used": 8234,
    "tools_called": [
      "list_pods",
      "get_pod_logs",
      "search_github_prs",
      "get_aws_ec2_instances"
    ]
  }
}
```

#### Step 3: Follow-up questions with sessions

Click on `POST /session` to create a conversation session:

**Create session:**
```json
{
  "initial_message": "What's wrong with proteus-dev?"
}
```

**Response includes session_id:**
```json
{
  "session_id": "sess_abc123",
  "response": "I found 3 pods in CrashLoopBackOff...",
  "created_at": "2025-10-21T10:20:00Z",
  "expires_at": "2025-10-21T10:50:00Z"
}
```

**Now ask follow-up questions** using `POST /query` with session_id:

```json
{
  "message": "What was the last deployment to this namespace?",
  "session_id": "sess_abc123"
}
```

**Claude remembers context:**
```json
{
  "response": "The last deployment to proteus-dev was 35 minutes ago:\n\n**Deployment Details:**\n- Service: proteus-api\n- Version: v2.14.5\n- Deployed by: ArgoCD (auto-sync)\n- Source: GitHub PR #452\n- Commit: a1b2c3d\n\nThis deployment introduced the caching layer I mentioned earlier, which is likely causing the OOM issues we discussed."
}
```

#### What to highlight:

1. **Interactive troubleshooting** - Ask questions in natural language
2. **Multi-turn conversations** - Claude remembers context
3. **Tool integration** - Automatically checks K8s, GitHub, AWS
4. **Fast responses** - 10-15 seconds for comprehensive analysis
5. **Easy to integrate** - Standard HTTP API, works with any tool

---

### Demo 3: MCP Magic - The Secret Sauce (5 min)

**"What makes this different from ChatGPT?"**

#### Without MCP (Manual Approach)

**What you'd type manually:**
```bash
# Check pods
kubectl get pods -n proteus-dev

# Describe failing pod
kubectl describe pod proteus-api-7d8f9c-xyz -n proteus-dev

# Get logs
kubectl logs proteus-api-7d8f9c-xyz -n proteus-dev --tail=100

# Check recent PRs
gh pr list --repo artemishealth/proteus --state merged --limit 5

# Copy-paste results between tools...
# Manually correlate the data...
# Write up findings...
```

**Time: 10-15 minutes of manual work**

---

#### With MCP (AI Approach)

**What you tell Claude:**
```
"Check proteus-dev health and correlate with recent deployments"
```

**What Claude does automatically:**

```python
# Claude's internal tool calls (via MCP)

# 1. List pods in namespace
result1 = mcp__kubernetes__pods_list(
    namespace="proteus-dev"
)

# 2. Check events for issues
result2 = mcp__kubernetes__events_list(
    namespace="proteus-dev",
    field_selector="type=Warning"
)

# 3. Get pod logs for failing pods
result3 = mcp__kubernetes__pods_logs(
    namespace="proteus-dev",
    pod_name="proteus-api-7d8f9c-xyz",
    tail_lines=100
)

# 4. Search recent GitHub activity
result4 = mcp__github__search_code(
    repo="artemishealth/proteus",
    query="path:k8s/ proteus-api"
)

# 5. Get recent PRs
result5 = mcp__github__list_pull_requests(
    repo="artemishealth/proteus",
    state="closed",
    limit=5
)

# Claude correlates all data and explains root cause
```

**Time: 15 seconds**

---

#### Show the MCP Configuration

**File: `eks/.claude/settings.json`**

```json
{
  "mcpServers": {
    "kubernetes": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-kubernetes"
      ],
      "env": {
        "KUBECONFIG": "/root/.kube/config",
        "K8S_MCP_LOG_LEVEL": "info"
      }
    },
    "github": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-github"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"
      }
    }
  }
}
```

**What this means:**
- MCP servers are external processes that give Claude structured access to tools
- Each MCP server exposes specific capabilities (pods_list, events_list, etc.)
- Claude can call these tools just like calling functions
- Type-safe, consistent, no string parsing required

---

#### The Power of Structured Access

**Without MCP:**
```python
# Brittle string parsing
output = subprocess.run(["kubectl", "get", "pods", "-o", "wide"])
lines = output.split("\n")
# Parse columns, handle edge cases, deal with format changes...
```

**With MCP:**
```python
# Structured, type-safe access
pods = mcp__kubernetes__pods_list(namespace="proteus-dev")
for pod in pods:
    print(f"Pod: {pod.name}, Status: {pod.status}, Restarts: {pod.restart_count}")
```

**Benefits:**
- No string parsing bugs
- Consistent results every time
- Built-in error handling
- Version-independent (MCP handles K8s API changes)

---

## PART 4: How It Works
### "The moving parts - demystified" (10 minutes)

### A. Claude Agent SDK vs Anthropic API

**Simple decision tree for choosing an approach:**

```
┌─────────────────────────────────────────────┐
│ Need automation that runs on its own?      │
│ (Scheduled monitoring, proactive alerts)   │
└──────────────┬──────────────────────────────┘
               │ YES
               ▼
       ┌───────────────────┐
       │ Claude Agent SDK  │
       │  (EKS approach)   │
       └───────────────────┘

       Features:
       ✓ Persistent memory across runs
       ✓ Multi-agent coordination
       ✓ Safety hooks and validation
       ✓ MCP integration built-in
       ✓ Complex workflow orchestration


┌─────────────────────────────────────────────┐
│ Need an API to integrate with tools?       │
│ (Slack bot, n8n workflows, curl commands)  │
└──────────────┬──────────────────────────────┘
               │ YES
               ▼
       ┌───────────────────┐
       │  Anthropic API    │
       │ (OnCall approach) │
       └───────────────────┘

       Features:
       ✓ Lightweight HTTP wrapper
       ✓ Stateless (or session-based)
       ✓ Easy integration (REST API)
       ✓ Fast startup, minimal deps
       ✓ Direct library calls
```

---

### B. MCP (Model Context Protocol)
### "Why MCP matters"

#### The Problem MCP Solves

**Traditional approach (brittle and error-prone):**

```python
# Execute kubectl command
result = subprocess.run(
    ["kubectl", "get", "pods", "-n", "proteus-dev", "-o", "json"],
    capture_output=True,
    text=True
)

# Parse output
import json
try:
    data = json.loads(result.stdout)
    pods = data.get("items", [])
except json.JSONDecodeError:
    # Handle parsing errors
    pass

# Extract what you need
for pod in pods:
    name = pod["metadata"]["name"]
    status = pod["status"]["phase"]
    # Hope the JSON structure doesn't change...
```

**Issues:**
- Command output format can change between K8s versions
- Error handling is manual
- No type safety
- Brittle string parsing
- Need to know exact kubectl syntax

---

#### MCP Approach (structured and reliable)

```python
# Claude uses MCP tool
pods = mcp__kubernetes__pods_list(namespace="proteus-dev")

# Structured response (always consistent)
for pod in pods:
    print(f"Name: {pod.name}")
    print(f"Status: {pod.status}")
    print(f"Restarts: {pod.restart_count}")
    print(f"Node: {pod.node_name}")
```

**Benefits:**
- **Type-safe**: Structured data, not string parsing
- **Version-independent**: MCP server handles API changes
- **Built-in error handling**: Errors are structured and actionable
- **Discoverable**: Claude knows what tools are available
- **Consistent**: Same interface across different tools (K8s, GitHub, Jira)

---

#### MCP Server Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Claude Agent                      │
│  (Decides which tools to call based on user query) │
└─────────────┬───────────────────────────────────────┘
              │
              │ "I need to check pod health"
              │
              ▼
┌─────────────────────────────────────────────────────┐
│              MCP Protocol Layer                      │
│    (Structured communication via JSON-RPC)          │
└─────────────┬───────────────────────────────────────┘
              │
    ┌─────────┼─────────┬──────────┐
    │         │         │          │
    ▼         ▼         ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│  K8s   │ │ GitHub │ │  Jira  │ │  AWS   │
│  MCP   │ │  MCP   │ │  MCP   │ │  MCP   │
│ Server │ │ Server │ │ Server │ │ Server │
└───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘
    │          │          │          │
    ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│ K8s API│ │ GitHub │ │  Jira  │ │AWS SDK │
│        │ │  API   │ │  API   │ │        │
└────────┘ └────────┘ └────────┘ └────────┘
```

**Each MCP server:**
- Runs as a separate process
- Exposes specific tools (list_pods, create_issue, etc.)
- Handles authentication and error handling
- Translates between Claude's requests and the underlying API

---

#### Available MCP Servers

**Official Anthropic MCP Servers:**
- `@modelcontextprotocol/server-kubernetes` - K8s cluster operations
- `@modelcontextprotocol/server-github` - GitHub repo management
- `@modelcontextprotocol/server-gitlab` - GitLab integration
- `@modelcontextprotocol/server-slack` - Slack messaging
- `@modelcontextprotocol/server-postgres` - Database queries
- `@modelcontextprotocol/server-filesystem` - File operations

**Third-party MCP Servers:**
- Atlassian (Jira/Confluence)
- AWS (EC2, S3, CloudWatch)
- Datadog (metrics and monitoring)
- PagerDuty (incident management)

**Build your own:**
- MCP protocol is open source
- Create custom MCP servers for internal tools
- Example: Your ticketing system, internal APIs, legacy systems

---

### C. Safety Hooks
### "How we prevent AI from breaking production"

#### The Hook Chain

When Claude wants to execute a potentially dangerous operation, it goes through a validation pipeline:

```
┌─────────────────────────────────────────────┐
│ Claude decides: "I should restart this pod" │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│        1. Safety Validator Hook              │
│                                              │
│  Questions:                                  │
│  ❓ Is this namespace protected?            │
│     (kube-system, production = BLOCK)       │
│  ❓ Is this a dangerous command?            │
│     (--all-namespaces, delete ns = BLOCK)   │
│  ❓ Does deployment have 2+ replicas?       │
│     (1 replica = BLOCK, 2+ = ALLOW)         │
│  ❓ Is this operation approved?             │
│     (rolling restart = YES, delete pv = NO) │
│                                              │
│  Decision: ALLOW / DENY                     │
└──────────────┬──────────────────────────────┘
               │ ALLOW
               ▼
┌──────────────────────────────────────────────┐
│         2. Action Logger Hook                │
│                                              │
│  Logs to audit trail:                        │
│  - Timestamp                                 │
│  - Tool called                               │
│  - Parameters                                │
│  - Justification from Claude                 │
│  - Safety decision                           │
│                                              │
│  File: /tmp/claude-k8s-agent-actions.log    │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│         3. Teams Notifier Hook               │
│                                              │
│  Sends real-time notification:               │
│  🤖 Action: kubectl rollout restart         │
│  📍 Namespace: proteus-dev                  │
│  🎯 Target: deployment/proteus-api          │
│  ✅ Safety: Validated (3 replicas)         │
│  📝 Reason: CrashLoopBackOff detected       │
│                                              │
│  Channel: #devops-alerts                    │
└──────────────┬──────────────────────────────┘
               │
               ▼
       ┌───────────────┐
       │ Execute Action │
       └───────────────┘
```

---

#### Safety Validator Rules

**File: `eks/.claude/hooks/safety_validator.py`**

**Protected Namespaces (NEVER allow destructive operations):**
- `kube-system` - Core K8s components
- `kube-public` - Public cluster resources
- `kube-node-lease` - Node heartbeat data
- `artemis-preprod`, `preprod` - Pre-production environments
- `artemis-prod`, `production`, `prod` - Production environments

**Dangerous Command Patterns (ALWAYS block):**
```python
DANGEROUS_PATTERNS = [
    r'kubectl\s+delete\s+namespace',           # Namespace deletion
    r'kubectl\s+delete\s+pv',                  # PersistentVolume deletion
    r'--all-namespaces',                       # Bulk operations
    r'-A\s',                                   # Shorthand bulk operations
    r'rm\s+-rf\s+/',                          # Filesystem destruction
    r'kubectl\s+delete.*--all',               # Delete all resources
]
```

**Dangerous MCP Operations (Complete blocks):**
```python
BLOCKED_MCP_OPERATIONS = [
    'mcp__kubernetes__namespaces_delete',
    'mcp__kubernetes__persistentvolumes_delete',
    'mcp__kubernetes__clusterroles_delete',
    'mcp__kubernetes__nodes_delete',
]
```

**Approved Auto-Remediation (For dev/staging clusters only):**
- ✅ Rolling restart deployments with **2+ replicas** (zero-downtime)
- ✅ Delete Failed/Evicted pods (cleanup)
- ✅ Scale deployments by **±2 replicas** (gradual changes)
- ✅ Delete individual pods in non-system namespaces

**Replica Count Validation:**
```python
# Safe: Rolling restart with multiple replicas
kubectl rollout restart deployment/api -n dev
# ✅ ALLOWED if deployment has 2+ replicas

# Unsafe: Restart single-replica deployment
kubectl rollout restart deployment/worker -n dev
# ❌ BLOCKED if deployment has 1 replica (would cause downtime)
```

---

#### Hook Response Format

**When operation is DENIED:**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "BLOCKED: Cannot delete namespace 'production' - protected namespace"
  }
}
```

Claude sees this and responds to the user:
> "I wanted to delete that namespace, but my safety validator blocked it because 'production' is a protected namespace. I recommend creating a support ticket for the platform team instead."

**When operation is ALLOWED:**
```json
{}
```

Empty response = proceed with operation.

---

#### Real Example: Hook in Action

**Scenario:** Claude detects a deployment stuck in CrashLoopBackOff

**Claude's thought process:**
```
1. I found proteus-api in CrashLoopBackOff
2. I should restart the deployment
3. Let me check: does it have multiple replicas?
   → Yes, 3 replicas
4. Calling tool: mcp__kubernetes__deployment_restart
```

**Hook validation:**
```bash
# Safety validator receives:
{
  "tool_name": "mcp__kubernetes__deployment_restart",
  "tool_input": {
    "namespace": "proteus-dev",
    "deployment": "proteus-api"
  }
}

# Safety validator checks:
1. Is "proteus-dev" a protected namespace? NO ✓
2. Query K8s: How many replicas? 3 ✓
3. Is this an approved operation? YES (restart with 2+ replicas) ✓

# Safety validator responds:
{}  # Empty = ALLOW

# Action logger writes:
[2025-10-21 10:15:41] ALLOWED
  Tool: mcp__kubernetes__deployment_restart
  Namespace: proteus-dev
  Deployment: proteus-api
  Replicas: 3
  Justification: CrashLoopBackOff detected, safe rolling restart

# Teams notifier sends:
🤖 Auto-remediation executed
📍 Namespace: proteus-dev
🎯 Action: Restarted deployment/proteus-api
✅ Safety: Validated (3 replicas, zero-downtime rolling restart)
📝 Reason: 3 pods in CrashLoopBackOff state
```

**Result:** Safe, logged, team-aware remediation in seconds.

---

### D. Multi-Agent Coordination (EKS Approach)

**How the EKS agent uses specialized subagents:**

```
┌─────────────────────────────────────────────┐
│         Main Orchestrator Agent             │
│  (Decides what needs to be investigated)    │
└──────────────┬──────────────────────────────┘
               │
               │ "Run health check"
               ▼
┌──────────────────────────────────────────────┐
│      1. k8s-diagnostics subagent             │
│  Specialized for: Fast bulk health checks    │
│  Tools: pods_list, events_list, deployments  │
│  Returns: List of issues found               │
└──────────────┬──────────────────────────────┘
               │
               │ Found: "3 pods CrashLooping in proteus-dev"
               ▼
┌──────────────────────────────────────────────┐
│       2. k8s-log-analyzer subagent           │
│  Specialized for: Root cause from logs       │
│  Tools: pods_logs, events_list               │
│  Returns: "OOMKilled - memory limit too low" │
└──────────────┬──────────────────────────────┘
               │
               │ Root cause: OOM
               ▼
┌──────────────────────────────────────────────┐
│       3. k8s-github subagent                 │
│  Specialized for: Deployment correlation     │
│  Tools: list_prs, search_code, create_issue  │
│  Returns: "PR #452 merged 30 min ago"        │
└──────────────┬──────────────────────────────┘
               │
               │ Correlated with recent deployment
               ▼
┌──────────────────────────────────────────────┐
│       4. k8s-remediation subagent            │
│  Specialized for: Safe cluster fixes         │
│  Tools: deployment_restart (with validation) │
│  Returns: "Restarted deployment safely"      │
└──────────────┬──────────────────────────────┘
               │
               │ Issue resolved
               ▼
┌──────────────────────────────────────────────┐
│       5. k8s-jira subagent                   │
│  Specialized for: Ticket management          │
│  Tools: create_issue, add_comment            │
│  Returns: "Created OPS-1234"                 │
└──────────────────────────────────────────────┘
```

**Why this matters:**
- Each subagent is optimized for its specific task
- Subagents can't see each other's context (isolation)
- Orchestrator coordinates the workflow
- Specialized models can be used per subagent
- Parallel execution where possible (diagnostics + cost analysis)

---

## PART 5: Real-World Impact
### "What we've learned running this in production" (5 minutes)

### Metrics from dev-eks Cluster
**Environment:** 40 nodes, 20+ namespaces, 200+ pods

#### Before AI Automation

**Incident Triage:**
- **Time to initial diagnosis:** 30-60 minutes
- **Manual kubectl commands:** ~20 per incident
- **Tools switched between:** 5+ (kubectl, GitHub, Jira, AWS Console, Datadog)
- **Knowledge requirements:** Senior engineers only
- **After-hours impact:** High (wake up, context-switch, investigate)
- **Documentation quality:** Inconsistent (depends on engineer's notes)

**Example incident timeline:**
```
00:15 - PagerDuty alert: Pod CrashLooping
00:17 - Engineer wakes up, opens laptop
00:20 - kubectl get pods (find affected pods)
00:25 - kubectl logs (read through logs)
00:30 - kubectl describe pod (check events)
00:35 - Check GitHub for recent PRs
00:40 - Check Jira for related tickets
00:45 - Check AWS for resource issues
00:50 - Correlate data, form hypothesis
00:55 - Create Jira ticket with findings
01:00 - Decide on remediation
01:05 - Execute fix
```

**Total time:** ~60 minutes from alert to resolution

---

#### After AI Automation

**Incident Triage:**
- **Time to initial diagnosis:** 60-90 seconds
- **Automated correlation:** Pod logs + GitHub PRs + AWS resources + Jira history
- **Tools required:** None (AI does it all)
- **Knowledge requirements:** Junior engineers can troubleshoot with AI guidance
- **After-hours impact:** Low (AI handles initial triage, pages only if needed)
- **Documentation quality:** Consistent, comprehensive, automatically created

**Example incident timeline (with EKS agent):**
```
00:15 - Pod starts CrashLooping
00:16 - EKS agent detects issue in scheduled monitoring cycle
00:17 - AI gathers: pod logs, events, recent deployments, GitHub PRs
00:18 - AI identifies root cause: OOMKilled from PR #452
00:19 - AI creates GitHub issue with full context
00:20 - AI creates Jira ticket OPS-1234
00:21 - AI validates: 3 replicas = safe to restart
00:22 - AI executes rolling restart (zero-downtime)
00:23 - Teams notification sent: "Issue detected and resolved"
```

**Total time:** ~90 seconds from detection to resolution
**Human intervention:** Zero (for approved auto-remediation cases)

---

### Quantified Benefits

#### Time Savings
- **Per-incident triage time:** 30-60 min → 60-90 sec = **~97% reduction**
- **Engineer context-switch overhead:** Eliminated for auto-resolved issues
- **Documentation time:** Manual notes → Auto-generated = **~15 min saved per incident**

#### Incident Response Quality
- **Root cause identification:** Improved from ~60% → ~90% accuracy
- **Correlation of related changes:** Manual (often missed) → Automatic (always checked)
- **Documentation completeness:** Variable → Consistently comprehensive

#### Team Impact
- **After-hours pages:** Reduced by ~40% (auto-resolution of common issues)
- **Junior engineer effectiveness:** Can now handle incidents that required senior engineers
- **Knowledge sharing:** AI explanations democratize troubleshooting knowledge

---

### Unexpected Benefits

#### 1. Documentation by Default
Every incident gets:
- Full timeline of events
- Correlation with code changes
- Root cause analysis
- Remediation steps taken
- Links to related resources (PRs, commits, AWS resources)

**Result:** Better postmortems, easier pattern recognition

#### 2. Pattern Recognition at Scale
AI spots recurring issues:
- "This is the 4th OOM in proteus-api this week"
- "Memory issues always follow deployments from feature branch X"
- "This service has been restarting every Tuesday at 2am for 3 weeks"

**Result:** Proactive fixes instead of reactive firefighting

#### 3. Knowledge Democratization
Junior engineers get AI explanations:
```
"This pod is in CrashLoopBackOff because it's being OOMKilled.

Here's what that means:
- The container tried to use more memory than its limit (512Mi)
- Linux kernel killed the process to protect the node
- Kubernetes restarted it, but it hit the same limit again
- This creates a restart loop

The fix: Increase the memory limit in the deployment manifest.
Look at k8s/deployment.yaml line 45."
```

**Result:** Learning opportunity, not just fire drill

#### 4. Noise Reduction
**Before:** 100+ Jira comments/day from monitoring alerts
**After:** ~5 meaningful comments/day (smart filtering)

**How:**
- AI recognizes duplicate issues
- AI groups related incidents
- AI only comments when new information is available
- AI auto-resolves transient issues

**Result:** Signal over noise, reduced alert fatigue

---

### Challenges We Solved

#### Challenge 1: MCP Kubernetes Server Bug
**Problem:** MCP server doesn't properly filter by namespace
- Query for "proteus-dev" namespace
- Returns ALL 300+ pods from entire cluster
- Exceeds 25K token limit
- Query fails

**Solution:** Fallback to kubectl via Bash tool
```python
# Prefer MCP for small queries
result = mcp__kubernetes__pods_list(namespace="kube-system")  # ~10 pods, works

# Fall back to kubectl for larger namespaces
result = bash("kubectl get pods -n proteus-dev -o json")  # 50+ pods, safer
```

**Learning:** Have fallback strategies for MCP limitations

---

#### Challenge 2: Token Costs
**Problem:** 15K tokens per monitoring cycle = expensive
- 4 cycles/hour (15 min intervals)
- ~1.4M tokens/day
- ~$3-5/day for dev cluster
- Would be ~$30-50/day for production cluster

**Solutions implemented:**
1. **Smart caching:** Only analyze pods that changed since last cycle
2. **Conditional subagents:** Only invoke log-analyzer if issues found
3. **Summarization:** Store summaries, not full logs
4. **Model selection:** Use Haiku for diagnostics, Sonnet for complex analysis

**Result:** Reduced to ~8K tokens/cycle (~$1.50/day)

---

#### Challenge 3: Rate Limits
**Problem:** Too many K8s API calls
- 20+ kubectl commands per cycle
- K8s API rate limiting (50 QPS per client)
- Timeouts in large clusters

**Solution:** Bulk queries via MCP
```python
# Bad: Sequential calls (20+ API requests)
for namespace in namespaces:
    pods = kubectl(f"get pods -n {namespace}")

# Good: Bulk query (1 API request)
all_pods = mcp__kubernetes__pods_list()  # All namespaces at once
filter_client_side(all_pods)
```

**Result:** Faster cycles, no rate limiting

---

#### Challenge 4: False Positives
**Problem:** AI over-reacting to normal operations
- Pod restarts during deployments → Not an issue
- Temporary Pending state → Normal for autoscaling
- ImagePullBackOff for 10 seconds → Transient network issue

**Solution:** Time-based thresholds
```python
# Only alert if issue persists
if pod.restart_count > 5 AND pod.age > 5 minutes:
    investigate()

if pod.status == "CrashLoopBackOff" AND pod.crash_count > 3:
    remediate()
```

**Result:** ~70% reduction in false positive alerts

---

### Cost-Benefit Analysis

**Monthly costs for dev-eks cluster (40 nodes, 200 pods):**
- AI monitoring: ~$45/month (1.5M tokens/day @ Claude Sonnet pricing)
- Saved engineering time: ~20 hours/month = $4,000/month (@ $200/hr blended rate)
- Prevented downtime: ~2 hours/month = $10,000/month (estimated business impact)

**ROI: ~300x**

**Intangible benefits:**
- Reduced burnout (less after-hours pages)
- Faster onboarding (AI teaches juniors)
- Better sleep (confidence in autonomous monitoring)

---

## PART 6: Getting Started
### "How you could adopt this" (10 minutes)

### Quick Wins (Week 1-2)
**Goal:** Get hands-on experience with minimal investment

#### Option 1: Try the OnCall API Locally

**Time investment:** 30 minutes

```bash
# Clone the repository
git clone <your-repo-url>
cd claude-agents/oncall

# Set up environment
cp .env.example .env

# Edit .env and add your Anthropic API key
# Get free credits: https://console.anthropic.com/
nano .env
# Add: ANTHROPIC_API_KEY=sk-ant-...

# Start the API
docker compose up oncall-agent-api

# In another terminal, test it
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What pods are running in kube-system?"
  }'
```

**What you get:**
- Working AI agent answering K8s questions
- Interactive API at http://localhost:8000/docs
- Understanding of how Claude interacts with your cluster
- Zero production risk (read-only by default)

**Next steps:**
- Test different queries: "What deployments changed recently?"
- Try session-based conversations
- Add your internal tools to the API

---

#### Option 2: Run EKS Monitor in Read-Only Mode

**Time investment:** 1-2 hours

```bash
# Clone the repository
git clone <your-repo-url>
cd claude-agents/eks

# Set up environment
cp .env.example .env

# Edit .env
nano .env
# Required settings:
# - ANTHROPIC_API_KEY=sk-ant-...
# - GITHUB_PERSONAL_ACCESS_TOKEN=ghp_... (for PR correlation)
# - CLUSTER_NAME=dev-eks (your dev cluster name)

# IMPORTANT: Disable auto-remediation for testing
# In .env, set:
# AUTO_REMEDIATION_ENABLED=false

# Edit .claude/CLAUDE.md to describe YOUR cluster
nano .claude/CLAUDE.md
# Update:
# - Cluster name and region
# - Critical namespaces to monitor
# - Team escalation contacts

# Start monitoring in read-only mode
docker compose up

# Watch the logs
docker compose logs -f eks-monitoring-daemon
```

**What you get:**
- AI monitoring your cluster every 15 minutes
- Teams notifications about issues (no auto-fix)
- GitHub issues created with full context
- Monitoring reports in `/tmp/eks-monitoring-reports/`

**Safety:** Read-only mode = AI reports issues but doesn't fix them

---

### Medium Investment (Month 1)
**Goal:** Deploy to dev cluster, evaluate effectiveness

#### Deploy to Kubernetes

```bash
# Review the Kubernetes manifests
cd k8s-monitor/k8s/
ls -la
# You'll see:
# - deployment.yaml          (Pod deployment)
# - orchestrator-configmap.yaml  (Cluster context)
# - agents-configmap.yaml    (Subagent definitions)
# - secret.yaml              (API keys - edit this)
# - serviceaccount.yaml      (RBAC permissions)

# Edit the cluster context ConfigMap
nano orchestrator-configmap.yaml
# Update CLAUDE.md with your cluster details

# Create the secret with your API keys
nano secret.yaml
# Add your ANTHROPIC_API_KEY and GITHUB_PERSONAL_ACCESS_TOKEN
# (base64 encoded)

echo -n 'sk-ant-your-key' | base64
echo -n 'ghp_your-token' | base64

# Deploy to your dev cluster
kubectl apply -f .

# Watch it start up
kubectl logs -f deployment/k8s-monitor -n monitoring

# Check monitoring reports
kubectl exec deployment/k8s-monitor -n monitoring -- \
  ls -la /tmp/eks-monitoring-reports/
```

**What you get:**
- Production-like deployment in dev cluster
- ConfigMap-driven configuration (GitOps-ready)
- Real monitoring of your dev workloads
- Data to evaluate effectiveness

**Evaluation criteria:**
- Does it catch issues you care about?
- Are the root causes accurate?
- Are the recommendations actionable?
- Is the noise level acceptable?

---

### Customization Ideas

#### 1. Add Your Own MCP Servers

**Example: Add PagerDuty integration**

```bash
# Install PagerDuty MCP server (hypothetical)
npm install -g @your-org/mcp-server-pagerduty

# Add to .claude/settings.json
{
  "mcpServers": {
    "pagerduty": {
      "command": "npx",
      "args": ["-y", "@your-org/mcp-server-pagerduty"],
      "env": {
        "PAGERDUTY_API_KEY": "${PAGERDUTY_API_KEY}"
      }
    }
  }
}
```

Now Claude can:
- Create PagerDuty incidents automatically
- Correlate K8s issues with on-call schedules
- Auto-acknowledge alerts when issues are resolved

---

#### 2. Create Specialized Subagents

**Example: Database health checker**

Create `.claude/agents/db-health-checker.md`:

```markdown
---
name: db-health-checker
description: Specialized subagent for PostgreSQL health monitoring
tools: Read, Bash, mcp__kubernetes__pods_list, mcp__kubernetes__pods_exec
model: $DB_HEALTH_MODEL
---

# Database Health Checker Subagent

You are a specialized agent for monitoring PostgreSQL database health in Kubernetes.

## Your Responsibilities

1. Check database pod health (CPU, memory, disk)
2. Execute health check queries (SELECT 1, connection count)
3. Monitor replication lag for HA setups
4. Identify slow queries and lock contention
5. Recommend index optimizations

## Tools Available

- mcp__kubernetes__pods_list - Find database pods
- mcp__kubernetes__pods_exec - Execute psql commands
- Bash - Run pg_stat_* queries

## Safety Rules

- NEVER run DDL statements (CREATE, ALTER, DROP)
- NEVER run DML statements (INSERT, UPDATE, DELETE)
- Only run SELECT queries for health checks
- Only connect to read replicas, not primary (unless explicitly needed)

## Output Format

Return a structured report:
- Database health status (Healthy/Degraded/Critical)
- Key metrics (connections, cache hit rate, replication lag)
- Identified issues with severity
- Recommendations for optimization
```

Add model to `.env`:
```bash
DB_HEALTH_MODEL=claude-sonnet-4-20250514
```

Invoke from orchestrator:
```python
result = await client.query(
    "Use Task tool to invoke db-health-checker subagent for PostgreSQL in production"
)
```

---

#### 3. Extend the OnCall API

**Example: Add Slack slash command**

```python
# File: oncall/src/api/slack_integration.py

from fastapi import APIRouter, Request
from slack_sdk import WebClient
from .agent_client import OnCallAgentClient

router = APIRouter()
slack_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
agent = OnCallAgentClient()

@router.post("/slack/commands/ask-claude")
async def slack_command(request: Request):
    """
    Handles Slack slash command: /ask-claude <question>

    Usage in Slack:
    /ask-claude What's wrong with proteus-dev?
    """
    form_data = await request.form()
    user_question = form_data.get("text")
    channel_id = form_data.get("channel_id")

    # Send "thinking" message
    slack_client.chat_postMessage(
        channel=channel_id,
        text="🤔 Investigating... this will take ~15 seconds"
    )

    # Query the agent
    response = await agent.query(user_question)

    # Send response
    slack_client.chat_postMessage(
        channel=channel_id,
        text=f"🤖 Claude's Analysis:\n\n{response}"
    )

    return {"ok": True}
```

Register in `api_server.py`:
```python
from .slack_integration import router as slack_router
app.include_router(slack_router, prefix="/integrations")
```

**Result:** Your team can ask questions directly in Slack!

---

#### 4. Integrate with Your Ticketing System

**Example: ServiceNow integration**

```python
# File: oncall/src/tools/servicenow_integrator.py

import requests
from typing import Dict, Any

class ServiceNowIntegrator:
    def __init__(self):
        self.instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
        self.username = os.getenv("SERVICENOW_USERNAME")
        self.password = os.getenv("SERVICENOW_PASSWORD")

    def create_incident(
        self,
        short_description: str,
        description: str,
        severity: str,
        assignment_group: str
    ) -> str:
        """Create a ServiceNow incident"""

        url = f"{self.instance_url}/api/now/table/incident"

        payload = {
            "short_description": short_description,
            "description": description,
            "urgency": self._map_severity(severity),
            "assignment_group": assignment_group,
            "caller_id": "claude-ai-agent"
        }

        response = requests.post(
            url,
            auth=(self.username, self.password),
            json=payload,
            headers={"Content-Type": "application/json"}
        )

        incident_number = response.json()["result"]["number"]
        return incident_number

    def _map_severity(self, severity: str) -> str:
        """Map our severity to ServiceNow urgency"""
        mapping = {
            "critical": "1",
            "high": "2",
            "medium": "3",
            "low": "4"
        }
        return mapping.get(severity, "3")
```

Add to agent tools:
```python
# In custom_tools.py
{
    "name": "create_servicenow_incident",
    "description": "Create an incident in ServiceNow",
    "input_schema": {
        "type": "object",
        "properties": {
            "short_description": {"type": "string"},
            "description": {"type": "string"},
            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]}
        }
    }
}
```

---

### Cost Estimation and Budgeting

#### Anthropic API Pricing (as of Oct 2024)

**Claude Sonnet (claude-sonnet-4-20250514):**
- Input: $3.00 per million tokens
- Output: $15.00 per million tokens

**Claude Haiku (claude-haiku-4-5-20251001):**
- Input: $0.80 per million tokens
- Output: $4.00 per million tokens

#### Cost Scenarios

**Scenario 1: OnCall API (On-Demand)**
```
Assumptions:
- 10 queries per day
- 8K tokens per query (5K input, 3K output)
- 30 days per month

Calculation:
- Input tokens: 10 queries × 5K tokens × 30 days = 1.5M tokens
- Output tokens: 10 queries × 3K tokens × 30 days = 0.9M tokens
- Input cost: 1.5M × $3.00 / 1M = $4.50
- Output cost: 0.9M × $15.00 / 1M = $13.50
- Total: $18/month
```

**Scenario 2: EKS Agent (Continuous Monitoring)**
```
Assumptions:
- 4 cycles per hour (15 min intervals)
- 15K tokens per cycle (10K input, 5K output)
- 24 hours per day, 30 days per month

Calculation:
- Cycles per month: 4 × 24 × 30 = 2,880 cycles
- Input tokens: 2,880 × 10K = 28.8M tokens
- Output tokens: 2,880 × 5K = 14.4M tokens
- Input cost: 28.8M × $3.00 / 1M = $86.40
- Output cost: 14.4M × $15.00 / 1M = $216.00
- Total: $302.40/month
```

**Cost optimization strategies:**
1. Use Haiku for simple diagnostics (80% cheaper)
2. Increase monitoring interval (15 min → 30 min = 50% savings)
3. Smart caching (only analyze changed pods)
4. Conditional subagent invocation (only when needed)

**Optimized EKS Agent cost:** ~$45-90/month

---

### Success Metrics

**How to measure if this is working:**

#### Quantitative Metrics
- **Mean Time to Detection (MTTD):** How fast are issues found?
- **Mean Time to Resolution (MTTR):** How fast are they fixed?
- **False Positive Rate:** What % of alerts are noise?
- **Auto-Resolution Rate:** What % of issues are fixed without human intervention?
- **Token Cost per Incident:** Is it cost-effective?

#### Qualitative Metrics
- **Engineer satisfaction:** Less stressful on-call?
- **Documentation quality:** Are postmortems better?
- **Knowledge sharing:** Can juniors handle more?
- **Alert fatigue:** Reduced or increased?

#### Tracking Dashboard (Example)

```python
# Monthly report query
SELECT
    COUNT(*) as total_incidents,
    AVG(detection_time_seconds) as avg_mttd,
    AVG(resolution_time_seconds) as avg_mttr,
    SUM(CASE WHEN auto_resolved THEN 1 ELSE 0 END) as auto_resolved_count,
    SUM(CASE WHEN false_positive THEN 1 ELSE 0 END) as false_positives,
    SUM(token_count) as total_tokens
FROM incidents
WHERE incident_date >= DATE_SUB(NOW(), INTERVAL 30 DAY)
```

---

## PART 7: Q&A and Discussion
### "Let's talk about your use cases" (15 minutes)

### Discussion Prompts

#### 1. Pain Point Discovery
**Questions to ask the audience:**

- "What's your biggest incident triage pain point?"
  - Manual correlation across tools?
  - Knowledge locked in specific engineers?
  - After-hours interruptions?
  - Documentation overhead?

- "How long does it typically take to diagnose a production issue?"
  - Minutes? Hours? Depends on who's on-call?

- "What percentage of your alerts are false positives?"
  - Do you get alert fatigue?
  - Are alerts actionable?

---

#### 2. Integration Opportunities
**Questions to explore:**

- "What tools would you want AI to integrate with?"
  - ServiceNow, PagerDuty, Splunk, Datadog?
  - Internal tools and APIs?
  - Legacy systems?

- "What would be your ideal Slack integration?"
  - `/ask-claude <question>` slash command?
  - Automatic incident threads with AI analysis?
  - Smart alert routing?

- "What data sources would be most valuable?"
  - APM tools (New Relic, Datadog)?
  - Log aggregation (Splunk, ELK)?
  - CI/CD systems (Jenkins, ArgoCD)?

---

#### 3. Safety and Governance
**Questions to address:**

- "What safeguards would you need for production use?"
  - More restrictive auto-remediation rules?
  - Approval workflows?
  - Audit logging requirements?
  - Compliance considerations?

- "How would you handle sensitive data?"
  - PII in logs?
  - Secrets in configuration?
  - GDPR/HIPAA requirements?

- "What level of autonomy are you comfortable with?"
  - Read-only analysis?
  - Auto-remediation for approved operations?
  - Full automation with human oversight?

---

#### 4. Success Measurement
**Questions to align on:**

- "How would you measure success?"
  - Time savings?
  - Reduced pages?
  - Improved MTTR?
  - Cost savings?

- "What would make this a 'must-have' vs 'nice-to-have'?"
  - What's the minimum value threshold?
  - What metrics matter most to your team?

- "What would be a good pilot project?"
  - Single service monitoring?
  - Specific use case (DB health, API performance)?
  - Dev cluster only initially?

---

### Potential Follow-Up Projects

Based on the discussion, here are potential next steps:

#### Option 1: Just Learn
**Time commitment:** 2-4 hours

- Fork this repository
- Run locally against your dev cluster
- Experiment with prompts and queries
- Learn MCP and Claude Agent SDK
- Share findings with the team

**Outcome:** Knowledge gained, no production commitment

---

#### Option 2: Build Something Cool
**Time commitment:** 1-2 weeks

- Identify a specific pain point
- Create a custom MCP server or subagent
- Integrate with your tools (Slack, ServiceNow, etc.)
- Demo to the team

**Examples:**
- Slack bot for incident triage
- Database health monitoring subagent
- Cost optimization recommender
- Security scanner with auto-remediation

**Outcome:** Custom tool solving a real problem

---

#### Option 3: Lighten the Load
**Time commitment:** 1 month

- Deploy to dev cluster
- Monitor for 2 weeks, tune configuration
- Measure MTTR and false positive rate
- Gradually enable auto-remediation for approved operations
- Expand to staging cluster

**Outcome:** Production-ready monitoring reducing on-call burden

---

#### Option 4: Make It a Feature
**Time commitment:** 3+ months

- Build a product around this
- Self-service platform for teams
- Multi-tenancy (multiple clusters/teams)
- Web UI for configuration
- Marketplace of MCP servers and subagents

**Outcome:** Internal platform teams can adopt

---

### Common Concerns and Responses

#### "What if the AI makes a mistake?"

**Response:**
- Safety hooks prevent dangerous operations
- All actions are logged for audit trail
- Start with read-only mode, gradually enable auto-remediation
- Replica count validation ensures zero-downtime operations
- Real-time Teams notifications keep team aware

**Example:** In 3 months of production use, zero incidents caused by AI. 40+ incidents resolved automatically.

---

#### "How do we handle sensitive data in logs?"

**Response:**
- MCP servers can be configured to redact PII
- Hook scripts can filter sensitive data before sending to Claude
- Use Claude's content filtering features
- Consider self-hosted models for highly sensitive environments

**Example implementation:**
```python
# In action_logger.py hook
def redact_sensitive_data(log_line: str) -> str:
    # Redact credit cards, SSNs, etc.
    log_line = re.sub(r'\d{4}-\d{4}-\d{4}-\d{4}', '[REDACTED]', log_line)
    log_line = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[REDACTED]', log_line)
    return log_line
```

---

#### "What about vendor lock-in with Anthropic?"

**Response:**
- MCP protocol is open source and model-agnostic
- Can swap Claude for other LLMs (OpenAI, Gemini, self-hosted)
- All infrastructure is containerized and portable
- Safety hooks and business logic are independent of model choice

**Example:** Change one environment variable to switch models:
```bash
ORCHESTRATOR_MODEL=openai/gpt-4-turbo
# or
ORCHESTRATOR_MODEL=ollama/llama3:70b  # Self-hosted
```

---

#### "How does this compare to just using ChatGPT?"

**Response:**
- **Structured tool access:** MCP gives Claude direct access to your infrastructure
- **Persistent memory:** Agent SDK maintains context across conversations
- **Safety hooks:** Pre-execution validation prevents mistakes
- **Automation:** Runs continuously without human prompts
- **Integration:** Native access to K8s, GitHub, Jira, etc. (not copy-pasting)

**ChatGPT is great for one-off questions. This is great for automated workflows.**

---

#### "What if we don't use Kubernetes?"

**Response:**
- The patterns apply to any infrastructure
- MCP servers exist for: AWS, Docker, Terraform, Ansible, etc.
- You can build custom MCP servers for your infrastructure
- The OnCall API approach works with any backend

**Examples:**
- VM-based infrastructure → Create MCP server for SSH/systemd
- AWS Lambda → Use AWS MCP server for function monitoring
- On-prem databases → Create custom MCP for DB health checks

---

## APPENDIX: Resources

### 1. This Repository

**GitHub:** `<your-repo-url>`

**Key documentation:**
- `/README.md` - Overview and quick start
- `/CLAUDE.md` - Detailed architecture and patterns
- `/docs/` - Additional guides and examples
- `/eks/README.md` - EKS agent specific docs
- `/oncall/README.md` - OnCall agent specific docs

**Example implementations:**
- `/eks/` - Autonomous monitoring agent
- `/oncall/` - On-demand API agent
- `/k8s-monitor/k8s/` - Kubernetes deployment manifests

---

### 2. Claude and MCP Documentation

**Claude Agent SDK:**
- Docs: https://docs.claude.com/en/api/agent-sdk/python
- GitHub: https://github.com/anthropics/anthropic-sdk-python

**Anthropic API:**
- Docs: https://docs.anthropic.com/
- API Reference: https://docs.anthropic.com/en/api/messages

**Model Context Protocol (MCP):**
- Official site: https://modelcontextprotocol.io/
- Specification: https://spec.modelcontextprotocol.io/
- Server examples: https://github.com/modelcontextprotocol/servers

---

### 3. Available MCP Servers

**Official Anthropic MCP Servers:**

Kubernetes:
```bash
npx -y @modelcontextprotocol/server-kubernetes
```

GitHub:
```bash
npx -y @modelcontextprotocol/server-github
```

GitLab:
```bash
npx -y @modelcontextprotocol/server-gitlab
```

Slack:
```bash
npx -y @modelcontextprotocol/server-slack
```

PostgreSQL:
```bash
npx -y @modelcontextprotocol/server-postgres
```

Filesystem:
```bash
npx -y @modelcontextprotocol/server-filesystem
```

**Community MCP Servers:**
- Browse: https://github.com/topics/mcp-server
- Examples: AWS, Datadog, PagerDuty, Terraform, etc.

---

### 4. Building Your Own MCP Server

**MCP Server Template:**
```python
# mcp_server_example.py
import json
import sys
from typing import Any, Dict

def handle_tool_call(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle a tool call from Claude.

    Your MCP server receives tool calls via stdin (JSON-RPC format)
    and returns results via stdout.
    """

    if tool_name == "my_custom_tool":
        # Implement your tool logic
        result = do_something(tool_input)
        return {"result": result}

    raise ValueError(f"Unknown tool: {tool_name}")

def main():
    """MCP server main loop"""
    for line in sys.stdin:
        request = json.loads(line)

        method = request.get("method")
        params = request.get("params", {})

        if method == "tools/call":
            tool_name = params["name"]
            tool_input = params["arguments"]

            result = handle_tool_call(tool_name, tool_input)

            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": result
            }

            print(json.dumps(response))
            sys.stdout.flush()

if __name__ == "__main__":
    main()
```

**Full tutorial:** https://modelcontextprotocol.io/docs/tutorials/building-a-server

---

### 5. Getting Help

**Anthropic Community:**
- Discord: https://discord.gg/anthropic
- Forum: https://community.anthropic.com/

**Internal Resources:**
- Slack channel: `#ai-incident-response` (create this!)
- Office hours: [Your availability]
- Wiki: [Your internal documentation]

**This Presentation:**
- Slides: `<link to slide deck>`
- Demo recordings: `<link to recordings>`
- Follow-up Q&A: [Schedule a meeting]

---

## Next Steps

### For Individuals
1. **Today:** Clone the repo and try the OnCall API locally
2. **This week:** Run a test query against your dev cluster
3. **This month:** Identify one pain point this could solve
4. **Share:** Tell your team what you learned

### For Teams
1. **This week:** Discuss as a team - is this interesting?
2. **Next week:** Identify a pilot project (small scope)
3. **This month:** Deploy to dev cluster, gather metrics
4. **Next month:** Evaluate results, decide on broader adoption

### For the Organization
1. **Short-term:** Create internal Slack channel for collaboration
2. **Medium-term:** Establish AI automation standards and best practices
3. **Long-term:** Build internal platform for AI-powered operations

---

## Thank You!

**Questions? Ideas? Want to collaborate?**

**Contact:**
- Presenter: Ari Sela
- Email: [your-email]
- Slack: @arisela
- Office hours: [your-availability]

**Let's build something cool together!**

---

## Bonus: Live Demo Script

If you want to follow along during the demo, here's the exact sequence:

### Demo 1: EKS Agent (5 min)

```bash
# Terminal 1: Start the agent
cd eks
docker compose up

# Terminal 2: Watch logs
docker compose logs -f eks-monitoring-daemon

# Terminal 3: View reports as they're created
watch -n 5 ls -lh /tmp/eks-monitoring-reports/

# After a cycle completes (~2 min):
cat /tmp/eks-monitoring-reports/$(ls -t /tmp/eks-monitoring-reports/ | head -1)

# Show action log
tail -20 /tmp/claude-k8s-agent-actions.log
```

---

### Demo 2: OnCall API (5 min)

```bash
# Terminal 1: Start API
cd oncall
docker compose up oncall-agent-api

# Browser: Open Swagger UI
open http://localhost:8000/docs

# In Swagger UI, try:
# 1. POST /query
{
  "message": "What pods are in CrashLoopBackOff right now?"
}

# 2. POST /session (create conversation)
{
  "initial_message": "Check proteus-dev health"
}
# Note the session_id in response

# 3. POST /query (follow-up question)
{
  "message": "What was the last deployment?",
  "session_id": "sess_..."
}

# Terminal 2: Watch logs to see tool calls
docker compose logs -f oncall-agent-api
```

---

### Demo 3: MCP in Action (5 min)

```bash
# Show MCP configuration
cat eks/.claude/settings.json | jq '.mcpServers'

# Test MCP server manually
npx -y @modelcontextprotocol/server-kubernetes

# In another terminal, test a tool call
# (This simulates what Claude does internally)
echo '{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "kubernetes_list_pods",
    "arguments": {"namespace": "kube-system"}
  }
}' | npx -y @modelcontextprotocol/server-kubernetes

# Show the structured response
# Compare to raw kubectl:
kubectl get pods -n kube-system
```

---

**End of Presentation**
