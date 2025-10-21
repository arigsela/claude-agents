---
marp: true
theme: default
paginate: true
backgroundColor: #fff
header: '**AI-Powered Incident Triage** | Ari Sela'
footer: 'From Hours to Minutes with Claude Code & MCP'
---

<!-- _paginate: false -->
<!-- _header: "" -->
<!-- _footer: "" -->
<!-- _class: lead -->

# AI-Powered Incident Triage
## From Hours to Minutes

**A practical demo of Claude Code & MCP for DevOps automation**

*Presenter: Ari Sela*

<!--
Welcome everyone! Today we're going to explore how AI can transform incident triage from a 30-60 minute manual process to a 60-second automated analysis.

This is a brunch and learn - no pressure to adopt anything. Just enjoy the demos and think about how this might help your team.
-->

---

# Agenda

1. **The Problem** (5 min) - Why manual triage is painful
2. **The Solution** (5 min) - Two AI deployment patterns
3. **Live Demos** (15 min) - See it in action
4. **How It Works** (10 min) - Architecture deep dive
5. **Real-World Impact** (5 min) - Metrics from production
6. **Getting Started** (10 min) - Your path to adoption
7. **Q&A** (15 min) - Your use cases

<!--
60 minutes total. Heavy on demos, light on theory.
We'll see both approaches in action, then discuss how you might use them.
-->

---

<!-- _class: lead -->

# PART 1: The Problem

## "Why we needed this"

<!--
Let's start with the pain points. I bet many of you will recognize these scenarios.
-->

---

# Typical Incident Response at 3am

**The all-too-familiar workflow:**

- 📱 PagerDuty alert wakes you up
- 💻 Open laptop, VPN in, context-switch from sleep
- 🔍 Manually check: pod logs, events, deployments, recent PRs
- 🔗 Cross-reference: Jira tickets, GitHub commits, AWS resources
- ⏱️ **30-60 minutes** just to understand what broke
- 🧠 Context-switching kills productivity
- 😴 Can't fall back asleep

<!--
Ask the audience: "How many of you have been through this?"
Show of hands - this usually resonates strongly.

Key point: The investigation is repetitive, manual, and time-consuming.
-->

---

# The Overhead: Tool Sprawl

**Multiple disconnected tools:**

| Tool | What You Do |
|------|------------|
| `kubectl` | Check pods, logs, events |
| GitHub | Search for recent PRs, config changes |
| Jira | Create ticket, check history |
| AWS Console | EC2 instances, load balancers |
| Datadog | Metrics, APM traces |

**Result:** Constant copy-pasting between systems

<!--
Each tool requires:
- Different authentication
- Different query language
- Different mental model
- Manual correlation of data

This is exhausting at 3am (or 3pm for that matter).
-->

---

# Manual Copy-Paste Hell

```bash
# Step 1: Get pod logs
kubectl logs proteus-api-xyz -n proteus-dev --tail=100
# → Copy output

# Step 2: Paste into Jira ticket
# → Switch to browser, open Jira, paste

# Step 3: Check recent deployments
kubectl get deployments -n proteus-dev
# → Copy deployment name

# Step 4: Search GitHub for related PRs
# → Switch to browser, search GitHub, correlate manually

# Step 5: Check AWS resources
# → Switch to AWS Console, find instances, correlate
```

**Every. Single. Incident.**

<!--
This is soul-crushing repetitive work.
And you're doing it manually because you don't have time to automate it.
Or previous attempts at automation were too brittle.
-->

---

# The Same Questions, Every Time

**Debugging patterns repeated over and over:**

- "Which pods are failing?"
- "What changed recently?"
- "Is this related to that deployment 2 hours ago?"
- "Has this happened before?"
- "What's the impact radius?"
- "Who was the last person to touch this?"

**Knowledge locked in senior engineers' heads:**

- Junior engineers don't know where to start
- Tribal knowledge not documented
- Inconsistent investigation quality

<!--
Senior engineers have mental playbooks.
Junior engineers are lost.
This knowledge should be codified and accessible to everyone.
-->

---

<!-- _class: lead -->

# The Big Question

> **"What if an AI could do the initial triage in 60 seconds?"**

<!--
This is the hypothesis we tested.
Could we reduce 30-60 minutes to 60 seconds?
Could we make junior engineers as effective as seniors?
Could we reduce after-hours pages?

Spoiler: Yes. Let me show you how.
-->

---

<!-- _class: lead -->

# PART 2: The Solution

## "Two ways to use Claude for automation"

<!--
We built two different implementations of the same use case.
Not because one is better, but because they solve different problems.
-->

---

# Approach 1: Autonomous Agent

