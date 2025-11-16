# RAG Stack Quickstart Guide

**For:** claude-agents repository
**Last Updated:** 2025-11-16

---

## TL;DR - What Should I Do?

You have **3 options** for adding RAG (memory/knowledge retrieval) to your agents:

| Option | Timeline | Cost/Month | Best For |
|--------|----------|------------|----------|
| **1. mem0 Only** | 2-6 weeks | $0 (Free tier) | Quick start, managed service |
| **2. PostgreSQL/pgvector + MCP** | 3-4 weeks | ~$72 | Self-hosted, DevOps control |
| **3. Hybrid (mem0 + pgvector)** | 4-6 weeks | ~$72 | **Recommended - Best of both** |

**Recommended: Option 3 (Hybrid)**

---

## Quick Decision Tree

```
Are you comfortable with managed services (like you use AWS, Anthropic)?
│
├─ YES → Start with mem0 (you have plans already!)
│         ├─ Execute: docs/implementations/mem0-k8s-monitor-implementation-plan.md
│         └─ Execute: docs/implementations/mem0-oncall-implementation-plan.md
│
└─ NO (want full control) → Build PostgreSQL/pgvector + MCP
          └─ Follow: docs/implementations/rag-stack-integration-guide.md

Want the best of both worlds?
└─ Do mem0 FIRST (2 weeks), then ADD pgvector (2 weeks) = Hybrid
```

---

## What You Already Have

✅ **Two production agents:**
- `k8s-monitor/` - Claude Agent SDK + Multi-Agent + MCP
- `oncall-agent-api/` - Anthropic API + Single-Agent + FastAPI

✅ **Comprehensive mem0 plans:**
- `docs/implementations/mem0-k8s-monitor-implementation-plan.md`
- `docs/implementations/mem0-oncall-implementation-plan.md`

✅ **MCP experience:**
- Already using: Kubernetes MCP, GitHub MCP, Atlassian MCP

✅ **Valuable knowledge (not yet indexed):**
- Jira tickets (historical remediation)
- GitHub commits/PRs (deployment impact)
- Slack alerts (incident patterns)
- Cycle reports (`/tmp/eks-monitoring-reports/`)
- Runbooks (probably in Confluence?)

---

## Option 1: mem0 Only

**What it is:**
- Managed RAG service (like AWS but for AI memory)
- Automatic memory extraction
- Python SDK integration

**Setup:**
```bash
# 1. Get API key from https://mem0.ai
# 2. Install SDK
pip install mem0ai

# 3. Follow your existing plans
cd k8s-monitor
# Execute: mem0-k8s-monitor-implementation-plan.md
```

**Pros:**
- ✅ Easiest to start (no infrastructure)
- ✅ You already have implementation plans
- ✅ 10K memories free (sufficient for 2-3 years)

**Cons:**
- ❌ Vendor lock-in
- ❌ Can't run complex SQL queries
- ❌ Limited to mem0's categorization

**Cost:** $0 (Free tier) or $249/month (Pro - after 10K memories)

**Your Documents:**
- Full plan: `docs/implementations/mem0-k8s-monitor-implementation-plan.md`
- Timeline: 5-6 weeks

---

## Option 2: PostgreSQL/pgvector + MCP

**What it is:**
- Self-hosted vector database (extension to PostgreSQL)
- MCP server wraps it (you already use MCP!)
- Ollama for embeddings (CPU-only, open source)

**Architecture:**
```
PostgreSQL (RDS or EKS)
    + pgvector extension
    ↓
MCP RAG Server (TypeScript/Python)
    ↓
Your agents (k8s-monitor, oncall)
    + Ollama embeddings (EKS pod)
```

**Setup:**
```bash
# 1. Enable pgvector
psql -h your-rds.amazonaws.com -U postgres
CREATE EXTENSION vector;

# 2. Deploy Ollama
kubectl apply -f k8s/ollama-embeddings.yaml

# 3. Create MCP server
cd mcp-rag-server
npm install
npm run build

# 4. Deploy to K8s
kubectl apply -f k8s/mcp-rag-server.yaml
```

**Pros:**
- ✅ Full control (no vendor lock-in)
- ✅ SQL + vector search combined
- ✅ Integrates with existing RDS
- ✅ You already use MCP pattern

**Cons:**
- ❌ More infrastructure to manage
- ❌ Manual memory extraction (no auto)
- ❌ Need to build MCP server

**Cost:** ~$72/month (RDS $42 + EKS pods $30)

**Your Documents:**
- Full guide: `docs/implementations/rag-stack-integration-guide.md`
- See: "Option 2" section
- Timeline: 3-4 weeks

---

