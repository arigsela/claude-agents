# Claude Agents Repository

**Learning Lab for Anthropic AI Integration Patterns**

This repository demonstrates different approaches to building intelligent automation agents with Anthropic's Claude AI, helping teams understand when to use each SDK and integration pattern.

## 🎓 Learning Objectives

Each project showcases **different Anthropic integration patterns** for the same use case (Kubernetes monitoring), highlighting:

1. **When to use Claude Agent SDK** vs **when to use Anthropic API directly**
2. **Multi-agent architecture** vs **single-agent architecture**
3. **MCP (Model Context Protocol)** vs **direct API libraries**
4. **Tradeoffs**: Flexibility vs simplicity, scalability vs overhead, context management vs stateless

By comparing both implementations, teams can learn which patterns fit their specific needs.

---

## Projects

### 🤖 [EKS Monitoring Agent](./eks-monitoring-agent/)

**SDK Used**: Claude Agent SDK | **Architecture**: Multi-Agent System

**Purpose**: Demonstrates **autonomous agent architecture** with persistent memory, specialized subagents, and MCP tool integration.

**What You'll Learn**:
- How to build **multi-agent systems** with specialized roles
- Using **MCP servers** for structured external tool access
- Implementing **institutional memory** (`.claude/CLAUDE.md` reloaded each cycle)
- Managing **agent context** across monitoring cycles
- Building **safety hooks** that intercept tool calls

**Architecture**:
```
Main Orchestrator (Claude Agent SDK client with persistent conversation)
├── k8s-diagnostics     → Haiku for fast bulk health checks
├── k8s-jira            → Sonnet for smart ticket management
├── k8s-log-analyzer    → Sonnet for complex pattern analysis
├── k8s-remediation     → Sonnet for safety-critical operations
├── k8s-github          → Sonnet for deployment correlation
└── k8s-cost-optimizer  → Haiku for cost-effective analysis

External Tools (via MCP):
├── Kubernetes MCP (Go binary)      → Structured K8s operations
├── GitHub MCP (Go binary)          → GitHub API operations
└── Atlassian MCP (Docker)          → Jira ticket management
```

**Key Features**:
- **Multi-Agent Coordination**: Orchestrator delegates to specialized subagents
- **MCP Integration**: 3 external MCP servers provide structured tool access
- **Smart Jira Management**: Anti-spam logic, only comments on significant changes
- **Persistent Context**: Maintains conversation state across cycles
- **Safety Hooks**: Pre-tool-execution validation layer

**Use Case**:
- Autonomous monitoring requiring **persistent state** and **complex workflows**
- Large clusters needing **efficient bulk operations**
- Formal incident tracking with **Jira integration**

**Quick Start**:
```bash
cd eks-monitoring-agent
pip install -r requirements.txt
cp .env.example .env
python monitor_daemon.py
```

[→ Full Documentation](./eks-monitoring-agent/README.md)

---

### 🚨 [On-Call Troubleshooting Agent](./oncall-agent-api/)

**SDK Used**: Anthropic API (Direct) | **Architecture**: Single-Agent + FastAPI

**Purpose**: Demonstrates **direct API integration** with Anthropic for stateless analysis and **HTTP API wrapper** for n8n integration.

**What You'll Learn**:
- Using **Anthropic API directly** without Agent SDK overhead
- Building **stateless LLM analysis** (two-turn investigation)
- Creating **HTTP API wrappers** around Claude for external integrations
- Implementing **dual-mode architecture** (daemon + API in same codebase)
- Managing **context manually** via n8n's conversation history

**Architecture**:
```
Daemon Mode (Orchestrator + Anthropic API):
K8s Event Watcher (60s) → Incident Detected
    ↓
Anthropic API Turn 1 (assess severity)
    ↓
Data Collection (K8s, GitHub, AWS)
    ↓
Anthropic API Turn 2 (root cause + remediation)
    ↓
Teams Notification

API Mode (FastAPI + Anthropic API):
n8n AI Agent → HTTP Request → FastAPI Server
    ↓
Anthropic API (stateless query)
    ↓
JSON Response → n8n handles context
```

**Key Features**:
- **Direct API Usage**: No SDK overhead, calls Anthropic Messages API directly
- **HTTP API**: FastAPI server for n8n AI Agent integration
- **Stateless Design**: n8n manages conversation context, agent is stateless
- **Dual Mode**: Single codebase supports both daemon and API deployment
- **Simple Integration**: Direct Python libraries (kubernetes, boto3, PyGithub)