## "AI teammate that watches your cluster 24/7"

**What it does:**

- ✅ Runs continuously in Kubernetes as a pod
- ✅ Proactively monitors cluster health every 15 minutes
- ✅ Creates Jira tickets automatically with full context
- ✅ Sends Teams notifications with root cause analysis
- ✅ Can perform **safe auto-remediation** (with approval gates)

**Think of it as:** Your AI SRE colleague

<!--
This is the "set it and forget it" approach.
The AI runs autonomously, looking for issues.
When it finds something, it investigates and reports back.
Sometimes it can even fix the issue (with safety guardrails).
-->

---

# When to Use Autonomous Agent

**✅ Choose this approach when you need:**

- Continuous monitoring (not event-driven)
- Proactive issue detection before users notice
- Auto-documentation in Jira
- Reduce alert noise with intelligent filtering
- Safe auto-remediation (restart pods, scale deployments)

**🔑 Key technology:**

- **Claude Agent SDK** - Persistent memory across runs
- **MCP servers** - Structured access to K8s, GitHub, Jira
- **Multi-agent coordination** - 6 specialized subagents

<!--
This is great for:
- Teams drowning in alerts
- Clusters with frequent transient issues
- Teams that want comprehensive monitoring

Not great for:
- One-off investigations
- External integrations (Slack bots, n8n)
-->

---

# Approach 2: On-Demand API

## "AI assistant you ask questions when something breaks"

**What it does:**

- ✅ HTTP API you can call from anywhere
- ✅ Slack bot integration for interactive troubleshooting
- ✅ n8n workflow automation
- ✅ Simple `curl` commands for ad-hoc queries
- ✅ Session-based conversations (ask follow-up questions)

**Think of it as:** ChatGPT but connected to your infrastructure

<!--
This is the "interactive troubleshooting" approach.
You ask it questions, it investigates and responds.
Great for integrating with existing workflows.
-->

---

# When to Use On-Demand API

**✅ Choose this approach when you need:**

- On-demand incident investigation
- Slack bot for team self-service
- Integration with existing tools (PagerDuty, ServiceNow)
- Quick prototyping and experimentation
- HTTP API wrapper around Claude

**🔑 Key technology:**

- **Anthropic API** - Direct, lightweight
- **FastAPI** - Standard HTTP REST interface
- **Direct Python libraries** - kubernetes, PyGithub, boto3
- **No external runtime dependencies**

<!--
This is great for:
- Slack bot use cases
- n8n automation workflows
- Teams that want "AI assistant on demand"

Not great for:
- Proactive monitoring
- Complex multi-step workflows
-->

---

# The Key Insight

<!-- _class: lead -->

> **Same AI brain, different deployment patterns for different needs**

<!--
These aren't competing approaches.
They're complementary.
You can run both simultaneously!
-->

---

# Use Case Decision Matrix

| Scenario | Recommended Approach |
|----------|---------------------|
| "Watch my cluster and tell me when something's wrong" | **Autonomous Agent** |
| "I have a Slack alert, help me investigate" | **On-Demand API** |
| "Auto-create Jira tickets with context" | **Autonomous Agent** |
| "Let engineers ask questions via Slack bot" | **On-Demand API** |
| "Perform safe auto-remediation" | **Autonomous Agent** |
| "Integrate with n8n workflows" | **On-Demand API** |

**💡 Pro tip:** Run both! They complement each other.

<!--
Autonomous agent for continuous monitoring.
On-demand API for interactive troubleshooting.
Both monitoring the same cluster, different mechanisms.
-->

---

<!-- _class: lead -->

# PART 3: Live Demos

## "Show, don't tell"

<!--
This is where it gets interesting.
I'm going to show you both approaches in action.

Demo 1: Autonomous monitoring (5 min)
Demo 2: Interactive API (5 min)
Demo 3: MCP magic (5 min)
-->

---

# Demo 1: Autonomous Monitoring

## EKS Agent in Action

**Scenario:** The EKS agent detected an issue during its scheduled monitoring cycle

**What we'll see:**
1. Agent running logs
2. Monitoring report with root cause analysis
3. Safety hooks validating operations
4. GitHub issue created automatically
5. Teams notification sent

<!--
This demo shows the agent working autonomously.
No human interaction required.
It finds the issue, diagnoses it, creates tickets, and (optionally) fixes it.

Have the demo prepared:
- Terminal showing docker compose logs
- Browser with GitHub issue
- Teams channel with notification
-->

---

# Demo 1: Step 1 - Agent Running

```bash
# Check the agent is running
docker compose logs eks-monitoring-daemon --tail=50
```

**Output shows:**

