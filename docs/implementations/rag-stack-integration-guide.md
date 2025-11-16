# RAG Stack Integration Guide for Claude Agents
## Leveraging Your Existing Agent Infrastructure with Adaptive Memory

**Version:** 1.0
**Last Updated:** 2025-11-16
**Status:** Strategic Planning Document

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Your Current State](#your-current-state)
3. [RAG Integration Options](#rag-integration-options)
4. [Recommended Architecture](#recommended-architecture)
5. [Implementation Strategies](#implementation-strategies)
6. [Shared Knowledge Infrastructure](#shared-knowledge-infrastructure)
7. [Deployment Examples](#deployment-examples)
8. [Cost & Performance Analysis](#cost--performance-analysis)
9. [Migration Path](#migration-path)
10. [Next Steps](#next-steps)

---

## Executive Summary

You have **two production-ready agent implementations** monitoring Kubernetes clusters:

1. **k8s-monitor** (Claude Agent SDK + Multi-Agent + MCP)
2. **oncall-agent-api** (Anthropic API + Single-Agent + FastAPI)

You've already created comprehensive mem0 integration plans for both. This document shows you how to **leverage RAG beyond mem0**, integrate with your existing infrastructure, and build a shared knowledge base across all agents.

### Key Insights

| RAG Approach | Best For | Integration Effort | Your Use Case |
|--------------|----------|-------------------|---------------|
| **mem0** (Existing Plans) | Quick start, managed service | ✅ **Lowest** (already planned) | Incident memory, remediation patterns |
| **PostgreSQL/pgvector + MCP** | Self-hosted, DevOps-friendly | Medium | Runbook search, deployment history |
| **Hybrid (mem0 + pgvector)** | **Best of both worlds** | Medium | **Recommended for you** |

### Recommended Strategy: Hybrid RAG Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hybrid RAG Architecture                      │
│                                                                 │
│  mem0 (Managed)                     PostgreSQL/pgvector         │
│  ├─ Dynamic incident learnings      ├─ Static runbooks          │
│  ├─ Remediation outcomes            ├─ Deployment logs          │
│  ├─ Alert patterns                  ├─ Historical metrics       │
│  └─ Cost insights                   └─ Full audit trail         │
│                                                                 │
│         Accessed via:                        Accessed via:      │
│      Python SDK (direct)                  MCP Server (RAG)      │
└─────────────────────────────────────────────────────────────────┘
         │                                            │
         └────────────────┬───────────────────────────┘
                          ▼
              ┌───────────────────────┐
              │  Your Claude Agents   │
              │  (k8s-monitor, oncall)│
              └───────────────────────┘
```

---

## Your Current State

### Existing Infrastructure

**You already have:**

| Component | Status | Location |
|-----------|--------|----------|
| **k8s-monitor agent** | ✅ Production (Phase 5 complete) | `k8s-monitor/` |
| **oncall-agent-api** | ✅ Production (dual-mode) | `oncall-agent-api/` |
| **mem0 integration plans** | 📋 Planned, not implemented | `docs/implementations/mem0-*.md` |
| **MCP server experience** | ✅ Using Kubernetes, GitHub MCP | k8s-monitor uses 3 MCP servers |
| **PostgreSQL** | 🤔 Likely available (RDS?) | Check your infra |
| **EKS clusters** | ✅ dev-eks, prod-eks | Current monitoring targets |

### Existing Knowledge Sources (Not Yet Indexed)

You have valuable knowledge scattered across:

```
📂 Knowledge Currently NOT in RAG:
├── Jira tickets (historical remediation patterns)
├── GitHub commits & PRs (deployment impact history)
├── Slack alerts (incident correlation patterns)
├── Cycle reports (`/tmp/eks-monitoring-reports/`)
├── Action audit logs (`/tmp/claude-k8s-agent-actions.log`)
├── Service mappings (`oncall/config/service_mapping.yaml`)
├── Alert rules (`oncall/config/k8s_monitoring.yaml`)
└── Team runbooks (probably in Confluence/Notion?)
```

**Opportunity:** Index this knowledge into RAG for instant retrieval.

---

## RAG Integration Options

### Option 1: mem0 Only (Easiest - Already Planned)

**What you get:**
- ✅ Managed service (no infrastructure)
- ✅ Automatic memory extraction
- ✅ Built-in categorization
- ✅ Python SDK (easy integration)
- ✅ **Already have implementation plans**

**Limitations:**
- ❌ Vendor lock-in
- ❌ Limited control over embeddings/search
- ❌ Cost at scale ($249/month for Pro)
- ❌ Can't query structured historical data easily

**Your existing plans:**
- `docs/implementations/mem0-k8s-monitor-implementation-plan.md` ✅
- `docs/implementations/mem0-oncall-implementation-plan.md` ✅

**Timeline:** 5-6 weeks (per your plan)

---

### Option 2: PostgreSQL/pgvector + MCP (DevOps-Friendly)

**What you get:**
- ✅ Self-hosted (full control)
- ✅ Integrates with existing RDS
- ✅ MCP server pattern (you already use MCP)
- ✅ No vendor lock-in
- ✅ SQL queries + vector search combined
- ✅ Cost-effective (just RDS + small compute)

**Architecture:**

```
┌────────────────────────────────────────────────────────────┐
│                PostgreSQL RDS (with pgvector)              │
│                                                            │
│  Tables:                                                   │
│  ├─ incidents (id, namespace, pod_name, root_cause, ...)  │
│  │   └─ embedding (vector(384))                           │
│  ├─ remediations (id, action, outcome, success, ...)      │
│  │   └─ embedding (vector(384))                           │
│  ├─ runbooks (id, title, content, ...)                    │
│  │   └─ embedding (vector(384))                           │
│  └─ deployments (id, service, pr_number, impact, ...)     │
│      └─ embedding (vector(384))                           │
└────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│              MCP Server: RAG Knowledge Base                │
│                                                            │
│  Tools exposed to Claude:                                  │
│  ├─ search_similar_incidents(query, namespace, limit)     │
│  ├─ search_runbooks(query, service, limit)                │
│  ├─ search_remediation_patterns(incident_type, limit)     │
│  ├─ search_deployment_history(service, limit)             │
│  └─ store_incident_analysis(namespace, pod, analysis, ...) │
└────────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────────┐
│              Ollama Embedding Service                      │
│              (CPU-only, all-MiniLM-L6-v2)                  │
│                                                            │
│  Deployment: K8s pod (2GB RAM, 1 CPU core)                │
│  Endpoint: http://ollama-embeddings:11434                 │
└────────────────────────────────────────────────────────────┘
```

**Implementation Complexity:** Medium
- Need to create MCP server (Python/TypeScript)
- Deploy Ollama for embeddings
- Create schema & indexing pipeline

**Timeline:** 2-3 weeks

---

### Option 3: Hybrid (mem0 + pgvector) - RECOMMENDED

**Why hybrid?**

| Knowledge Type | Storage | Reason |
|---------------|---------|--------|
| **Dynamic learnings** | mem0 | Auto-extraction, easy start |
| **Static runbooks** | pgvector | Structured search, version control |
| **Deployment logs** | pgvector | SQL queries + vector search |
| **Historical metrics** | pgvector | Time-series + semantic search |
| **Incident memories** | **Both** | mem0 for recent, pgvector for archive |

**Benefits:**
- ✅ Start fast with mem0 (your existing plans)
- ✅ Add pgvector later for long-term knowledge
- ✅ Best tool for each job
- ✅ No single vendor lock-in
- ✅ Cross-query both sources

**Example workflow:**

```python
# In your k8s-analyzer subagent
from src.memory.memory_manager import MemoryManager
from src.memory.pgvector_client import PGVectorClient

# 1. Search mem0 for recent incidents (fast, auto-extracted)
mem0 = MemoryManager(cluster_name="dev-eks")
recent_incidents = mem0.search_similar_incidents(
    namespace="proteus-dev",
    incident_type="OOMKilled",
    limit=5
)

# 2. Search pgvector for runbooks (structured, authoritative)
pgv = PGVectorClient()
runbooks = pgv.search_runbooks(
    query="proteus OOMKilled memory increase procedure",
    service="proteus",
    limit=3
)

# 3. Combine context for Claude
combined_context = f"""
**Recent Similar Incidents (from mem0):**
{format_mem0_memories(recent_incidents)}

**Relevant Runbooks (from pgvector):**
{format_pgvector_runbooks(runbooks)}
"""
```

**Timeline:** 3-4 weeks (mem0 first, then pgvector)

---

## Recommended Architecture

### Phase 1: Start with mem0 (Weeks 1-6)

**Use your existing plans:**

1. Implement `docs/implementations/mem0-k8s-monitor-implementation-plan.md`
2. Implement `docs/implementations/mem0-oncall-implementation-plan.md`
3. Get to production with mem0 only

**What you'll have:**
- ✅ Dynamic incident learning
- ✅ Remediation pattern memory
- ✅ Alert deduplication
- ✅ Cross-cycle knowledge

**Limitations you'll notice:**
- ❌ Can't easily search historical deployments by date range
- ❌ Runbooks not indexed (still in Confluence?)
- ❌ No structured queries (e.g., "all OOMKilled in Q4 2024")

---

### Phase 2: Add PostgreSQL/pgvector (Weeks 7-10)

**Goal:** Complement mem0 with structured, long-term knowledge

**Step 2.1: Set Up Infrastructure**

```bash
# 1. Enable pgvector on existing PostgreSQL
psql -h your-rds-endpoint.rds.amazonaws.com -U postgres
CREATE EXTENSION IF NOT EXISTS vector;

# 2. Deploy Ollama for embeddings
kubectl apply -f k8s/ollama-embeddings.yaml

# 3. Create RAG schema
psql -f sql/rag-schema.sql
```

**Step 2.2: Create MCP Server**

Create `mcp-rag-server/`:

```typescript
// src/index.ts - MCP RAG Server
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { Pool } from "pg";
import axios from "axios";

const pool = new Pool({
  host: process.env.POSTGRES_HOST,
  database: "rag_knowledge",
  user: process.env.POSTGRES_USER,
  password: process.env.POSTGRES_PASSWORD,
});

const OLLAMA_ENDPOINT = process.env.OLLAMA_ENDPOINT || "http://ollama-embeddings:11434";

async function getEmbedding(text: string): Promise<number[]> {
  const response = await axios.post(`${OLLAMA_ENDPOINT}/api/embeddings`, {
    model: "all-minilm",
    prompt: text,
  });
  return response.data.embedding;
}

// Tool: search_runbooks
server.setRequestHandler("tools/call", async (request) => {
  if (request.params.name === "search_runbooks") {
    const { query, limit = 5 } = request.params.arguments;

    // Generate embedding
    const queryEmbedding = await getEmbedding(query);

    // Vector search
    const result = await pool.query(`
      SELECT
        id,
        title,
        content,
        service,
        1 - (embedding <=> $1::vector) AS similarity
      FROM runbooks
      ORDER BY embedding <=> $1::vector
      LIMIT $2
    `, [JSON.stringify(queryEmbedding), limit]);

    return {
      content: [{
        type: "text",
        text: JSON.stringify(result.rows, null, 2)
      }]
    };
  }

  // Similar for other tools: search_incidents, search_remediations, etc.
});
```

**Step 2.3: Deploy MCP Server**

```yaml
# k8s/mcp-rag-server.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-rag-server
  namespace: monitoring
spec:
  replicas: 2
  selector:
    matchLabels:
      app: mcp-rag-server
  template:
    metadata:
      labels:
        app: mcp-rag-server
    spec:
      containers:
      - name: server
        image: your-registry/mcp-rag-server:v1.0.0
        ports:
        - containerPort: 3000
        env:
        - name: POSTGRES_HOST
          valueFrom:
            configMapKeyRef:
              name: rag-config
              key: postgres_host
        - name: OLLAMA_ENDPOINT
          value: "http://ollama-embeddings:11434"
        - name: POSTGRES_USER
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: postgres_user
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: rag-secrets
              key: postgres_password
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-rag-server
  namespace: monitoring
spec:
  ports:
  - port: 3000
    targetPort: 3000
  selector:
    app: mcp-rag-server
```

**Step 2.4: Integrate with k8s-monitor**

```markdown
# k8s-monitor/.claude/agents/k8s-analyzer.md

tools:
  - mcp__kubernetes__pods_list
  - mcp__kubernetes__events_list
  - mcp__rag__search_runbooks              # NEW
  - mcp__rag__search_incidents             # NEW
  - mcp__rag__search_remediation_patterns  # NEW

---

## RAG Integration

You now have TWO knowledge sources:

1. **mem0** - Recent dynamic learnings (last 90 days)
2. **pgvector** - Long-term structured knowledge (historical)

### Workflow for Analyzing New Incident:

1. Search **mem0** for similar recent incidents
2. Search **pgvector** for relevant runbooks
3. Combine both contexts
4. Store findings in **both** (mem0 auto-stores, pgvector manual)

### Example: OOMKilled Analysis

```python
# 1. mem0 - recent similar incidents
from src.memory.memory_manager import MemoryManager
memory = MemoryManager("dev-eks")
recent = memory.search_similar_incidents(
    namespace="proteus-dev",
    incident_type="OOMKilled",
    limit=3
)

# 2. pgvector - runbooks via MCP
runbooks = mcp__rag__search_runbooks(
    query="proteus memory optimization runbook",
    service="proteus",
    limit=2
)

# 3. Combine and analyze
context = f"""
**Recent Similar Incidents (mem0):**
{format_memories(recent)}

**Runbooks (pgvector):**
{format_runbooks(runbooks)}
"""

# 4. Store NEW finding
# mem0 auto-stores via MemoryManager
memory.store_incident_analysis(...)

# pgvector stores via MCP
mcp__rag__store_incident(
    namespace="proteus-dev",
    pod_name=pod_name,
    root_cause=identified_cause,
    analysis=full_analysis
)
```
```

---

### Phase 3: Build Shared Knowledge Infrastructure (Weeks 11-14)

**Goal:** All agents share a common knowledge base

```
┌──────────────────────────────────────────────────────────────┐
│              Shared RAG Knowledge Infrastructure             │
│                                                              │
│  mem0 (user_id=cluster_name):                               │
│  ├─ dev-eks memories (k8s-monitor + oncall shared)          │
│  └─ prod-eks memories (future)                              │
│                                                              │
│  PostgreSQL/pgvector (cluster_name table filter):           │
│  ├─ runbooks (service, title, content, embedding)           │
│  ├─ incidents (cluster, namespace, timestamp, embedding)    │
│  ├─ deployments (service, pr_number, commit, impact, ...)   │
│  └─ remediations (cluster, action, outcome, success, ...)   │
└──────────────────────────────────────────────────────────────┘
         │                                  │
         ▼                                  ▼
┌──────────────────────┐     ┌──────────────────────────┐
│   k8s-monitor        │     │   oncall-agent-api       │
│   (Agent SDK)        │     │   (Direct API)           │
│                      │     │                          │
│ Writes:              │     │ Writes:                  │
│ ├─ mem0 (auto)       │     │ ├─ mem0 (manual)         │
│ └─ pgvector (MCP)    │     │ └─ pgvector (direct SQL) │
│                      │     │                          │
│ Reads:               │     │ Reads:                   │
│ ├─ mem0 SDK          │     │ ├─ mem0 SDK              │
│ └─ MCP RAG server    │     │ └─ Direct pgvector query │
└──────────────────────┘     └──────────────────────────┘
```

**Cross-Agent Learning Example:**

```python
# Scenario: oncall-agent discovers a new deployment impact pattern

# oncall-agent (daemon mode) - stores discovery
from src.integrations.rag_client import RAGClient

rag = RAGClient(cluster_name="dev-eks")

# Store in pgvector (structured)
rag.store_deployment_impact(
    service="proteus",
    pr_number=789,
    commit_sha="abc123",
    impact="Caused 5 OOMKilled events within 30 minutes",
    namespace="proteus-dev",
    severity="high"
)

# Store in mem0 (dynamic)
from mem0 import MemoryClient
mem0 = MemoryClient(api_key=os.getenv("MEM0_API_KEY"))
mem0.add(
    messages=[{
        "role": "assistant",
        "content": f"Deployment PR#789 for proteus caused OOMKilled events. Memory config error."
    }],
    user_id="dev-eks",
    agent_id="oncall-daemon",
    metadata={"service": "proteus", "incident_type": "deployment_impact"}
)

# ---
# Later, k8s-monitor sees similar deployment issue

# k8s-analyzer subagent searches BOTH sources
memory_context = memory.search_deployment_impacts(service="proteus", limit=3)  # mem0
runbook_context = mcp__rag__search_deployments(query="proteus deployment issues", limit=3)  # pgvector

# Claude sees BOTH contexts:
"""
**Past Deployment Issues (mem0):**
- [2 days ago] PR#789 caused OOMKilled - memory config error

**Deployment History (pgvector - structured):**
- 2025-11-14: PR#789, commit abc123, impact: 5 OOMKilled events, severity: high
- 2025-11-01: PR#745, commit def456, impact: ImagePullBackOff, severity: medium
...
"""
```

---

## Implementation Strategies

### Strategy 1: Quick Win - mem0 for k8s-monitor (2 weeks)

**Just execute your existing plan:**
- `docs/implementations/mem0-k8s-monitor-implementation-plan.md`

**Deliverable:** k8s-monitor with adaptive memory

---

### Strategy 2: Full Hybrid (4-6 weeks)

**Week 1-2:** mem0 foundation
- Implement mem0-k8s-monitor (Phase 1-2)
- Implement mem0-oncall (orchestrator only)

**Week 3:** PostgreSQL setup
- Enable pgvector on RDS
- Deploy Ollama embeddings
- Create schema

**Week 4:** MCP RAG server
- Build TypeScript MCP server
- Implement search_runbooks, search_incidents tools
- Deploy to K8s

**Week 5:** Integration
- Update k8s-analyzer subagent to use MCP RAG
- Update oncall daemon to use pgvector directly
- Backfill runbooks from Confluence

**Week 6:** Testing & rollout
- E2E tests
- Production gradual rollout

---

### Strategy 3: Shared Knowledge First (pragmatic)

**Focus on high-value knowledge sharing:**

**Week 1:** Index critical runbooks
- Export Confluence runbooks to Markdown
- Generate embeddings with Ollama
- Store in pgvector

**Week 2:** Deploy MCP RAG server
- Simple read-only server
- Just `search_runbooks` tool initially

**Week 3:** Integrate with both agents
- k8s-monitor: Add MCP RAG to subagents
- oncall: Direct pgvector queries in orchestrator

**Week 4:** Add mem0 for dynamic learning
- Start with oncall (simpler integration)
- Then k8s-monitor

**Benefits:**
- ✅ High-value runbooks available FAST
- ✅ Both agents benefit immediately
- ✅ Add dynamic learning incrementally

---

## Shared Knowledge Infrastructure

### Database Schema (PostgreSQL with pgvector)

```sql
-- sql/rag-schema.sql

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Runbooks table
CREATE TABLE runbooks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    service TEXT,  -- proteus, hermes, etc.
    category TEXT,  -- incident_response, deployment, cost_optimization
    tags TEXT[],
    source TEXT,  -- confluence, github, manual
    source_url TEXT,
    embedding vector(384),  -- all-MiniLM-L6-v2 dimension
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Vector index for fast similarity search
CREATE INDEX runbooks_embedding_idx ON runbooks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Incidents table (long-term archive)
CREATE TABLE incidents (
    id SERIAL PRIMARY KEY,
    cluster_name TEXT NOT NULL,  -- dev-eks, prod-eks
    namespace TEXT NOT NULL,
    pod_name TEXT NOT NULL,
    service TEXT,
    incident_type TEXT NOT NULL,  -- OOMKilled, CrashLoopBackOff, etc.
    root_cause TEXT,
    analysis TEXT NOT NULL,
    severity TEXT,  -- critical, high, medium, low
    resolved BOOLEAN DEFAULT FALSE,
    embedding vector(384),
    occurred_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX incidents_embedding_idx ON incidents
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Composite index for filtering
CREATE INDEX incidents_cluster_ns_type_idx
ON incidents (cluster_name, namespace, incident_type, occurred_at DESC);

-- Remediations table
CREATE TABLE remediations (
    id SERIAL PRIMARY KEY,
    incident_id INTEGER REFERENCES incidents(id),
    cluster_name TEXT NOT NULL,
    namespace TEXT NOT NULL,
    service TEXT,
    action TEXT NOT NULL,  -- "Increased memory to 2Gi", "Rolling restart"
    outcome TEXT,
    success BOOLEAN NOT NULL,
    time_to_resolution_minutes INTEGER,
    embedding vector(384),
    performed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX remediations_embedding_idx ON remediations
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Deployments table
CREATE TABLE deployments (
    id SERIAL PRIMARY KEY,
    service TEXT NOT NULL,
    cluster_name TEXT NOT NULL,
    namespace TEXT,
    pr_number INTEGER,
    commit_sha TEXT NOT NULL,
    impact TEXT,  -- NULL if no impact, description if incidents followed
    severity TEXT,  -- NULL, low, medium, high, critical
    incidents_count INTEGER DEFAULT 0,
    embedding vector(384),
    deployed_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX deployments_embedding_idx ON deployments
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX deployments_service_time_idx
ON deployments (service, deployed_at DESC);
```

### Indexing Pipeline (Python)

```python
# scripts/index_knowledge.py
"""
One-time script to index existing knowledge into pgvector
Run after setting up schema
"""
import asyncio
import os
from pathlib import Path
import psycopg2
from psycopg2.extras import execute_values
import httpx
from typing import List, Dict
import json
import yaml

OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
POSTGRES_CONN = os.getenv("DATABASE_URL")

async def get_embedding(text: str) -> List[float]:
    """Generate embedding using Ollama"""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{OLLAMA_ENDPOINT}/api/embeddings",
            json={"model": "all-minilm", "prompt": text}
        )
        return response.json()["embedding"]

async def index_runbooks(runbooks_dir: Path):
    """Index Markdown runbooks from directory"""
    conn = psycopg2.connect(POSTGRES_CONN)
    cursor = conn.cursor()

    runbooks = []

    for md_file in runbooks_dir.glob("**/*.md"):
        # Parse frontmatter
        content = md_file.read_text()
        if content.startswith("---"):
            parts = content.split("---", 2)
            frontmatter = yaml.safe_load(parts[1])
            body = parts[2].strip()
        else:
            frontmatter = {}
            body = content

        # Generate embedding
        full_text = f"{frontmatter.get('title', md_file.stem)}\n\n{body}"
        embedding = await get_embedding(full_text)

        runbooks.append((
            frontmatter.get("title", md_file.stem),
            body,
            frontmatter.get("service"),
            frontmatter.get("category", "general"),
            frontmatter.get("tags", []),
            "filesystem",
            str(md_file),
            embedding
        ))

    # Bulk insert
    execute_values(
        cursor,
        """
        INSERT INTO runbooks
        (title, content, service, category, tags, source, source_url, embedding)
        VALUES %s
        """,
        runbooks
    )

    conn.commit()
    print(f"Indexed {len(runbooks)} runbooks")

async def index_historical_incidents(log_dir: Path):
    """Index past incidents from cycle reports"""
    conn = psycopg2.connect(POSTGRES_CONN)
    cursor = conn.cursor()

    incidents = []

    for report_file in log_dir.glob("**/cycle-report-*.json"):
        report = json.loads(report_file.read_text())

        for incident in report.get("incidents", []):
            analysis_text = f"{incident.get('incident_type')} in {incident.get('namespace')}/{incident.get('pod_name')}\n\n{incident.get('analysis', '')}"
            embedding = await get_embedding(analysis_text)

            incidents.append((
                incident.get("cluster", "dev-eks"),
                incident.get("namespace"),
                incident.get("pod_name"),
                incident.get("service"),
                incident.get("incident_type"),
                incident.get("root_cause"),
                incident.get("analysis"),
                incident.get("severity"),
                incident.get("resolved", False),
                embedding,
                incident.get("occurred_at")
            ))

    execute_values(
        cursor,
        """
        INSERT INTO incidents
        (cluster_name, namespace, pod_name, service, incident_type, root_cause,
         analysis, severity, resolved, embedding, occurred_at)
        VALUES %s
        """,
        incidents
    )

    conn.commit()
    print(f"Indexed {len(incidents)} historical incidents")

async def main():
    """Index all knowledge"""
    print("Starting knowledge indexing...")

    # Index runbooks from docs/runbooks/
    await index_runbooks(Path("docs/runbooks"))

    # Index historical incidents from logs
    await index_historical_incidents(Path("/tmp/eks-monitoring-reports"))

    print("✅ Knowledge indexing complete!")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Deployment Examples

### Example 1: Ollama Embeddings (Kubernetes)

```yaml
# k8s/ollama-embeddings.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama-embeddings
  namespace: monitoring
spec:
  replicas: 2
  selector:
    matchLabels:
      app: ollama-embeddings
  template:
    metadata:
      labels:
        app: ollama-embeddings
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest
        ports:
        - containerPort: 11434
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        command:
        - /bin/sh
        - -c
        - |
          ollama serve &
          sleep 5
          ollama pull all-minilm
          wait
        volumeMounts:
        - name: models
          mountPath: /root/.ollama
      volumes:
      - name: models
        persistentVolumeClaim:
          claimName: ollama-models
---
apiVersion: v1
kind: Service
metadata:
  name: ollama-embeddings
  namespace: monitoring
spec:
  ports:
  - port: 11434
    targetPort: 11434
  selector:
    app: ollama-embeddings
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ollama-models
  namespace: monitoring
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
```

### Example 2: MCP RAG Server (Docker Compose for local dev)

```yaml
# docker-compose.rag.yml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: rag_knowledge
      POSTGRES_USER: rag_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./sql/rag-schema.sql:/docker-entrypoint-initdb.d/01-schema.sql

  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_models:/root/.ollama
    command: >
      sh -c "ollama serve & sleep 5 && ollama pull all-minilm && wait"

  mcp-rag-server:
    build: ./mcp-rag-server
    ports:
      - "3000:3000"
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_DB: rag_knowledge
      POSTGRES_USER: rag_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      OLLAMA_ENDPOINT: http://ollama:11434
    depends_on:
      - postgres
      - ollama

  # Your k8s-monitor agent can connect to mcp-rag-server:3000
  k8s-monitor:
    build: ./k8s-monitor
    environment:
      MEM0_API_KEY: ${MEM0_API_KEY}
      MCP_RAG_SERVER: http://mcp-rag-server:3000
    depends_on:
      - mcp-rag-server

volumes:
  postgres_data:
  ollama_models:
```

### Example 3: Using Both RAG Sources in k8s-analyzer

```python
# k8s-monitor/src/orchestrator/enhanced_analyzer.py
"""
Enhanced k8s-analyzer that uses BOTH mem0 and pgvector
"""
import asyncio
from src.memory.memory_manager import MemoryManager
from src.memory.pgvector_client import PGVectorClient

class EnhancedKubernetesAnalyzer:
    def __init__(self, cluster_name: str):
        self.cluster_name = cluster_name

        # mem0 for dynamic learnings
        self.mem0 = MemoryManager(cluster_name=cluster_name)

        # pgvector for structured knowledge
        self.pgv = PGVectorClient(cluster_name=cluster_name)

    async def analyze_oom_incident(
        self,
        namespace: str,
        pod_name: str,
        service: str
    ) -> Dict[str, Any]:
        """
        Analyze OOMKilled incident using BOTH knowledge sources
        """

        # 1. Search mem0 for recent similar incidents (fast, recent)
        recent_incidents = self.mem0.search_similar_incidents(
            namespace=namespace,
            incident_type="OOMKilled",
            service=service,
            limit=3
        )

        # 2. Search pgvector for historical patterns (structured, deep)
        historical = await self.pgv.search_similar_incidents(
            query=f"{service} OOMKilled memory pressure",
            cluster=self.cluster_name,
            namespace=namespace,
            incident_type="OOMKilled",
            limit=5
        )

        # 3. Search pgvector for runbooks (authoritative)
        runbooks = await self.pgv.search_runbooks(
            query=f"{service} memory optimization procedure",
            service=service,
            limit=2
        )

        # 4. Search pgvector for successful remediations
        remediations = await self.pgv.search_successful_remediations(
            incident_type="OOMKilled",
            service=service,
            limit=3
        )

        # 5. Combine ALL contexts for Claude
        combined_context = self._build_rich_context(
            recent_incidents,
            historical,
            runbooks,
            remediations
        )

        # 6. Claude analyzes with FULL context
        analysis = await self._call_claude_with_context(
            namespace=namespace,
            pod_name=pod_name,
            context=combined_context
        )

        # 7. Store findings in BOTH sources
        # mem0 (automatic via MemoryManager)
        self.mem0.store_incident_analysis(
            namespace=namespace,
            pod_name=pod_name,
            incident_type="OOMKilled",
            analysis=analysis["full_text"],
            severity=analysis["severity"],
            root_cause=analysis["root_cause"],
            service=service
        )

        # pgvector (manual, structured)
        await self.pgv.store_incident(
            cluster_name=self.cluster_name,
            namespace=namespace,
            pod_name=pod_name,
            service=service,
            incident_type="OOMKilled",
            root_cause=analysis["root_cause"],
            analysis=analysis["full_text"],
            severity=analysis["severity"]
        )

        return analysis

    def _build_rich_context(
        self,
        recent: List[Dict],
        historical: List[Dict],
        runbooks: List[Dict],
        remediations: List[Dict]
    ) -> str:
        """Build comprehensive context from all sources"""

        context_parts = []

        # Recent learnings from mem0
        if recent:
            context_parts.append("## Recent Similar Incidents (mem0 - last 90 days):")
            context_parts.append(self.mem0.format_memories_as_context(recent))

        # Historical patterns from pgvector
        if historical:
            context_parts.append("\n## Historical Incident Patterns (pgvector - all time):")
            for inc in historical:
                context_parts.append(f"- [{inc['occurred_at']}] {inc['namespace']}: {inc['root_cause']} (severity: {inc['severity']})")

        # Runbooks from pgvector
        if runbooks:
            context_parts.append("\n## Relevant Runbooks:")
            for rb in runbooks:
                context_parts.append(f"### {rb['title']}")
                context_parts.append(rb['content'][:500] + "...")

        # Successful remediations
        if remediations:
            context_parts.append("\n## Successful Past Remediations:")
            for rem in remediations:
                context_parts.append(
                    f"- {rem['action']} → {rem['outcome']} "
                    f"(resolved in {rem['time_to_resolution_minutes']} min)"
                )

        return "\n".join(context_parts)
```

---

## Cost & Performance Analysis

### mem0 Costs

| Tier | Memories | Monthly Cost | Your Estimate |
|------|----------|--------------|---------------|
| **Free** | 10,000 | $0 | ✅ Sufficient for 1-2 clusters (6 months) |
| **Pro** | Unlimited | $249 | Needed after 10K memories (~Month 6) |

**Your projected usage (2 clusters, 20 namespaces):**
- Incidents: ~50/week = 200/month = 2,400/year
- Remediations: ~20/week = 80/month = 960/year
- Cost insights: ~10/week = 40/month = 480/year
- **Total:** ~3,840 memories/year

**Result:** Free tier sufficient for ~2.5 years

---

### PostgreSQL/pgvector Costs

| Component | Instance Type | Monthly Cost (AWS us-east-1) |
|-----------|---------------|------------------------------|
| **RDS PostgreSQL** | db.t4g.small (2GB) | ~$30 |
| **Storage** | 100GB GP3 | ~$12 |
| **Ollama (EKS)** | 1 pod (2GB RAM, 1 CPU) | ~$15 |
| **MCP Server (EKS)** | 2 pods (1GB RAM each) | ~$15 |
| **Total** | | **~$72/month** |

**Cheaper alternative (self-hosted):**
- PostgreSQL on EKS: Free (use existing nodes)
- Ollama on EKS: ~$15
- MCP Server on EKS: ~$15
- **Total:** **~$30/month**

---

### Hybrid Total Cost

| Component | Monthly Cost |
|-----------|--------------|
| mem0 (Free tier) | $0 |
| PostgreSQL/pgvector (RDS) | $42 |
| Ollama embeddings (EKS) | $15 |
| MCP RAG server (EKS) | $15 |
| **Total** | **$72/month** |

**vs. mem0 Pro only:** $249/month
**Savings:** $177/month ($2,124/year)

---

### Performance Comparison

| Metric | mem0 | PostgreSQL/pgvector | Hybrid |
|--------|------|---------------------|--------|
| **Search latency** | ~100-300ms | ~50-150ms (local) | 100-300ms |
| **Structured queries** | ❌ Not supported | ✅ SQL + vector | ✅ Both |
| **Auto-extraction** | ✅ Built-in | ❌ Manual | ✅ mem0 handles |
| **Historical depth** | 90 days (configurable) | Unlimited | Unlimited |
| **Cross-agent sharing** | ✅ Via user_id | ✅ Via cluster_name | ✅ Both |

---

## Migration Path

### Timeline: 10-Week Rollout

**Weeks 1-2: mem0 Foundation (k8s-monitor)**
- ✅ Implement mem0-k8s-monitor Phase 1-2
- ✅ Get k8s-analyzer, github-reviewer, slack-notifier using mem0
- ✅ Deploy to dev-eks
- **Deliverable:** k8s-monitor with dynamic memory

**Weeks 3-4: mem0 for oncall**
- ✅ Implement mem0-oncall (orchestrator only)
- ✅ Deploy to dev-eks
- **Deliverable:** Both agents using mem0

**Week 5: PostgreSQL Setup**
- ✅ Enable pgvector on RDS
- ✅ Deploy Ollama embeddings to EKS
- ✅ Create schema
- ✅ Index first 50 runbooks from Confluence export
- **Deliverable:** RAG infrastructure ready

**Week 6-7: MCP RAG Server**
- ✅ Build TypeScript MCP server
- ✅ Implement search_runbooks, search_incidents tools
- ✅ Deploy to EKS
- ✅ Test locally with k8s-monitor
- **Deliverable:** MCP RAG server operational

**Week 8: Integration**
- ✅ Update k8s-analyzer to use MCP RAG (add to tools list)
- ✅ Update oncall orchestrator to query pgvector directly
- ✅ Backfill last 90 days of incidents into pgvector
- **Deliverable:** Hybrid RAG working

**Week 9: Testing**
- ✅ E2E tests (both agents use both sources)
- ✅ Performance benchmarks
- ✅ Cost validation
- **Deliverable:** Production-ready

**Week 10: Production Rollout**
- ✅ Gradual rollout (feature flags)
- ✅ Monitor metrics
- ✅ Documentation updates
- **Deliverable:** Hybrid RAG in production

---

## Next Steps

### Immediate Actions (This Week)

1. **Decide on approach:**
   - [ ] mem0 only (fast, managed) → Follow existing plans
   - [ ] Hybrid (recommended) → This guide
   - [ ] pgvector only (self-hosted) → More work upfront

2. **If choosing hybrid:**
   - [ ] Start with mem0 implementation (Week 1-2)
   - [ ] Order RDS PostgreSQL (or check existing)
   - [ ] Export 10-20 runbooks from Confluence to Markdown

3. **Set up infrastructure:**
   - [ ] Enable pgvector: `CREATE EXTENSION vector;`
   - [ ] Deploy Ollama to EKS: `kubectl apply -f k8s/ollama-embeddings.yaml`
   - [ ] Create rag-knowledge database

### Month 1 Goals

- [ ] k8s-monitor using mem0 (dynamic learning)
- [ ] oncall-agent using mem0 (incident correlation)
- [ ] PostgreSQL/pgvector ready (schema created)
- [ ] First 50 runbooks indexed

### Month 2 Goals

- [ ] MCP RAG server deployed
- [ ] k8s-monitor using both mem0 + pgvector
- [ ] oncall using both sources
- [ ] Historical incidents backfilled (90 days)

### Month 3 Goals

- [ ] Both agents fully hybrid
- [ ] Metrics dashboard (memory usage, search latency)
- [ ] Runbook maintenance process
- [ ] Cost tracking

---

## Appendix: Code Templates

### A. pgvector Client (Python)

```python
# k8s-monitor/src/memory/pgvector_client.py
"""
PostgreSQL/pgvector client for structured RAG queries
Complements mem0 with long-term, structured knowledge
"""
import asyncio
import os
import asyncpg
import httpx
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class PGVectorClient:
    """Client for PostgreSQL/pgvector RAG knowledge base"""

    def __init__(self, cluster_name: str):
        self.cluster_name = cluster_name
        self.db_url = os.getenv("RAG_DATABASE_URL")
        self.ollama_endpoint = os.getenv("OLLAMA_ENDPOINT", "http://ollama-embeddings:11434")
        self.pool = None

    async def _get_pool(self):
        """Get connection pool (lazy initialization)"""
        if not self.pool:
            self.pool = await asyncpg.create_pool(self.db_url, min_size=2, max_size=10)
        return self.pool

    async def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding using Ollama"""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.ollama_endpoint}/api/embeddings",
                json={"model": "all-minilm", "prompt": text}
            )
            return response.json()["embedding"]

    async def search_runbooks(
        self,
        query: str,
        service: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict]:
        """
        Search for relevant runbooks

        Args:
            query: Search query
            service: Optional service filter
            limit: Max results

        Returns:
            List of runbook dicts
        """
        pool = await self._get_pool()
        embedding = await self._get_embedding(query)

        if service:
            sql = """
                SELECT
                    id, title, content, service, category, tags,
                    1 - (embedding <=> $1::vector) AS similarity
                FROM runbooks
                WHERE service = $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3
            """
            rows = await pool.fetch(sql, embedding, service, limit)
        else:
            sql = """
                SELECT
                    id, title, content, service, category, tags,
                    1 - (embedding <=> $1::vector) AS similarity
                FROM runbooks
                ORDER BY embedding <=> $1::vector
                LIMIT $2
            """
            rows = await pool.fetch(sql, embedding, limit)

        return [dict(row) for row in rows]

    async def search_similar_incidents(
        self,
        query: str,
        cluster: Optional[str] = None,
        namespace: Optional[str] = None,
        incident_type: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict]:
        """Search historical incidents"""
        pool = await self._get_pool()
        embedding = await self._get_embedding(query)

        # Build dynamic WHERE clause
        where_clauses = []
        params = [embedding, limit]
        param_idx = 3

        if cluster:
            where_clauses.append(f"cluster_name = ${param_idx}")
            params.insert(param_idx - 1, cluster)
            param_idx += 1

        if namespace:
            where_clauses.append(f"namespace = ${param_idx}")
            params.insert(param_idx - 1, namespace)
            param_idx += 1

        if incident_type:
            where_clauses.append(f"incident_type = ${param_idx}")
            params.insert(param_idx - 1, incident_type)
            param_idx += 1

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        sql = f"""
            SELECT
                id, cluster_name, namespace, pod_name, service,
                incident_type, root_cause, analysis, severity,
                occurred_at,
                1 - (embedding <=> $1::vector) AS similarity
            FROM incidents
            {where_sql}
            ORDER BY embedding <=> $1::vector
            LIMIT $2
        """

        rows = await pool.fetch(sql, *params)
        return [dict(row) for row in rows]

    async def search_successful_remediations(
        self,
        incident_type: str,
        service: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict]:
        """Search for successful remediation patterns"""
        pool = await self._get_pool()

        # Get recent successful remediations (no embedding, just filter)
        if service:
            sql = """
                SELECT r.*, i.incident_type
                FROM remediations r
                JOIN incidents i ON r.incident_id = i.id
                WHERE r.success = true
                  AND i.incident_type = $1
                  AND r.service = $2
                ORDER BY r.performed_at DESC
                LIMIT $3
            """
            rows = await pool.fetch(sql, incident_type, service, limit)
        else:
            sql = """
                SELECT r.*, i.incident_type
                FROM remediations r
                JOIN incidents i ON r.incident_id = i.id
                WHERE r.success = true
                  AND i.incident_type = $1
                ORDER BY r.performed_at DESC
                LIMIT $2
            """
            rows = await pool.fetch(sql, incident_type, limit)

        return [dict(row) for row in rows]

    async def store_incident(
        self,
        cluster_name: str,
        namespace: str,
        pod_name: str,
        service: str,
        incident_type: str,
        root_cause: Optional[str],
        analysis: str,
        severity: str
    ) -> int:
        """Store new incident"""
        pool = await self._get_pool()

        # Generate embedding
        analysis_text = f"{incident_type} in {namespace}/{pod_name}: {analysis}"
        embedding = await self._get_embedding(analysis_text)

        row = await pool.fetchrow(
            """
            INSERT INTO incidents
            (cluster_name, namespace, pod_name, service, incident_type,
             root_cause, analysis, severity, embedding, occurred_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector, NOW())
            RETURNING id
            """,
            cluster_name, namespace, pod_name, service, incident_type,
            root_cause, analysis, severity, embedding
        )

        logger.info(f"Stored incident {row['id']} in pgvector")
        return row['id']
```

---

## Summary

**You're in a great position to leverage RAG with your existing agents:**

1. **✅ You have two production agents** (k8s-monitor, oncall)
2. **✅ You have comprehensive mem0 plans** (ready to execute)
3. **✅ You have MCP experience** (already using 3 MCP servers)
4. **✅ You have valuable un-indexed knowledge** (Jira, GitHub, logs, runbooks)

**Recommended path:**

1. **Start with mem0** (Weeks 1-4) - Execute your existing plans
2. **Add PostgreSQL/pgvector** (Weeks 5-7) - Build shared knowledge base
3. **Deploy MCP RAG server** (Weeks 8-9) - Unified access for both agents
4. **Test & rollout** (Week 10) - Production deployment

**Expected outcomes:**

- ✅ 70% of recurring incidents auto-detected
- ✅ 40% reduction in duplicate Jira comments
- ✅ Runbooks instantly searchable by both agents
- ✅ Deployment impact automatically correlated
- ✅ Cost: ~$72/month (vs $249 for mem0 Pro)
- ✅ Full control + flexibility

**Next step:** Pick your approach and start Week 1! 🚀