**Use Case**:
- **n8n integration** requiring HTTP API endpoints
- **Stateless analysis** where context is managed externally
- **Simpler architecture** for smaller clusters (<15 namespaces)
- Teams-only notifications (no Jira)

**Quick Start**:
```bash
cd oncall-agent-api
source venv/bin/activate
docker compose up  # Runs both daemon and API
```

[→ Full Documentation](./oncall-agent-api/README.md)

---

## 📚 SDK Comparison: Learning from Both Approaches

### When to Use Claude Agent SDK (EKS Monitoring Agent)

**✅ Best For:**
- **Persistent conversational agents** that maintain state across interactions
- **Complex workflows** requiring multiple specialized subagents
- **Tool-heavy operations** where MCP provides structured access
- **Dynamic context** that changes over time (institutional memory)
- **Safety-critical** operations needing pre-execution validation hooks

**🎯 You Get:**
- Built-in context/memory management
- Multi-agent coordination via `Task` tool
- MCP tool integration out-of-the-box
- Safety hooks for tool call interception
- Configuration-driven behavior (`.claude/` directory)

**⚠️ Tradeoffs:**
- More complex setup (Node.js, Docker for MCP servers)
- Additional dependencies (MCP server processes)
- Learning curve for multi-agent patterns
- MCP overhead for simple operations

### When to Use Anthropic API Directly (On-Call Agent)

**✅ Best For:**
- **Stateless analysis** where external system manages context (n8n, web UI)
- **HTTP API wrappers** for third-party integrations
- **Simple, focused tasks** that don't need persistent memory
- **Performance-critical** applications avoiding SDK/MCP overhead
- **Quick prototyping** without architectural complexity

**🎯 You Get:**
- Full control over request/response flow
- Minimal dependencies (just `anthropic` package)
- Direct API calls (no MCP intermediary)
- Easier to understand and debug
- Works great with FastAPI/Flask for HTTP wrappers

**⚠️ Tradeoffs:**
- Manual context management (you track conversation history)
- No built-in tool calling (you implement tool logic)
- No safety hooks (you build validators manually)
- More code for multi-turn workflows

---

## 🔬 Side-by-Side Technical Comparison

| Aspect | EKS Agent (Agent SDK) | On-Call Agent (Direct API) |
|--------|----------------------|---------------------------|
| **SDK Choice** | Claude Agent SDK | Anthropic API (Messages) |
| **Context Management** | ✅ Automatic (persistent conversation) | ❌ Manual (n8n manages) |
| **Tool Access** | MCP servers (Kubernetes, GitHub, Atlassian) | Direct Python libs (kubernetes, PyGithub, boto3) |
| **Architecture** | Multi-agent (6 specialized subagents) | Single-agent (monolithic) |
| **Configuration** | `.claude/` directory (Markdown files) | `config/` YAML files |
| **Safety Hooks** | Pre-tool-execution hooks (3 layers) | Hard-coded validation only |
| **Memory** | Conversation persists across cycles | Stateless (each query independent) |
| **n8n Integration** | ❌ No HTTP API | ✅ FastAPI server |
| **Jira Integration** | ✅ MCP server with smart commenting | ❌ Not implemented |
| **Setup Complexity** | Medium (MCP servers, hooks) | Low (just Python) |
| **Dependencies** | Python + Node.js + Docker | Python + Docker |
| **Best For** | Long-running autonomous agents | HTTP API wrappers, stateless queries |
| **Learning Focus** | Multi-agent patterns, MCP, hooks | Direct API usage, FastAPI integration |

---

## 🎯 Choosing the Right Pattern for Your Use Case

### Use Claude Agent SDK When:
1. **Agent needs memory** across multiple interactions (monitoring cycles, investigations)
2. **Complex workflows** require coordination between specialized agents
3. **You want MCP integration** for structured tool access (Kubernetes, Jira, Slack, etc.)
4. **Safety is critical** and you need pre-execution validation hooks
5. **Configuration-driven** behavior is preferred (update `.claude/` files without code changes)

**Example Use Cases:**
- Autonomous monitoring daemons (this repo)
- Multi-step incident response workflows
- Agents with institutional knowledge
- SRE automation requiring safety guardrails

### Use Anthropic API Directly When:
1. **Stateless analysis** where context is managed externally (n8n, web frontend)
2. **Building HTTP APIs** around Claude for integrations
3. **Simple, focused tasks** that don't need persistent memory
4. **Performance matters** and you want to avoid MCP overhead
5. **Quick prototyping** or proof-of-concepts

**Example Use Cases:**
- n8n AI Agent backends (this repo)
- Chatbots where frontend manages history
- One-shot analysis tasks (code review, log analysis)
- Microservices exposing Claude via REST API