```log
[2025-10-21 10:15:00] Starting monitoring cycle #47
[2025-10-21 10:15:02] Invoking k8s-diagnostics subagent
[2025-10-21 10:15:35] Found 3 issues across 2 namespaces
[2025-10-21 10:15:36] Invoking k8s-log-analyzer subagent
[2025-10-21 10:16:12] Root cause: OOMKilled in proteus-dev
[2025-10-21 10:16:15] Creating GitHub issue #453
[2025-10-21 10:16:18] Posting Teams notification
[2025-10-21 10:16:20] Cycle complete - 80 seconds
```

<!--
Point out:
- Autonomous operation (no human trigger)
- Multiple subagents invoked (diagnostics → log analyzer)
- Fast cycle time (80 seconds for full cluster scan)
- Creates GitHub issue automatically
-->

---

# Demo 1: Step 2 - What It Discovered

```bash
cat /tmp/eks-monitoring-reports/2025-10-21-10-15-00.json
```

**Key findings:**

- **Issue:** CrashLoopBackOff in `proteus-dev` namespace
- **Root Cause:** OOMKilled - container exceeded 512Mi limit
- **Correlation:** PR #452 merged 30 minutes ago (added caching layer)
- **Recommendations:** Increase memory to 1Gi, check for memory leaks
- **Auto-remediation:** Restarted deployment (safe: 3 replicas)
- **Tickets created:** GitHub issue #453, Jira OPS-1234

<!--
Highlight the correlation:
- AI connected the dots between pod crash and recent PR
- This is what would take a human 20-30 minutes
- AI did it in 80 seconds

Show the actual GitHub issue created - full context, links, recommendations
-->

---

# Demo 1: Step 3 - Safety Hooks

```bash
tail -20 /tmp/claude-k8s-agent-actions.log
```

**Safety validation in action:**

```log
[10:15:40] TOOL_CALL: mcp__kubernetes__pods_restart
           Namespace: proteus-dev, Deployment: proteus-api

[10:15:40] SAFETY_VALIDATOR: EVALUATING
           ✓ Namespace protected? NO (proteus-dev is dev namespace)
           ✓ Has 2+ replicas? YES (3 replicas)
           ✓ Dangerous operation? NO (rolling restart is safe)
           DECISION: ALLOW

[10:15:41] ACTION_LOGGER: LOGGED
[10:15:42] TEAMS_NOTIFIER: SENT to #devops-alerts
```

<!--
This is critical for production use.
Before executing ANY operation, it goes through validation:
1. Safety validator checks rules
2. Action logger creates audit trail
3. Teams notifier alerts team in real-time

Humans stay in the loop.
-->

---

# Demo 2: Interactive API

## OnCall Agent via HTTP

**Scenario:** You get a Slack alert and want to investigate

**What we'll see:**
1. Swagger UI (interactive API docs)
2. Simple query → comprehensive analysis
3. Session-based follow-up questions
4. Multi-turn conversation with context

<!--
This demo shows the on-demand approach.
You ask questions, AI investigates.
Great for Slack bots or n8n workflows.

Have Swagger UI open at http://localhost:8000/docs
-->

---

# Demo 2: Query via Swagger UI

**Open:** http://localhost:8000/docs

**Try `POST /query` endpoint:**

```json
{
  "message": "What's wrong with proteus-dev namespace right now?"
}
```

**Response (in ~15 seconds):**

```json
{
  "response": "I found 3 pods in CrashLoopBackOff state...\n\n
              Root Cause: All pods are being OOMKilled...\n\n
              Recent Changes: PR #452 merged 30 minutes ago...\n\n
              Recommendations:\n
              1. Increase memory limit to 1Gi\n
              2. Review caching implementation...",
  "metadata": {
    "query_time": "14.2s",
    "tokens_used": 8234,
    "tools_called": ["list_pods", "get_pod_logs", "search_github_prs"]
  }
}
```

<!--
Point out:
- Natural language query
- Comprehensive analysis in 15 seconds
- Automatic tool selection (pods, logs, GitHub)
- Metadata shows what it did behind the scenes
-->

---

# Demo 2: Follow-Up Questions

**Create a session for multi-turn conversation:**

```json
POST /session
{
  "initial_message": "What's wrong with proteus-dev?"
}

→ Returns session_id: "sess_abc123"
```

**Ask follow-up questions:**

```json
POST /query
{
  "message": "What was the last deployment to this namespace?",
  "session_id": "sess_abc123"
}
```

**Claude remembers context:**
> "The last deployment was 35 minutes ago (proteus-api v2.14.5) from PR #452, which introduced the caching layer I mentioned earlier causing the OOM issues."

