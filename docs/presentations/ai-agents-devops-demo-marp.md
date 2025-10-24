---
marp: true
theme: gaia
paginate: true
class: lead
author: Ari Sela
title: Smarter DevOps with Claude AI Agents
---

<style scoped>
.author-info {
    position: absolute;
    bottom: 40px;
    left: 50%;
    transform: translateX(-50%);
    text-align: center;
    font-size: 18px;
}
</style>

# Smarter DevOps with Claude AI Agents

![width:400px](./images/smarter_devops.png)

<div class="author-info">

**Ari Sela**
Senior DevOps Manager at NomiHealth

</div>

---

<style scoped>
section {
    font-size: 26px;
}
.content {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    align-items: center;
}
</style>

## The Problem We Face Today

<div class="content">

🔀 **Multiple Data Sources**
⏱️ **Time-Consuming Correlation**
🚨 **Alert Fatigue**
🔄 **Context Switching**
🧠 **Tribal Knowledge Gap**
❌ **Missed Connections**

![width:350px](./images/multiple-sources.png)

</div>

---

<style scoped>
section {
    font-size: 26px;
}
.impact-content {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 60px;
    align-items: center;
}
</style>

### Real-World Impact

<div class="impact-content">

<div>

⏱️ **20-40 minutes Average incident investigation time**

🎯 **Our Goal: Reduce to 2-5 minutes**

</div>

<div style="text-align: center;">

![width:300px](./images/time-reduction.png)

</div>

</div>

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

### n8n Orchestration

**Workflow manages the agent:**

<div style="text-align: center; margin: 20px 0;">

![width:900px](./images/n8n-workflow.png)

</div>

**n8n handles:** Memory, tools, coordination

---

### Dual-Mode Operation

<div style="text-align: center; margin: 60px 0;">

![width:450px](./images/dual_mode_operation.png)

</div>

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

