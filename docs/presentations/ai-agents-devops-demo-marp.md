---
marp: true
theme: gaia
paginate: true
class: lead
author: Ari Sela
title: Smarter DevOps with Claude AI Agents
---

# Smarter DevOps with Claude AI Agents

**Proactive Monitoring & Interactive Troubleshooting**

<div style="position: absolute; bottom: 40px; left: 50%; transform: translateX(-50%); text-align: center; font-size: 18px;">

**Ari Sela**
Senior DevOps Manager at NomiHealth

</div>

---
## The Problem We Face Today

### Manual Troubleshooting Challenges

<div style="font-size: 0.85em;">

🔀 **Multiple Data Sources**
⏱️ **Time-Consuming Correlation**
🚨 **Alert Fatigue**
🔄 **Context Switching**
🧠 **Tribal Knowledge Gap**
❌ **Missed Connections**

</div>

![width:500px](./images/multiple-sources.png)

---
### Real-World Impact

⏱️ **20-40 minutes Average incident investigation time**
🎯 **Our Goal: Reduce to 2-5 minutes**

---

## Our Solution: Dual AI Agent Architecture

### Two Complementary Approaches

| **K8s Monitor Agent** | **OnCall Agent** |
|----------------------|------------------|
| 🤖 **Proactive** monitoring | 💬 **Interactive** troubleshooting |
| ⏰ Runs every 15 minutes | 🚨 On-demand via Slack |
| 📊 Full cluster scans | 🎯 Targeted investigations |
| 🎫 Creates Jira tickets | 📝 Conversational responses |
| 🔔 Teams notifications | 💡 Context-aware answers |

---

### How They Work Together

<div style="text-align: center; margin: 20px 0;">

![width:600px](./images/tool-interactions.png)

</div>

---
## K8s Monitor Agent
**Architecture & Tech Stack**
---

### Built on Claude Agent SDK

🧠 **Persistent Memory**
🤝 **Multi-Agent Coordination**
🔌 **MCP Tool Access**
⚙️ **GitOps Configuration**
🛡️ **Safety Hooks**
📂 **`.claude/` Directory**

---

### 6 Specialized Subagents

<div style="font-size: 0.9em;">

| Subagent | Purpose |
|----------|---------|
| 🔍 **Diagnostics** | Bulk health checks |
| 🔧 **Remediation** | Safe auto-healing |
| 📝 **Log Analyzer** | Root cause analysis |
| 💰 **Cost Optimizer** | Resource insights |
| 🔗 **GitHub** | Deployment correlation |
| 🎫 **Jira** | Smart ticketing |

</div>

---

### MCP Integration

**Structured tool access to:**

☸️ Kubernetes (pods, events, logs)
🔗 GitHub (PRs, deployments)
🎫 Jira (tickets, comments)

---

### Safety First

**Pre-execution validation:**

<div style="text-align: center; font-size: 1.3em; margin: 40px 0;">

🛡️ → 📋 → 📢

**Validate → Log → Notify**

</div>

**Blocks dangerous operations before execution**

---

## OnCall Agent

**Architecture & Tech Stack**

---

### Built on Anthropic API (Direct)

⚡ **Fast Responses**
🔌 **HTTP API (n8n)**
🎯 **Stateless Design**
📚 **Direct Python Libraries**
💬 **Slack Integration**
🔄 **Two-Turn Investigation**

---

### Dual-Mode Operation

<div style="font-size: 1.2em; text-align: center; margin: 40px 0;">

**1. API Mode** → 🔌 HTTP Server (n8n)

**2. Daemon Mode** → ⏰ Autonomous Monitoring

</div>

---

### n8n Orchestration

**Workflow manages the agent:**

<div style="text-align: center; margin: 20px 0;">

![width:900px](./images/n8n-workflow.png)

</div>

**n8n handles:** Memory, tools, coordination

---

## Benefits for DevOps

<!-- .slide: data-background="#27ae60" -->

---

### K8s Monitor Benefits

🔍 **Proactive Detection**
🤖 **Auto-Correlation**
📚 **Knowledge Preservation**
✅ **Safe Auto-Remediation**

---

### OnCall Agent Benefits

⚡ **Instant Answers**
🔎 **Deep Investigation**
🔌 **Flexible Integration**
📖 **Low Barrier to Entry**

---

### When to Use Each

| Use Case | K8s Monitor | OnCall Agent |
|----------|-------------|--------------|
| **Proactive monitoring** | ✅ | |
| **Interactive questions** | | ✅ |
| **Comprehensive coverage** | ✅ | |
| **Fast responses** | | ✅ |
| **Safety-critical** | ✅ | |
| **External integrations** | | ✅ |

---

## Demo Time!

**Let's see these agents in action**

---

### Demo 1: K8s Monitor Agent

⏰ **Autonomous Monitoring**
📊 **Full Cluster Scan**
🎫 **Jira Ticket Creation**
📢 **Teams Notifications**

---

### Demo 2: OnCall Agent via Slack

<div style="text-align: center; font-size: 1.5em;">

💬 **Interactive Chat**
🧠 **Context Memory**
🔍 **Deep Investigation**
📝 **RCA Reports**

</div>

---

## What's Next?

### Planned Enhancements

🔧 **Add business logic integration to oncall-agent**

🔗 **Enable k8s-monitor to delegate deep dives to oncall-agent**

🛡️ **Add production protection hooks to k8s-monitor**

📚 **Implement skills in k8s-monitor for better token efficiency**

---

## Resources

### 📦 Source Code

**GitHub Repository:** [github.com/arigsela/claude-agents](https://github.com/arigsela/claude-agents)
- 📁 `k8s-monitor/` - K8s Monitor Agent (Claude Agent SDK)
- 📁 `oncall/` - OnCall Agent (Anthropic API)

### 📚 Documentation

**Claude Agent SDK:** [docs.claude.com/en/api/agent-sdk/overview](https://docs.claude.com/en/api/agent-sdk/overview)

**Claude Client SDKs:** [docs.claude.com/en/api/client-sdks](https://docs.claude.com/en/api/client-sdks)

---

## Questions?

**Thank you!**