---

## 🧪 Learning Exercises

### Exercise 1: Compare Performance
Run both agents on the same cluster and measure:
- Time to complete health check
- Number of API calls made
- Token usage for similar analysis
- Scalability with cluster size

### Exercise 2: Add a Feature
Try adding "cost optimization" to both:
- **EKS Agent**: Create new subagent in `.claude/agents/k8s-cost-optimizer.md`
- **On-Call Agent**: Add method in `src/tools/k8s_analyzer.py`

Notice the difference in:
- Where logic lives (configuration vs code)
- How to test changes (restart vs code reload)
- Integration patterns (MCP vs direct)

### Exercise 3: Build Custom Integration
Add Slack integration to both:
- **EKS Agent**: Use Slack MCP server + safety hook
- **On-Call Agent**: Use `slack-sdk` Python library directly

Compare: MCP abstraction vs direct library control

---

## 📊 Real-World Performance Metrics

Based on production usage with **dev-eks cluster** (40 nodes, 20+ namespaces, 200+ pods):

### EKS Monitoring Agent
- **Cycle time**: 45-90 seconds (full cluster scan)
- **MCP calls**: 3-5 per cycle (bulk queries)
- **Namespace coverage**: 100% (all 20+ namespaces checked)
- **Jira noise**: ~5 comments/day per ticket (smart filtering)
- **Teams notifications**: 1 per cycle (comprehensive summary)
- **Token usage**: ~15K tokens/cycle

### On-Call Agent
- **Cycle time**: 60-180 seconds (often timeouts)
- **K8s API calls**: 20+ per cycle (sequential namespaces)
- **Namespace coverage**: ~30-40% (timeouts after 8 namespaces)
- **Teams notifications**: 1 per incident (simpler format)
- **Token usage**: ~8K tokens/cycle (less complex analysis)

**Why the difference?**
- EKS agent: Bulk queries + specialized subagents = better coverage, more tokens
- On-Call agent: Sequential queries + simpler = lower coverage, fewer tokens
- **Neither is "better"** - depends on your needs (coverage vs cost)

---

## Repository Structure

```
claude-agents/
├── eks-monitoring-agent/      # Next-gen multi-agent monitoring (Jira + MCP)
│   ├── .claude/               # Agent configuration & institutional memory
│   │   ├── CLAUDE.md          # Cluster context (reloaded each cycle)
│   │   ├── settings.json      # Safety hooks configuration
│   │   ├── agents/            # 6 specialized subagent definitions
│   │   └── hooks/             # Safety validator, logger, Teams notifier
│   ├── bin/                   # MCP server wrappers
│   ├── monitor_daemon.py      # Main orchestrator (single entry point)
│   ├── docs/                  # Implementation guides
│   └── README.md
│
├── oncall-agent-api/          # Legacy incident response agent (n8n + Direct APIs)
│   ├── src/
│   │   ├── agent/             # Claude Agent SDK wrapper
│   │   ├── api/               # FastAPI server (n8n integration)
│   │   ├── integrations/      # Daemon mode orchestrator
│   │   └── tools/             # K8s/GitHub/AWS helpers
│   ├── config/                # YAML configuration files
│   ├── tests/                 # Test suite
│   ├── k8s/                   # Kubernetes manifests
│   └── docs/
│
└── README.md                  # This file
```

## Architecture Philosophy

This repository demonstrates **two complementary approaches** to building AI agents with Anthropic:

### Approach 1: Claude Agent SDK (EKS Monitoring Agent)
**Pattern**: Autonomous agent with persistent memory and multi-agent coordination

**When this pattern shines:**
- Agent runs continuously and maintains state across cycles
- Complex workflows benefit from specialized subagents
- Need structured tool access via MCP servers
- Configuration changes should apply without code redeployment

**Architectural Choices:**
1. **Multi-Agent System**: Orchestrator delegates to 6 specialized subagents (diagnostics, Jira, logs, remediation, GitHub, costs)
2. **MCP Integration**: External tools via Kubernetes, GitHub, Atlassian MCP servers
3. **Institutional Memory**: `.claude/CLAUDE.md` reloaded every cycle (living documentation)
4. **Safety Hooks**: Pre-execution validation layer intercepts tool calls
5. **Configuration-Driven**: Behavior defined in markdown files, not code

**Tradeoffs Accepted:**
- More dependencies (Node.js, Docker for MCP servers)
- Setup complexity (MCP configuration, hooks)
- Higher token usage (~15K/cycle) for comprehensive analysis