## Option 3: Hybrid (Recommended)

**What it is:**
- mem0 for **dynamic learnings** (recent incidents, auto-extracted)
- pgvector for **static knowledge** (runbooks, long-term history)

**Why hybrid?**

| Knowledge Type | Best Storage | Why |
|---------------|--------------|-----|
| Recent incidents | **mem0** | Auto-extraction, fast, managed |
| Runbooks | **pgvector** | Structured, version-controlled, searchable |
| Deployment logs | **pgvector** | SQL queries + time-series |
| Alert patterns | **mem0** | Auto-learns deduplication |
| Historical metrics | **pgvector** | Complex queries, unlimited retention |

**Workflow:**
```python
# Your k8s-analyzer subagent

# 1. Search mem0 for recent incidents (last 90 days)
recent = mem0.search_similar_incidents(
    namespace="proteus-dev",
    incident_type="OOMKilled",
    limit=3
)

# 2. Search pgvector for runbooks (authoritative)
runbooks = mcp__rag__search_runbooks(
    query="proteus memory optimization",
    service="proteus",
    limit=2
)

# 3. Combine both for Claude
context = f"""
Recent incidents (mem0): {recent}
Runbooks (pgvector): {runbooks}
"""
```

**Setup Timeline:**

```
Week 1-2: mem0 for k8s-monitor
    └─ Follow: mem0-k8s-monitor-implementation-plan.md

Week 3-4: mem0 for oncall
    └─ Follow: mem0-oncall-implementation-plan.md

Week 5: PostgreSQL/pgvector infrastructure
    ├─ Enable pgvector extension
    ├─ Deploy Ollama embeddings
    └─ Index 50 runbooks

Week 6-7: Build MCP RAG server
    ├─ Create TypeScript MCP server
    └─ Deploy to K8s

Week 8: Integration
    └─ Both agents use BOTH sources

Week 9-10: Testing & rollout
```

**Pros:**
- ✅ Best of both worlds
- ✅ Start fast with mem0 (existing plans)
- ✅ Add pgvector for long-term knowledge
- ✅ No single vendor lock-in
- ✅ Right tool for each job

**Cons:**
- ❌ Most complex (two systems)
- ❌ Highest timeline (10 weeks)

**Cost:** ~$72/month (same as Option 2, mem0 free tier)

**Your Documents:**
- Full guide: `docs/implementations/rag-stack-integration-guide.md`
- See: "Recommended Architecture" section
- Timeline: 10 weeks

---

## Recommended: Start With mem0, Add pgvector Later

### Phase 1: mem0 (Weeks 1-4)

**Execute your existing plans:**

1. **k8s-monitor** (Weeks 1-2)
   ```bash
   cd k8s-monitor
   # Follow: ../docs/implementations/mem0-k8s-monitor-implementation-plan.md
   # Phases 1-3 (setup, orchestrator, subagents)
   ```

2. **oncall-agent** (Weeks 3-4)
   ```bash
   cd oncall-agent-api
   # Follow: ../docs/implementations/mem0-oncall-implementation-plan.md
   # Orchestrator integration only
   ```

**What you'll have:**
- ✅ Both agents with adaptive memory
- ✅ Incident correlation across cycles
- ✅ Remediation pattern learning
- ✅ Alert deduplication

**Limitations:**
- ❌ No runbook search yet
- ❌ No long-term historical archive
- ❌ Limited to 10K memories (free tier)

---

### Phase 2: Add pgvector (Weeks 5-8)

**Follow the hybrid guide:**

```bash
# Read full details in:
cat docs/implementations/rag-stack-integration-guide.md

# Quick setup:

# 1. Enable pgvector (5 min)
psql -h your-rds.amazonaws.com
CREATE EXTENSION vector;
\c rag_knowledge
\i sql/rag-schema.sql

# 2. Deploy Ollama (10 min)
kubectl apply -f k8s/ollama-embeddings.yaml

# 3. Index runbooks (1 hour)
# Export Confluence runbooks to docs/runbooks/*.md
python scripts/index_knowledge.py

# 4. Build MCP RAG server (Week 6-7)
cd mcp-rag-server
npm install
npm run build
docker build -t your-registry/mcp-rag-server:v1.0.0 .

# 5. Deploy MCP server (Week 8)
kubectl apply -f k8s/mcp-rag-server.yaml
```

**What you'll gain:**
- ✅ Runbook search for both agents
- ✅ Unlimited historical archive (SQL queries)
- ✅ Deployment correlation (time-series + vector)
- ✅ No memory limits

---

## Sample Implementations

### mem0 Only (Simplest)