<!--
This is powerful for troubleshooting.
You can have a conversation, ask follow-ups.
Claude maintains context across queries.
-->

---

# Demo 3: MCP Magic

## "What makes this different from ChatGPT?"

**The secret sauce:** Model Context Protocol (MCP)

<!--
This is the "aha moment" for most people.
MCP is what makes this actually useful vs just ChatGPT.
-->

---

# Without MCP (Manual Approach)

**What you'd type manually:**

```bash
kubectl get pods -n proteus-dev
kubectl describe pod proteus-api-xyz -n proteus-dev
kubectl logs proteus-api-xyz --tail=100
gh pr list --repo artemishealth/proteus --state merged
# ... copy-paste results
# ... manually correlate
# ... write up findings
```

**Time:** 10-15 minutes of manual work

<!--
This is brittle, error-prone, and boring.
And you have to remember all the command syntax.
-->

---

# With MCP (AI Approach)

**What you tell Claude:**

```
"Check proteus-dev health and correlate with recent deployments"
```

**What Claude does automatically:**

```python
# 1. List pods (structured data, not string parsing)
pods = mcp__kubernetes__pods_list(namespace="proteus-dev")

# 2. Check events for issues
events = mcp__kubernetes__events_list(namespace="proteus-dev")

# 3. Get pod logs for failing pods
logs = mcp__kubernetes__pods_logs(pod_name="proteus-api-xyz")

# 4. Search GitHub for recent activity
prs = mcp__github__list_pull_requests(repo="artemishealth/proteus")

# 5. Correlate all data and explain root cause
```

**Time:** 15 seconds

<!--
MCP gives Claude structured access to tools.
No string parsing. No brittle scripts.
Type-safe, consistent, reliable.
-->

---

# MCP: Structured Tool Access

```yaml
# MCP Server Configuration (eks/.claude/settings.json)
mcpServers:
  kubernetes:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-kubernetes"]
    env:
      KUBECONFIG: /root/.kube/config

  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_PAT}
```

**Result:** Claude has direct, structured access to K8s and GitHub

<!--
MCP servers are external processes that expose tools.
Each tool has a schema (input/output types).
Claude can discover and call these tools.

This is NOT screen scraping or string parsing.
This is structured API access.
-->

---

# The Power of Structured Access

**Without MCP (brittle):**

```python
# String parsing, version-dependent, error-prone
output = subprocess.run(["kubectl", "get", "pods"])
lines = output.split("\n")
# Parse columns, handle edge cases...
```

**With MCP (structured):**

```python
# Type-safe, version-independent, reliable
pods = mcp__kubernetes__pods_list(namespace="proteus-dev")
for pod in pods:
    print(f"{pod.name}: {pod.status} ({pod.restart_count} restarts)")
```

**Benefits:** Consistent, discoverable, maintainable

<!--
This is the key architectural insight.
MCP makes AI agents RELIABLE for production use.
Not just clever demos.
-->

---

<!-- _class: lead -->

# PART 4: How It Works

## "The moving parts - demystified"

<!--
Let's dive into the architecture.
Don't worry, we'll keep it practical.
-->

---

# Decision Tree: SDK vs API

```
┌─────────────────────────────────────────────┐
│ Need automation that runs on its own?      │
│ (Scheduled monitoring, proactive alerts)   │
└──────────────┬──────────────────────────────┘
               │ YES → Claude Agent SDK
               │       (EKS approach)
               │
               │ Features:
               │ ✓ Persistent memory
               │ ✓ Multi-agent coordination
               │ ✓ Safety hooks
               │ ✓ MCP integration built-in
               └────────────────────────────────

┌─────────────────────────────────────────────┐
│ Need an API to integrate with tools?       │
│ (Slack bot, n8n workflows, curl commands)  │
└──────────────┬──────────────────────────────┘
               │ YES → Anthropic API
               │       (OnCall approach)
               │
               │ Features:
               │ ✓ Lightweight HTTP wrapper
               │ ✓ Stateless (or session-based)
               │ ✓ Easy integration (REST API)
               │ ✓ Fast startup, minimal deps
               └────────────────────────────────
```

<!--
Simple rule of thumb:
- Runs on its own? → SDK
- Called from elsewhere? → API
-->

---

# Model Context Protocol (MCP)

## Why MCP Matters

**The Problem MCP Solves:**

Traditional approach:
- Execute commands → Parse string output → Hope format doesn't change
- Brittle, version-dependent, error-prone

MCP approach:
- Call structured tools → Get typed responses → Always consistent
- Reliable, version-independent, discoverable

<!--
MCP is to AI agents what REST APIs are to web services.
Structured, discoverable, composable.
-->

