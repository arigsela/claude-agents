---
title: "Intelligent DevOps with Claude AI Agents"
subtitle: "Proactive Monitoring & Interactive Troubleshooting"
author: "DevOps Engineering Team"
date: "2025-10-23"
theme: dracula
highlightTheme: dracula
revealOptions:
  transition: 'none'
  controls: true
  progress: true
  slideNumber: true
  backgroundTransition: 'none'
---

# Intelligent DevOps with Claude AI Agents

**Proactive Monitoring & Interactive Troubleshooting**

---

## The Problem We Face Today

<!-- .slide: data-background="#c0392b" -->

---

### Manual Troubleshooting Challenges

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 40px; text-align: center;">

<div>
🔀<br/>
**Multiple Data Sources**
</div>

<div>
⏱️<br/>
**Time-Consuming Correlation**
</div>

<div>
🚨<br/>
**Alert Fatigue**
</div>

<div>
🔄<br/>
**Context Switching**
</div>

<div>
🧠<br/>
**Tribal Knowledge Gap**
</div>

<div>
❌<br/>
**Missed Connections**
</div>

</div>

---

### Real-World Impact

<div style="font-size: 3em; text-align: center; margin: 60px 0;">
⏱️ **15-20 minutes**
</div>

<div style="text-align: center; font-size: 1.2em;">
**Average incident investigation time**
</div>

<div style="margin-top: 40px; text-align: center;">
🎯 **Our Goal:** Reduce to 2-5 minutes
</div>

---

## Our Solution: Dual AI Agent Architecture

<!-- .slide: data-background="#27ae60" -->

---

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

<div style="text-align: center; font-size: 1.5em; margin: 40px 0;">

☸️ **Kubernetes Cluster**

↙️ ↘️

🤖 **K8s Monitor** → 📋 Jira + 📢 Teams

💬 **OnCall Agent** → 💭 Slack + 📊 RCA

</div>

---

## K8s Monitor Agent

**Architecture & Tech Stack**

<!-- .slide: data-background="#2c3e50" -->

---

### Built on Claude Agent SDK

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 30px;">

<div>
🧠 **Persistent Memory**
</div>

<div>
🤝 **Multi-Agent Coordination**
</div>

<div>
🔌 **MCP Tool Access**
</div>

<div>
⚙️ **GitOps Configuration**
</div>

<div>
🛡️ **Safety Hooks**
</div>

<div>
📂 **`.claude/` Directory**
</div>

</div>

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

- ☸️ Kubernetes (pods, events, logs)
- 🔗 GitHub (PRs, deployments)
- 🎫 Jira (tickets, comments)

**Type-safe, no parsing errors**

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

<!-- .slide: data-background="#34495e" -->

---

### Built on Anthropic API (Direct)

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 30px;">

<div>
⚡ **Fast Responses**
</div>

<div>
🔌 **HTTP API (n8n)**
</div>

<div>
🎯 **Stateless Design**
</div>

<div>
📚 **Direct Python Libraries**
</div>

<div>
💬 **Slack Integration**
</div>

<div>
🔄 **Two-Turn Investigation**
</div>

</div>

---

### Dual-Mode Operation

<div style="font-size: 1.2em; text-align: center; margin: 40px 0;">

**1. API Mode** → 🔌 HTTP Server (n8n)

**2. Daemon Mode** → ⏰ Autonomous Monitoring

</div>

---

### n8n Orchestration

**Workflow manages the agent:**

<div style="text-align: center; font-size: 1.3em; margin: 40px 0;">

💬 Slack → 🔄 n8n → 🤖 Claude → 📊 Response

</div>

**n8n handles:** Memory, tools, coordination

---

## Benefits for DevOps

<!-- .slide: data-background="#27ae60" -->

---

### K8s Monitor Benefits

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 40px; text-align: center;">

<div>
🔍<br/>
**Proactive Detection**
</div>

<div>
🤖<br/>
**Auto-Correlation**
</div>

<div>
📚<br/>
**Knowledge Preservation**
</div>

<div>
✅<br/>
**Safe Auto-Remediation**
</div>

</div>

---

### OnCall Agent Benefits

<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 40px; text-align: center;">

<div>
⚡<br/>
**Instant Answers**
</div>

<div>
🔎<br/>
**Deep Investigation**
</div>

<div>
🔌<br/>
**Flexible Integration**
</div>

<div>
📖<br/>
**Low Barrier to Entry**
</div>

</div>

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

<div style="text-align: center; font-size: 1.5em;">

⏰ **Autonomous Monitoring**

📊 **Full Cluster Scan**

🎫 **Jira Ticket Creation**

📢 **Teams Notifications**

</div>

---

### Demo 2: OnCall Agent via Slack

<div style="text-align: center; font-size: 1.5em;">

💬 **Interactive Chat**

🧠 **Context Memory**

🔍 **Deep Investigation**

📝 **RCA Reports**

</div>

---

## Conclusion

<!-- .slide: data-background="#27ae60" -->

---

### The Power of Dual Agents

<div style="font-size: 1.3em; text-align: center; margin: 60px 0;">

🤖 **Proactive** + 💬 **Reactive**

⏱️ **20-40 min** → **2-5 min**

🚨 **Alert Noise** → **Smart Insights**

</div>

---

## Questions?

**Thank you!**