```python
# k8s-monitor/src/orchestrator/persistent_monitor.py

from src.memory.memory_manager import MemoryManager

class PersistentMonitor:
    def __init__(self, settings: Settings):
        # Just mem0
        self.memory = MemoryManager(cluster_name=settings.cluster_name)

    async def run_cycle(self):
        # 1. Search mem0 for context
        recent_incidents = self.memory.search_similar_incidents(
            namespace="", incident_type="", limit=5
        )

        # 2. Run monitoring with context
        context = self.memory.format_memories_as_context(recent_incidents)
        results = await self.monitor.run_with_context(context)

        # 3. Store findings (automatic via MemoryManager)
        for incident in results["incidents"]:
            self.memory.store_incident_analysis(...)
```

### Hybrid (mem0 + pgvector)

```python
# k8s-monitor/src/orchestrator/persistent_monitor.py

from src.memory.memory_manager import MemoryManager
from src.memory.pgvector_client import PGVectorClient

class PersistentMonitor:
    def __init__(self, settings: Settings):
        # Both mem0 and pgvector
        self.mem0 = MemoryManager(cluster_name=settings.cluster_name)
        self.pgv = PGVectorClient(cluster_name=settings.cluster_name)

    async def run_cycle(self):
        # 1. Search BOTH sources
        recent_incidents = self.mem0.search_similar_incidents(
            namespace="", incident_type="", limit=5
        )
        runbooks = await self.pgv.search_runbooks(
            query="kubernetes incident response", limit=3
        )

        # 2. Combine contexts
        context = f"""
        {self.mem0.format_memories_as_context(recent_incidents)}

        ## Runbooks:
        {format_pgvector_runbooks(runbooks)}
        """

        # 3. Run monitoring
        results = await self.monitor.run_with_context(context)

        # 4. Store in BOTH
        for incident in results["incidents"]:
            # mem0 (auto)
            self.mem0.store_incident_analysis(...)

            # pgvector (manual, structured)
            await self.pgv.store_incident(...)
```

---

## Cost Summary

| Approach | Monthly Cost | Free Tier Duration |
|----------|--------------|-------------------|
| **mem0 only** | $0 → $249 | ~2.5 years (10K memories) |
| **pgvector only** | ~$72 | Forever (self-hosted) |
| **Hybrid** | ~$72 | Forever (pgvector) + 2.5 years (mem0 free) |

**Recommendation:** Hybrid gives you best value

---

## Next Steps

### This Week (Choose One)

**Option A: Start with mem0 (fastest)**
```bash
cd k8s-monitor
# Read: ../docs/implementations/mem0-k8s-monitor-implementation-plan.md
# Execute Phase 1: Setup & Foundation (1 day)
pip install mem0ai
# Get API key: https://mem0.ai
```

**Option B: Start with pgvector (more control)**
```bash
# Read: ../docs/implementations/rag-stack-integration-guide.md
# Execute: PostgreSQL Setup section
psql -h your-rds.amazonaws.com
CREATE EXTENSION vector;
```

**Option C: Plan hybrid (recommended)**
```bash
# Week 1: Start mem0 for k8s-monitor
# Week 5: Add pgvector infrastructure
# Week 10: Both agents using both sources
```

---

## Documentation Index

| Document | Purpose | Timeline |
|----------|---------|----------|
| **This file** | Quick decision guide | 5 min read |
| `rag-stack-integration-guide.md` | Complete hybrid architecture | 30 min read |
| `mem0-k8s-monitor-implementation-plan.md` | mem0 for k8s-monitor (existing) | 5-6 weeks |
| `mem0-oncall-implementation-plan.md` | mem0 for oncall (existing) | 2-3 weeks |

---

## Questions?

**"Which option should I choose?"**
→ Start with mem0 (you have plans), add pgvector later if needed

**"How much will this cost?"**
→ mem0 free for 2-3 years, pgvector ~$72/month

**"Can I switch later?"**
→ Yes! Start mem0, add pgvector, or replace mem0 with pgvector

**"What's the ROI?"**
→ 70% auto-detection of recurring issues, 40% less duplicate Jira comments

**"Do I need both agents?"**
→ No, you can start with just k8s-monitor or just oncall

---

## Success Metrics

After implementing RAG, you should see:

| Metric | Target | Timeframe |
|--------|--------|-----------|
| Recurring incident detection | 70% | Month 1 |
| Jira comment deduplication | 40% reduction | Month 2 |
| Runbook search latency | <200ms | Month 1 (pgvector) |
| Cost optimization retention | 90% | Month 3 |
| Cross-agent knowledge sharing | 100% | Month 2 |

---

**Ready to start? Pick your option and follow the corresponding guide!** 🚀