---

# MCP Architecture

```
┌─────────────────────────────────────┐
│      Claude Agent                   │
│  (Decides which tools to call)     │
└──────────┬──────────────────────────┘
           │
           │ "I need to check pod health"
           │
           ▼
┌─────────────────────────────────────┐
│     MCP Protocol Layer              │
│  (JSON-RPC communication)          │
└──────────┬──────────────────────────┘
           │
    ┌──────┼──────┬──────┬──────┐
    │      │      │      │      │
    ▼      ▼      ▼      ▼      ▼
┌────┐  ┌────┐ ┌────┐ ┌────┐ ┌────┐
│K8s │  │Git │ │Jira│ │AWS │ │...│
│MCP │  │Hub │ │MCP │ │MCP │ │   │
└────┘  └────┘ └────┘ └────┘ └────┘
```

<!--
Each MCP server:
- Runs as separate process
- Exposes specific tools
- Handles auth and errors
- Translates between Claude and underlying APIs
-->

---

# Available MCP Servers

**Official Anthropic MCP Servers:**

- `@modelcontextprotocol/server-kubernetes` - K8s cluster ops
- `@modelcontextprotocol/server-github` - GitHub repo management
- `@modelcontextprotocol/server-gitlab` - GitLab integration
- `@modelcontextprotocol/server-slack` - Slack messaging
- `@modelcontextprotocol/server-postgres` - Database queries

**Third-party:**

- Atlassian (Jira/Confluence)
- AWS, Datadog, PagerDuty
- Your internal tools!

**Build your own:** MCP protocol is open source

<!--
MCP ecosystem is growing rapidly.
You can build custom MCP servers for internal tools.
This makes AI agents infinitely extensible.
-->

---

# Safety Hooks

## "How we prevent AI from breaking production"

**The Hook Chain:**

```
Claude wants to restart a pod
         ↓
1. Safety Validator
   ❓ Is namespace protected?
   ❓ Has 2+ replicas?
   ❓ Is operation approved?
   → ALLOW or DENY
         ↓
2. Action Logger
   → Audit trail
         ↓
3. Teams Notifier
   → Real-time alert
         ↓
   Execute (if allowed)
```

<!--
This is how we sleep at night.
AI makes decisions, but humans set the rules.
Every operation is validated before execution.
-->

---

# Safety Validator Rules

**Protected Namespaces (NEVER allow destructive ops):**

- `kube-system`, `kube-public` - Core K8s
- `production`, `prod` - Production environments
- `artemis-prod`, `preprod` - Business-critical

**Dangerous Command Patterns (ALWAYS block):**

- `kubectl delete namespace`
- `kubectl delete pv`
- `--all-namespaces` (bulk operations)
- `rm -rf /`

**Approved Auto-Remediation (dev/staging only):**

- ✅ Rolling restart deployments with 2+ replicas
- ✅ Delete Failed/Evicted pods
- ✅ Scale deployments by ±2 replicas

<!--
These rules are defined in code.
You customize them for your environment.
Start conservative, gradually relax as you gain confidence.
-->

---

# Multi-Agent Coordination

## EKS Agent: Specialized Subagents

```
Main Orchestrator
    ↓
1. k8s-diagnostics → Fast health checks
    ↓
2. k8s-log-analyzer → Root cause from logs
    ↓
3. k8s-github → Deployment correlation
    ↓
4. k8s-remediation → Safe cluster fixes
    ↓
5. k8s-jira → Ticket management
```

**Each subagent:**

