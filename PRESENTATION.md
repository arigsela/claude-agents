---
marp: true
theme: default
class: invert
paginate: true
backgroundColor: #1a1a1a
color: #ffffff
style: |
  section {
    font-family: 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
    padding: 25px 35px;
  }
  h1 {
    color: #00d4ff;
    font-size: 1.6em;
    text-shadow: 0 0 20px rgba(0, 212, 255, 0.3);
    margin-bottom: 8px;
  }
  h2 {
    color: #00d4ff;
    font-size: 1.2em;
    border-bottom: 2px solid #00d4ff;
    padding-bottom: 5px;
    margin-bottom: 8px;
  }
  h3 {
    color: #4fd0ff;
    font-size: 0.9em;
    margin-bottom: 4px;
  }
  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }
  .column {
    padding: 15px;
  }
  .highlight {
    background: rgba(0, 212, 255, 0.1);
    padding: 6px;
    border-left: 3px solid #00d4ff;
    border-radius: 3px;
    font-size: 0.7em;
    line-height: 1.2;
    margin: 3px 0;
  }
  .stat {
    font-size: 1.1em;
    color: #00ff88;
    font-weight: bold;
  }
  .metric {
    background: rgba(0, 255, 136, 0.1);
    padding: 5px;
    border-radius: 3px;
    margin: 2px 0;
    border-left: 2px solid #00ff88;
    font-size: 0.7em;
    line-height: 1.2;
  }
  .comparison-table {
    width: 100%;
    margin: 8px 0;
    font-size: 0.7em;
    border-collapse: collapse;
  }
  .comparison-table th {
    background: rgba(0, 212, 255, 0.2);
    color: #00d4ff;
    padding: 5px;
    text-align: left;
    border-bottom: 2px solid #00d4ff;
  }
  .comparison-table td {
    padding: 5px;
    border-bottom: 1px solid rgba(0, 212, 255, 0.1);
  }
  .api {
    background: rgba(255, 100, 100, 0.1);
    border-left: 4px solid #ff6464;
  }
  .sdk {
    background: rgba(100, 255, 100, 0.1);
    border-left: 4px solid #64ff64;
  }
  .footer {
    font-size: 0.8em;
    color: #888;
  }
  ul {
    font-size: 0.7em;
    line-height: 1.2;
    margin: 2px 0;
  }
  li {
    margin-bottom: 2px;
  }
  code {
    background: rgba(0, 0, 0, 0.5);
    color: #00ff88;
    padding: 2px 4px;
    border-radius: 2px;
    font-family: 'Courier New', monospace;
    font-size: 0.68em;
  }
  p {
    margin: 3px 0;
    font-size: 0.7em;
    line-height: 1.2;
  }
---

<!-- Title Slide -->

# AI for Kubernetes Incident Triage

## Two Approaches. One Goal. Zero Pressure.

### A Learning Lab in AI/MCP Integration Patterns

---

# PART 1: The Problem

## Typical Incident Response at 3am

**PagerDuty alert. Service X is down.**

1. Open 7 browser tabs
2. Find the right logs (wrong namespace? wrong time window?)
3. Check what deployed
4. Assess impact
5. Attempt fix
6. Document in Jira

**Total: 30-45 minutes**
**Stress level**: 📈📈📈
**Sleep quality**: 😴→🚀

---

# PART 1: The Problem (Continued)

## The Overhead: Tool Sprawl

**Seven different tools. Seven context switches. Zero integration.**

- 📊 **Datadog** - Which metric?
- 📋 **Splunk** - Wrong time window
- 🚀 **GitHub** - What deployed?
- ☸️ **Kubernetes** - Which namespace?
- ☁️ **AWS** - Click click click
- 🎫 **Jira** - Write it all down
- 💬 **Slack** - Is anyone else on it?

---

# PART 1: The Problem (Continued)

## The Same Questions, Every Time

Every single incident, you ask these:

- ✓ **"Is this a real problem?"** - Or a flaky monitor?
- ✓ **"What actually changed?"** - Deployment? Configuration? External?
- ✓ **"What logs are relevant?"** - Which service? Which namespace? Which time window?
- ✓ **"Who depends on this?"** - Cascade risk assessment?
- ✓ **"Is this new or recurring?"** - Pattern detection?
- ✓ **"What's the fastest fix?"** - Restart? Scale? Rollback?
- ✓ **"How do I document this?"** - For the post-mortem?

And you repeat this **every single time**, even if:
- Same service as last month
- Same error as last week
- Same root cause as three days ago

---

# PART 1: The Problem (Continued)

## The Big Question

**What if an AI could do this in 60 seconds?**