### Approach 2: Anthropic API (On-Call Agent)
**Pattern**: Stateless analysis with HTTP API wrapper for external integrations

**When this pattern shines:**
- External system (n8n) manages conversation context
- Need HTTP API for third-party integrations
- Stateless analysis without persistent memory
- Simpler architecture preferred

**Architectural Choices:**
1. **Direct API**: Calls Anthropic Messages API without SDK intermediary
2. **Direct Libraries**: kubernetes-python, boto3, PyGithub (no MCP layer)
3. **Dual Mode**: Same codebase for daemon (monitoring) + API (n8n)
4. **Stateless Design**: Each query is independent, n8n tracks history
5. **Code-Driven**: Behavior in Python code, not configuration files

**Tradeoffs Accepted:**
- Manual context management (n8n provides conversation history)
- No built-in tool abstractions (implement tools yourself)
- Hard-coded safety (no dynamic hooks)
- Sequential operations (simpler but slower for large clusters)

### Key Insight: Both Are Production-Ready

**Neither is "better" or "legacy"** - they solve different problems:

- **EKS Agent**: Best for **autonomous daemons** with complex state
- **On-Call Agent**: Best for **HTTP API wrappers** with external context management

**Use this repository to learn when each pattern fits YOUR use case.**

### Shared Principles

Regardless of SDK choice, all agents follow:
- ✅ **Safety First**: Cluster protections, validation, human-in-the-loop
- ✅ **Production Ready**: Logging, error handling, monitoring, audit trails
- ✅ **Cost Awareness**: Minimize LLM calls through intelligent deduplication
- ✅ **Observability**: Teams notifications, structured reports, actionable alerts

## Prerequisites

### EKS Monitoring Agent
- Python 3.10+
- Node.js (for Kubernetes & GitHub MCP servers)
- Docker (for Atlassian MCP server)
- kubectl with cluster access
- Anthropic API key
- GitHub Personal Access Token
- Jira API Token (optional, for ticket management)

### On-Call Agent
- Python 3.11+
- kubectl with cluster access
- Anthropic API key
- GitHub Personal Access Token
- Docker (for containerized deployment)

## Development

### Setup

**EKS Monitoring Agent:**
```bash
cd eks-monitoring-agent
pip install -r requirements.txt
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, GITHUB_PERSONAL_ACCESS_TOKEN, JIRA credentials

# Customize cluster context
vi .claude/CLAUDE.md  # Critical namespaces, SOPs, escalation rules

# Run daemon
python monitor_daemon.py
```

**On-Call Agent:**
```bash
cd oncall-agent-api
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, GITHUB_TOKEN, AWS credentials

# Run daemon
docker compose up

# OR run API only
./run_api_server.sh
```

### Code Quality Standards

All projects follow these standards:

```bash
black src/                     # Code formatting
ruff check src/                # Linting
mypy src/                      # Type checking (EKS agent uses type hints extensively)
pytest tests/                  # Testing
```

## 🔄 Running Both Agents Together

**Both agents can run simultaneously** - they serve complementary purposes:

### Scenario 1: EKS Agent (Monitoring) + On-Call Agent API (n8n Queries)

```bash
# Terminal 1: Start EKS monitoring daemon
cd eks-monitoring-agent
python monitor_daemon.py
# → Runs every 15 min, creates Jira tickets, sends Teams cycle summaries

# Terminal 2: Start On-Call API for n8n
cd oncall-agent-api
docker compose up oncall-agent-api -d
# → HTTP API on port 8000, responds to n8n queries
```

**Result**:
- ✅ Autonomous monitoring with Jira tracking
- ✅ Interactive troubleshooting via n8n
- ✅ Both monitoring the same cluster, different mechanisms

### Scenario 2: Compare Both Daemon Modes (Learning)

```bash
# Run both daemons in parallel (educational)
cd eks-monitoring-agent
python monitor_daemon.py &

cd oncall-agent-api
python src/integrations/orchestrator.py &

# Compare in Teams:
# - EKS sends rich cycle summaries with Jira tickets
# - On-Call sends simpler incident alerts
```

**Use this to learn:** How SDK choice affects notification quality, coverage, and token usage.

## 🚀 Future Enhancements

### Cross-Learning Opportunities:
- ⬜ **Port HTTP API to EKS Agent**: Add FastAPI mode for n8n (learn SDK limitations)
- ⬜ **Add MCP to On-Call Agent**: Integrate Jira MCP (learn MCP benefits)
- ⬜ **Multi-cluster support**: Monitor multiple clusters simultaneously
- ⬜ **Slack integration**: Alternative to Teams notifications