- Optimized for specific task
- Isolated context (can't see other subagents)
- Can use different models (Haiku for simple, Sonnet for complex)

<!--
This is like having a team of specialists.
Orchestrator delegates to experts.
More efficient than one generalist agent.
-->

---

<!-- _class: lead -->

# PART 5: Real-World Impact

## "What we've learned running this in production"

<!--
Let's talk numbers.
These are real metrics from running the EKS agent on dev-eks cluster.
40 nodes, 20+ namespaces, 200+ pods.
-->

---

# Before AI Automation

**Incident Triage:**

- ⏱️ Time to diagnosis: **30-60 minutes**
- 🔨 Manual kubectl commands: **~20 per incident**
- 🔀 Tools switched between: **5+**
- 🧠 Knowledge requirements: **Senior engineers only**
- 🌙 After-hours impact: **High** (wake up, investigate, can't sleep)
- 📝 Documentation quality: **Inconsistent**

**Example timeline:**

```
00:15 - Alert
00:17 - Engineer wakes up
00:45 - Understands issue
01:00 - Decides on fix
01:05 - Executes fix
────────────────
Total: 50 minutes
```

<!--
Ask audience: "How many all-nighters have you had because of this?"
This is the status quo for many teams.
-->

---

# After AI Automation

**Incident Triage:**

- ⏱️ Time to diagnosis: **60-90 seconds**
- 🤖 Automated correlation: **Pod logs + GitHub PRs + AWS + Jira**
- 🔀 Tools required: **None** (AI does it all)
- 🧠 Knowledge requirements: **Junior engineers can troubleshoot**
- 🌙 After-hours impact: **Low** (AI handles initial triage)
- 📝 Documentation quality: **Consistent, comprehensive**

**Example timeline:**

```
00:15 - Pod crashes
00:16 - AI detects in monitoring cycle
00:17 - AI diagnoses root cause
00:18 - AI creates GitHub issue
00:19 - AI creates Jira ticket
00:20 - AI validates safety (3 replicas)
00:21 - AI executes rolling restart
00:22 - Teams notification: "Resolved"
────────────────
Total: 90 seconds, zero human intervention
```

<!--
This is not a demo. This happens every day.
97% reduction in time.
100% reduction in pages for auto-resolved issues.
-->

---

# Quantified Benefits

**Time Savings:**

- Per-incident triage: 30-60 min → 60-90 sec = **~97% reduction**
- Documentation: Manual notes → Auto-generated = **~15 min saved**

**Quality Improvements:**

- Root cause accuracy: ~60% → ~90%
- Correlation of changes: Manual (often missed) → Automatic (always checked)

**Team Impact:**

- After-hours pages: **↓ 40%** (auto-resolution of common issues)
- Junior engineer effectiveness: **↑ 300%** (AI guidance)
- Alert fatigue: **↓ 75%** (smart filtering)

<!--
These numbers are conservative.
The intangible benefits (sleep, morale, learning) are huge.
-->

---

# Cost-Benefit Analysis

**Monthly costs for dev-eks cluster:**

- **AI monitoring:** ~$45/month
  - 1.5M tokens/day @ Claude Sonnet pricing
  - Optimized with smart caching

**Saved costs:**

- **Engineering time:** ~20 hours/month = **$4,000/month**
  - @ $200/hr blended rate
- **Prevented downtime:** ~2 hours/month = **$10,000/month**
  - Estimated business impact

**ROI: ~300x**

<!--
Even if you only count engineering time, ROI is massive.
If you count prevented downtime, it's a no-brainer.

Plus intangible benefits:
- Reduced burnout
- Faster onboarding
- Better sleep
-->

---

# Unexpected Benefits

**1. Documentation by Default**

Every incident gets full context:

- Timeline of events
- Code changes that caused it
- Root cause analysis
- Remediation steps taken
- Links to all related resources

**Result:** Better postmortems, easier pattern recognition

<!--
This is huge for compliance and learning.
Every incident is automatically documented.
No more "we forgot to write the postmortem."
-->

---

# More Unexpected Benefits

**2. Pattern Recognition at Scale**

AI spots recurring issues:

- "This is the 4th OOM in proteus-api this week"
- "Memory issues always follow deployments from feature-xyz branch"
- "This service restarts every Tuesday at 2am for 3 weeks"

**Result:** Proactive fixes instead of reactive firefighting

**3. Knowledge Democratization**

Junior engineers get AI explanations:

> "This pod is in CrashLoopBackOff because it's being OOMKilled. Here's what that means... The fix: increase memory limit at k8s/deployment.yaml line 45."

**Result:** Learning opportunity, not just fire drill

<!--
These benefits surprised us.
We built it for time savings.
We got a teaching tool and pattern detector for free.
-->

---

# Challenges We Solved

**Challenge 1: MCP Kubernetes Server Bug**

- MCP server doesn't filter by namespace properly
- Returns ALL 300+ pods → exceeds 25K token limit
- **Solution:** Fallback to kubectl via Bash tool

**Challenge 2: Token Costs**

- Initial: 15K tokens/cycle = $5/day
- **Solution:** Smart caching, conditional subagents, summarization
- **Result:** 8K tokens/cycle = $1.50/day

**Challenge 3: False Positives**

- AI over-reacting to normal operations
- **Solution:** Time-based thresholds, replica count validation
- **Result:** 70% reduction in false positives

<!--
These are real problems we encountered.
Not everything works perfectly out of the box.
But they're all solvable.
-->

---

<!-- _class: lead -->

# PART 6: Getting Started

## "How you could adopt this"

<!--
Let's talk about your path to adoption.
Start small, prove value, expand.
-->

---

# Quick Wins (Week 1-2)

## Try the OnCall API Locally

**Time investment:** 30 minutes

```bash
# Clone repo
git clone <repo-url>
cd claude-agents/oncall

# Set up
cp .env.example .env
# Add ANTHROPIC_API_KEY

# Start API
docker compose up oncall-agent-api

# Test it
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"message": "What pods are running in kube-system?"}'
```

**What you get:** Working AI agent answering K8s questions, zero risk

<!--
This is the fastest way to get hands-on experience.
30 minutes from clone to working AI agent.
No production deployment needed.
-->

---

# Medium Investment (Month 1)

## Deploy to Dev Cluster

**Time investment:** 1-2 hours

```bash
cd eks

# Configure
cp .env.example .env
# Add ANTHROPIC_API_KEY, GITHUB_PAT

# IMPORTANT: Disable auto-remediation for testing
AUTO_REMEDIATION_ENABLED=false

# Edit cluster context
nano .claude/CLAUDE.md
# Update cluster name, namespaces, team contacts

# Deploy to K8s
kubectl apply -f k8s-monitor/k8s/

# Watch it run
kubectl logs -f deployment/k8s-monitor -n monitoring
```

**What you get:** AI monitoring your dev cluster, creating tickets, zero auto-fix

<!--
This is the "test drive" phase.
Let it run for a week.
See what it finds.
Tune the configuration.
Decide if you want to enable auto-remediation.
-->

---

# Customization Ideas

**1. Add Your Own MCP Servers**

Example: PagerDuty integration

```json
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

Now Claude can create PagerDuty incidents, correlate with on-call schedules

<!--
MCP is infinitely extensible.
Build MCP servers for your internal tools.
Slack, ServiceNow, your ticketing system, etc.
-->

---

# More Customization Ideas

**2. Create Specialized Subagents**

Example: Database health checker

```markdown
---
name: db-health-checker
description: PostgreSQL health monitoring
tools: mcp__kubernetes__pods_exec, Bash
model: claude-sonnet-4-20250514
---

Monitor PostgreSQL database health:
- Check connection count
- Monitor replication lag
- Identify slow queries
- Recommend index optimizations
```

**3. Extend the OnCall API**

Add Slack slash command:

```python
@app.post("/slack/commands/ask-claude")
async def slack_command(request):
    question = request.form.get("text")
    response = await agent.query(question)
    return {"text": response}
```

<!--
The architecture is designed for extensibility.
These are just examples - build what your team needs.
-->

---

# Cost Estimation

**Scenario 1: OnCall API (On-Demand)**

```
Assumptions:
- 10 queries/day
- 8K tokens per query
- 30 days/month

Cost: ~$18/month
```

**Scenario 2: EKS Agent (Continuous)**

```
Assumptions:
- 4 cycles/hour (15 min intervals)
- 15K tokens per cycle
- 24 hours/day, 30 days/month

Cost: ~$302/month (unoptimized)
Cost: ~$45-90/month (optimized)
```

**Optimization strategies:** Use Haiku for simple tasks, smart caching, conditional subagents

<!--
Cost is very manageable.
Even unoptimized, ROI is positive.
With optimization, it's a no-brainer.
-->

---

# Success Metrics

**How to measure if this is working:**

**Quantitative:**

- Mean Time to Detection (MTTD) - How fast are issues found?
- Mean Time to Resolution (MTTR) - How fast are they fixed?
- False Positive Rate - What % of alerts are noise?
- Auto-Resolution Rate - What % fixed without human intervention?

**Qualitative:**

- Engineer satisfaction - Less stressful on-call?
- Documentation quality - Are postmortems better?
- Knowledge sharing - Can juniors handle more?
- Alert fatigue - Reduced or increased?

<!--
Define success criteria upfront.
Track metrics.
Iterate based on data.
-->

---

<!-- _class: lead -->

# PART 7: Q&A and Discussion

## "Let's talk about your use cases"

<!--
Now it's your turn.
What problems are you trying to solve?
How might this help?
-->

---

# Discussion Questions

**Pain Point Discovery:**

- What's your biggest incident triage pain point?
- How long does it typically take to diagnose a production issue?
- What percentage of your alerts are false positives?

**Integration Opportunities:**

- What tools would you want AI to integrate with?
- What would be your ideal Slack integration?
- What data sources would be most valuable?

**Safety and Governance:**

- What safeguards would you need for production use?
- How would you handle sensitive data?
- What level of autonomy are you comfortable with?

<!--
Listen more than talk.
Understand their specific pain points.
Tailor the solution to their needs.
-->

---

# Potential Follow-Up Projects

**Option 1: Just Learn** (2-4 hours)

- Fork repo, run locally
- Experiment and share findings
- No production commitment

**Option 2: Build Something Cool** (1-2 weeks)

- Custom MCP server or subagent
- Slack bot or n8n integration
- Demo to team

**Option 3: Lighten the Load** (1 month)

- Deploy to dev cluster
- Measure MTTR improvement
- Gradually enable auto-remediation

**Option 4: Make It a Feature** (3+ months)

- Build internal platform
- Multi-tenancy support
- Self-service for teams

<!--
Meet them where they are.
Not everyone needs to go to production immediately.
Start with learning, build momentum.
-->

---

# Common Concerns

**"What if the AI makes a mistake?"**

- Safety hooks prevent dangerous operations
- All actions logged for audit
- Start read-only, gradually enable auto-remediation
- Real-time notifications keep team aware
- **In 3 months: zero incidents caused by AI, 40+ incidents resolved**

**"How do we handle sensitive data in logs?"**

- MCP servers can redact PII
- Hook scripts filter sensitive data
- Claude's content filtering features
- Self-hosted models for highly sensitive environments

<!--
These concerns are valid.
Address them head-on with concrete solutions.
Safety is paramount.
-->

---

# More Common Concerns

**"What about vendor lock-in with Anthropic?"**

- MCP protocol is open source, model-agnostic
- Can swap Claude for OpenAI, Gemini, self-hosted
- All infrastructure is containerized and portable
- Just change one environment variable to switch models

**"How does this compare to ChatGPT?"**

- **Structured tool access** via MCP (not copy-pasting)
- **Persistent memory** across conversations
- **Safety hooks** for production use
- **Automation** without human prompts
- **Integration** with your infrastructure

**ChatGPT is great for questions. This is great for automation.**

<!--
Vendor lock-in is minimal.
MCP makes this portable.
This is fundamentally different from ChatGPT.
-->

---

<!-- _class: lead -->

# Resources

## Where to learn more

---

# Documentation and Code

**This Repository:**

- GitHub: `<your-repo-url>`
- Full docs: `/CLAUDE.md`
- Examples: `/eks/` and `/oncall/`

**Claude and MCP:**

- Claude Agent SDK: https://docs.claude.com/en/api/agent-sdk
- Anthropic API: https://docs.anthropic.com/
- MCP Protocol: https://modelcontextprotocol.io/

**MCP Servers:**

- Official servers: `@modelcontextprotocol/server-*`
- Build your own: https://modelcontextprotocol.io/docs/tutorials/

<!--
All the code is open source.
Documentation is comprehensive.
Community is growing.
-->

---

# Getting Help

**Anthropic Community:**

- Discord: https://discord.gg/anthropic
- Forum: https://community.anthropic.com/

**Internal Resources:**

- Slack: `#ai-incident-response` (create this!)
- Office hours: [Your availability]
- Wiki: [Your internal docs]

**This Presentation:**

- Slides: [Link to this presentation]
- Demo recordings: [Link to recordings]
- Follow-up Q&A: [Schedule a meeting]

<!--
Create internal channels for collaboration.
Set up office hours for questions.
Build a community of practice.
-->

---

<!-- _class: lead -->

# Next Steps

---

# Individual Next Steps

**Today:**

- Clone the repo
- Try the OnCall API locally

**This Week:**

- Run a test query against your dev cluster
- Share with your team

**This Month:**

- Identify one pain point this could solve
- Deploy to dev cluster for testing

<!--
Start small.
Prove value.
Build momentum.
-->

---

# Team Next Steps

**This Week:**

- Discuss as a team - is this interesting?

**Next Week:**

- Identify a pilot project (small scope)

**This Month:**

- Deploy to dev cluster, gather metrics

**Next Month:**

- Evaluate results, decide on broader adoption

<!--
Make it a team decision.
Get buy-in.
Measure results.
-->

---

# Organization Next Steps

**Short-term:**

- Create internal Slack channel for collaboration

**Medium-term:**

- Establish AI automation standards and best practices

**Long-term:**

- Build internal platform for AI-powered operations

<!--
Think bigger.
This isn't just a tool, it's a new way of working.
Build the culture and practices to support it.
-->

---

<!-- _class: lead -->
<!-- _paginate: false -->

# Thank You!

**Questions? Ideas? Want to collaborate?**

**Contact:**

- Presenter: Ari Sela
- Email: [your-email]
- Slack: @arisela
- Office hours: [your-availability]

**Let's build something cool together!**

<!--
End on a high note.
Invite collaboration.
Make yourself available for follow-up.

Remember: The goal is to spark interest and start conversations.
Not everyone will adopt immediately, and that's okay.
Plant the seed, provide the path, let them move at their pace.
-->