One query → Instant analysis → Actionable output

**Instead of 30-45 minutes → 60 seconds**

---

# Meet the Solutions

## Two Complementary Approaches

<div class="columns">
<div class="column">

## 📥 oncall-agent
Interactive Troubleshooting
"Ask the AI when something breaks"

- **Framework**: Anthropic API
- **Pattern**: HTTP API
- **Entry Point**: Ask → Get answers
- **Live**: Slack bot

</div>
<div class="column">

## 🤖 k8s-monitor
Autonomous Monitoring
"AI watches automatically"

- **Framework**: Claude Agent SDK
- **Pattern**: Persistent memory
- **Entry Point**: Every 15 minutes
- **Status**: 208 passing tests

</div>
</div>

---

# Approach 1: oncall-agent

## Interactive AI Troubleshooting with Anthropic API

### How It Works

💬 **You ask** → 🧠 **Claude thinks** → 🔧 **Tools execute** → ✅ **Answer back**

### What Makes It Special

- ✅ **HTTP API Integration** - 8 RESTful endpoints for n8n, webhooks, anything
- ✅ **Service Catalog Knowledge** - Built-in understanding of YOUR infrastructure
- ✅ **18 Custom Tools** - Kubernetes, GitHub, AWS, Datadog integrations
- ✅ **Business Logic** - Priority classification, known issues, dependency awareness
- ✅ **Real Example** - Already running your Slack bot!

### Example Intelligence

<div class="highlight">

**Knows your infrastructure:**
- "chores-tracker slow startup is NORMAL (5-6 min)"
- "Vault unsealing procedure after pod restart"
- "Service dependency impact analysis"

</div>

---

# oncall-agent: Technical Details

## Architecture & Integration

<div class="columns">
<div class="column">

### Stack
- **Framework**: FastAPI (HTTP server)
- **LLM Access**: Anthropic API (direct messages)
- **Tools**: Python libraries
  - kubernetes-client
  - PyGithub
  - boto3
  - requests

### Modes
- **API Mode**: HTTP server for n8n
- **Daemon Mode**: Continuous monitoring

</div>
<div class="column">

### Integration Points
- **n8n Workflows** - Orchestration
- **Slack Bot** - Chat interface
- **Custom Tools** - Kubernetes, GitHub, AWS

</div>
</div>

### Production Metrics

<div class="metric">
**Already Running**: Slack bot integration complete
</div>

<div class="metric">
**Implementation Time**: 2-3 weeks for basic setup
</div>

<div class="metric">
**Monthly Cost**: ~$50-100 (usage-based, highly variable)
</div>

---

# n8n: The Orchestration Layer

## Visual Workflow Engine for Slack Integration

### The Flow
**Slack Message** → **Extract Data** → **Claude AI** → **Tool Selection** → **Slack Response**

### Key Components

- 🎯 **Slack Trigger** - Captures messages in thread
- 🧠 **Claude Haiku** - Decides which tool to call
- 🔧 **Tool Binding** - oncall_agent_query, website_health_query
- 💾 **Memory Buffer** - 10-message conversation window
- ✉️ **Response** - Posts back to Slack thread

### Why n8n?

<div class="highlight">
Low-code orchestration: Connect Slack → Claude → oncall-agent visually, no code changes needed. Already running in production.
</div>

---

# n8n Workflow Details

## The 7 Components

1. **extract_slack_data** - Parses message, thread ID, session ID
2. **AI Agent** - Claude Haiku decides which tool to call
3. **Anthropic Chat Model** - Language model backend
4. **conversation_memory** - LangChain 10-message buffer
5. **oncall_agent_query** - HTTP POST to oncall-agent API
6. **website_health_query** - HTTP GET health checks
7. **send_slack_response** - Posts response to Slack thread

---

# oncall-agent: Advantages & Tradeoffs

## Why Choose This Approach?

<div class="highlight api">

**✅ Advantages**
- **Simple to understand** - Just Python + API calls
- **Easy to customize** - Add any Python library easily
- **Flexible deployment** - Runs anywhere (containers, serverless, VMs)
- **Already in use** - Proven with Slack bot
- **Familiar pattern** - Looks like most Python backends

**⚠️ Tradeoffs**
- **Requires n8n orchestrator** - Anthropic API lacks built-in memory/context
- **You build context management** - Manual session handling needed
- **No conversation persistence** - n8n handles this via its memory buffer
- **Manual tool integration** - Must define each tool separately
- **Sequential API calls** - Slower for large investigations

</div>

---

# Approach 2: k8s-monitor

## Autonomous AI Monitoring with Claude Agent SDK