### New Agent Projects:
- **Deployment Agent**: Automated deployment analysis and rollback detection
- **Security Audit Agent**: Compliance checking with auto-remediation
- **Cost Optimization Agent**: AWS cost analysis with Claude recommendations

## Safety and Ethics

All agents in this repository:

✅ **Do**:
- Provide intelligent analysis and recommendations
- Monitor and alert on infrastructure issues
- Verify configurations and resources
- Document actions with full audit trails

❌ **Do Not**:
- Make automated destructive changes to production systems
- Bypass approval workflows
- Access sensitive data without proper authentication
- Operate on protected clusters without explicit safeguards

**Cluster Protection**: All agents enforce hard-coded cluster protections (e.g., `PROTECTED_CLUSTERS = ["prod-eks", "staging-eks"]`).

## License

Internal ArtemisHealth project - All rights reserved

## Contributing

1. Create a feature branch from `main`
2. Implement changes following code quality standards
3. Add/update tests as needed
4. Submit PR with detailed description
5. Ensure all CI checks pass

## 💡 Learning Resources

### Understanding the Code

**Start Here:**
1. **Read both READMEs** to understand architectural differences
2. **Compare `.claude/` vs `config/`** - configuration-driven vs code-driven
3. **Trace a health check** in both agents side-by-side
4. **Run learning exercises** (see exercises above)

### Key Concepts to Master

**Claude Agent SDK:**
- How `ClaudeSDKClient` manages persistent conversations
- Using `Task` tool to invoke subagents
- MCP server configuration and tool registration
- Safety hooks and tool call interception
- `setting_sources` for loading `.claude/` configuration

**Anthropic API (Direct):**
- Manual conversation history tracking
- Two-turn investigation patterns
- Direct tool implementation (no MCP abstraction)
- FastAPI integration for HTTP APIs
- Stateless request/response patterns

### Recommended Learning Path

1. **Week 1**: Run On-Call Agent (simpler)
   - Understand direct Anthropic API usage
   - See how n8n provides context management
   - Study two-turn investigation pattern

2. **Week 2**: Run EKS Monitoring Agent
   - See how Agent SDK manages context automatically
   - Understand multi-agent coordination
   - Study MCP server integration

3. **Week 3**: Compare Both
   - Run learning exercises
   - Measure performance differences
   - Decide which pattern fits your use case

## Support

**For Learning Questions:**
- Review code comments and documentation in both projects
- Compare implementations of the same feature (e.g., health checks)
- Run both agents and observe behavior differences

**For Issues:**
- Open GitHub issue with details
- Tag with project name (EKS Monitoring vs On-Call)

**For Team Collaboration:**
- Share learnings about SDK tradeoffs
- Document which pattern worked best for your use case
- Contribute improvements to both implementations

## Documentation

### EKS Monitoring Agent
- [Complete README](./eks-monitoring-agent/README.md) - Architecture, quick start, troubleshooting
- [Implementation Plan](./eks-monitoring-agent/docs/implementation-plan.md) - Phased development guide
- [MCP Setup Guide](./eks-monitoring-agent/docs/phase4-mcp-setup-guide.md) - MCP server configuration
- [Jira Integration](./eks-monitoring-agent/docs/JIRA-INTEGRATION.md) - Jira setup and smart commenting
- [Kubernetes Deployment](./eks-monitoring-agent/docs/KUBERNETES-DEPLOYMENT.md) - Production deployment

### On-Call Agent
- [Complete README](./oncall-agent-api/README.md) - Dual-mode architecture
- [API Documentation](./oncall-agent-api/docs/) - FastAPI endpoints
- [n8n Integration](./oncall-agent-api/docs/n8n-integrations/) - n8n AI Agent setup
- [Kubernetes Deployment](./oncall-agent-api/k8s/README.md) - K8s manifests guide

---

## 🎯 Repository Mission

**This is a learning lab, not just production code.**

The goal is to help DevOps teams understand:
- When to use Claude Agent SDK vs Anthropic API directly
- Tradeoffs between multi-agent and single-agent architectures
- Benefits and overhead of MCP vs direct library integration
- How context management differs between approaches
- Which patterns fit different operational needs

**Both implementations are production-ready** - choose based on your requirements:
- Need n8n integration? → On-Call Agent
- Need Jira + complex workflows? → EKS Monitoring Agent
- Want to learn both patterns? → Run them side-by-side!

**Contributions welcome** - especially comparisons, performance benchmarks, and lessons learned!

---

**Built with Claude AI** | ArtemisHealth DevOps Engineering | Learning Lab for AI Agent Patterns