### How It Works

**Every 15 minutes** → **Full cluster analysis** → **Smart escalation** → **Notifications**

### What Makes It Special

- ✅ **Autonomous** - Runs without human intervention
- ✅ **Long-Context Memory** - Remembers previous cycles (120k token window)
- ✅ **Trend Detection** - Identifies escalation patterns across cycles
- ✅ **Multi-Agent** - Specialized subagents for different tasks
- ✅ **MCP Integration** - Structured tool access via Model Context Protocol
- ✅ **Smart Pruning** - Preserves critical incidents, manages context limits

### Key Intelligence Examples

<div class="highlight">

**Cycle 1:** "Found 5 unhealthy pods in monitoring namespace"

**Cycle 2:** "Detected escalation: 5 → 13 issues (2.6x increase). Probable cause: node-2 memory pressure"

**Cycle 3:** "Escalation continues: 13 → 56 issues across 8 namespaces. PATTERN DETECTED: Cascading failure from single node"

</div>

---

# k8s-monitor: Technical Details

## Architecture & Integration

<div class="columns">
<div class="column">

### Stack
- **Framework**: Claude Agent SDK
- **LLM Access**: Anthropic API (structured)
- **Orchestration**: Multi-agent coordination
- **Tools**: MCP Servers
  - Kubernetes (Node.js)
  - GitHub (Node.js)
  - Atlassian (Node.js)

### Modes
- **Stateless**: Independent cycles (~8K tokens)
- **Persistent**: Long-context (~15K tokens)

</div>
<div class="column">

### 6 Subagents
- `k8s-diagnostics` - Bulk health checks
- `k8s-remediation` - Safe rolling restarts
- `k8s-log-analyzer` - Root cause analysis
- `k8s-cost-optimizer` - Resource utilization
- `k8s-github` - Deployment correlation
- `k8s-jira` - Smart ticket management

### Session Features
- Persistent conversation history
- Automatic pruning at 80% token limit
- Preserves critical incidents
- Auto-recovery on restart

</div>
</div>

### Production Metrics

<div class="metric">
**Test Coverage**: 208 passing tests
</div>

<div class="metric">
**Cycle Time**: 45-90 seconds
</div>

<div class="metric">
**Scale**: 20+ namespaces, 200+ pods per cycle
</div>

---

# Long-Context Memory in Action

## Real Production Data: Message History Grows Across Cycles

### The Proof

```
🚀 RUNNING IN LONG-CONTEXT PERSISTENT MODE
   Session ID: k8s-monitor-production
   Max Context Tokens: 120000
```

**Message history accumulating:**
- Cycle 1 (19:24): 1 message in history, 1,930 tokens
- Cycle 2 (19:54): 3 messages in history, 2,449 tokens
- Cycle 3 (20:24): 5 messages in history, 4,756 tokens

Claude maintains conversation memory across monitoring cycles!

---

# Why Long-Context Matters

## Detecting Patterns Over Time

<div class="highlight">

**Without Long-Context (Stateless):**
- Cycle 1: "6 issues found" → Analysis complete
- Cycle 2: "0 issues found" → Analysis complete
- **Problem**: No way to know if improving or coincidence

**With Long-Context (Persistent):**
- Cycle 1: "6 issues found"
- Cycle 2: "Issues resolved (6→0). System recovering ✅"
- Cycle 3: "NEW escalation (0→12). Pattern change detected ⚠️"

</div>

### Real Intelligence Gains

- ✅ Detects escalation trends in minutes
- ✅ Distinguishes transient from recurring issues
- ✅ Answers "is this getting worse?"
- ✅ Efficient token usage (4.7K by Cycle 3)

---

# k8s-monitor: Advantages & Tradeoffs

## Why Choose This Approach?

<div class="highlight sdk">

**✅ Advantages**
- **Autonomous** - No human needed to trigger
- **Long-context management** - Built-in conversation persistence
- **Trend detection** - Automatic pattern recognition
- **Multi-agent coordination** - Specialized agents for different tasks
- **Structured tools** - MCP provides standardized access
- **Production-ready** - 208 passing tests, battle-tested
- **Scalable** - Designed for complex multi-agent workflows

**⚠️ Tradeoffs**
- More complex architecture to understand
- Requires Node.js for MCP servers
- Higher token usage (~15K/cycle)
- Steeper learning curve
- More operational overhead

</div>

---

# Side-by-Side Comparison

<table class="comparison-table">
<tr>
  <th>Aspect</th>
  <th>oncall-agent (API)</th>
  <th>k8s-monitor (SDK)</th>
</tr>
<tr>
  <td><strong>Entry Point</strong></td>
  <td>On-demand queries (HTTP)</td>
  <td>Autonomous (every 15 min)</td>
</tr>
<tr>
  <td><strong>Memory/Context</strong></td>
  <td>Stateless or manual sessions</td>
  <td>Persistent (120k tokens)</td>
</tr>
<tr>
  <td><strong>Trend Detection</strong></td>
  <td>Manual (user queries)</td>
  <td>Automatic across cycles</td>
</tr>
<tr>
  <td><strong>Setup Complexity</strong></td>
  <td>⭐ Simple (Python only)</td>
  <td>⭐⭐⭐ Complex (SDK + MCP)</td>
</tr>
<tr>
  <td><strong>Orchestration</strong></td>
  <td>Requires n8n for memory</td>
  <td>Built into Agent SDK</td>
</tr>
<tr>
  <td><strong>Token Usage</strong></td>
  <td>~8K per query</td>
  <td>~15K per cycle</td>
</tr>
<tr>
  <td><strong>When to Use</strong></td>
  <td>Interactive troubleshooting</td>
  <td>Proactive monitoring</td>
</tr>
</table>

---

# Why Not Both?

## They're Complementary, Not Competing

<div class="columns">
<div class="column">

### oncall-agent (Interactive)
- Team member notices anomaly
- Queries: "What's wrong with service X?"
- Gets immediate analysis + recommendations
- Solves 90% of issues with one query

</div>
<div class="column">

### k8s-monitor (Proactive)
- Runs automatically every 15 min
- Detects trends before humans notice
- Alerts team to P0/P1 issues
- Catches the 10% you'd miss

</div>
</div>

### Combined Benefits

<div class="highlight">

**Both running simultaneously**:
- ✅ Autonomous monitoring catches issues early (k8s-monitor)
- ✅ Interactive queries when team needs answers (oncall-agent)
- ✅ Redundant coverage - if one misses it, the other catches it
- ✅ Different UX for different use cases
- ✅ Learning lab - experiment with both patterns

</div>

---

# Safety & Cluster Protection

## How Both Approaches Keep Your Cluster Safe

### Hard-Coded Protection

```
ALLOWED_CLUSTERS = ["dev-eks"]
PROTECTED_CLUSTERS = ["prod-eks", "staging-eks"]
```

**Result**: Any protected cluster access raises `PermissionError` immediately.

### oncall-agent Safety

- ✅ **Read-only analysis** - Gathers information, no modifications
- ✅ **Recommendations only** - Human must approve all actions
- ✅ **API key authentication** - Rate limiting, audit trails
- ✅ **Session isolation** - Each conversation independent

### k8s-monitor Safety

- ✅ **Pre-execution hooks** - Tools blocked before running
- ✅ **Approved auto-remediation** - Only safe actions (rolling restarts on 2+ replica deployments)
- ✅ **Namespace protection** - Can't delete critical namespaces
- ✅ **Audit trail** - All actions logged with timestamps

---

# Key Takeaways

## What You're Getting

✅ **Two production-ready implementations** - Not prototypes, not experiments

✅ **Complementary patterns** - Reactive AND proactive monitoring

✅ **Real metrics** - Cost estimates, timelines, resource usage

✅ **Safety-first** - Hard-coded cluster protection, audit trails

✅ **Choice** - Pick one approach or run both together

✅ **Learning opportunity** - Understand when to use API vs SDK

---

# Questions & Discussion

## Let's Talk!

### What we can explore:

- **"How hard would it be for us to implement?"**
- **"Which approach fits our team better?"**
- **"Can we customize this for our infrastructure?"**
- **"What would we need to invest in time/cost?"**
- **"Do we want to pilot this in dev first?"**

### No Pressure Agenda

- 🎯 Learn from real production examples
- 🎯 Understand API vs SDK tradeoffs
- 🎯 Explore potential value for your team
- 🎯 Start simple → go advanced if it resonates
- 🎯 Maybe lightens your load, builds something cool

---

# Thank You

## Let's Reduce Incident Triage Together

### Resources

- **oncall-agent README**: `/oncall/README.md`
- **k8s-monitor README**: `/k8s-monitor/README.md`
- **CLAUDE.md Architecture Guide**: `/CLAUDE.md`

### Quick Links

- 📊 API Docs: http://localhost:8000/docs
- 🔍 Source Code: `github.com/anthropics/claude-agents`
- 📚 Claude Docs: https://docs.claude.com/

### Contact

**Ari Sela** - AI/MCP Integration Specialist
*Making Kubernetes troubleshooting smarter, one agent at a time*

---
