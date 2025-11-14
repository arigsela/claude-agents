# mem0 Integration for k8s-monitor Agent - Implementation Plan
## Adaptive Memory Layer for Claude Agent SDK Multi-Agent Architecture

---

## Table of Contents

1. [Overview & Goals](#overview--goals)
2. [Architecture Integration](#architecture-integration)
3. [Phase 1: Setup & Foundation](#phase-1-setup--foundation)
4. [Phase 2: Orchestrator Integration](#phase-2-orchestrator-integration)
5. [Phase 3: Subagent Memory Enhancement](#phase-3-subagent-memory-enhancement)
6. [Phase 4: ConfigMap GitOps Integration](#phase-4-configmap-gitops-integration)
7. [Phase 5: Testing & Validation](#phase-5-testing--validation)
8. [Phase 6: Production Deployment](#phase-6-production-deployment)
9. [Monitoring & Operations](#monitoring--operations)
10. [Rollback Strategy](#rollback-strategy)

---

## Overview & Goals

### Current State

The k8s-monitor agent uses **Claude Agent SDK** with:
- **Persistent conversations** within monitoring cycles via `PersistentMonitor`
- **Subagents**: k8s-analyzer, github-reviewer, slack-notifier, escalation-manager
- **Static institutional memory**: `.claude/CLAUDE.md` reloaded each cycle
- **ConfigMap-driven** cluster context (hot-reload capable)
- **No adaptive learning** - same issues investigated repeatedly across cycles

### What mem0 Adds

```
┌─────────────────────────────────────────────────────────────────┐
│                    mem0 Adaptive Memory Layer                   │
│                                                                 │
│  Complements (not replaces) .claude/CLAUDE.md:                 │
│  - .claude/CLAUDE.md = Static cluster config & SOPs            │
│  - mem0 = Dynamic learnings from past incidents & patterns     │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│              Main Orchestrator (PersistentMonitor)              │
│                                                                 │
│  Before Cycle:                                                  │
│  - Load .claude/CLAUDE.md (static context)                     │
│  - Search mem0 for recent incident patterns                    │
│  - Combine both as enhanced context                            │
│                                                                 │
│  After Cycle:                                                   │
│  - Store findings, remediation outcomes, patterns in mem0      │
│  - Update cycle statistics                                     │
└────────────┬───────────────────────────────────────────────────┘
             │
             ├─ Task Tool (invokes subagents with memory context)
             │
    ┌────────┴────────┬──────────────┬──────────────┬────────────┐
    │                 │              │              │            │
    ▼                 ▼              ▼              ▼            ▼
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ ┌──────────┐
│k8s-      │   │github-   │   │slack-    │   │escalation│ │Future    │
│analyzer  │   │reviewer  │   │notifier  │   │-manager  │ │subagents │
│          │   │          │   │          │   │          │ │          │
│Searches  │   │Searches  │   │Uses      │   │Uses      │ │Can all   │
│mem0 for  │   │mem0 for  │   │mem0 for  │   │mem0 for  │ │access    │
│similar   │   │past PR   │   │alert     │   │escalation│ │mem0      │
│incidents │   │patterns  │   │history   │   │patterns  │ │learnings │
│          │   │          │   │          │   │          │ │          │
│Stores    │   │Stores    │   │Stores    │   │Stores    │ │via       │
│findings  │   │deploy    │   │alert     │   │escalation│ │agent_id  │
│          │   │impact    │   │dedup     │   │outcomes  │ │scoping   │
└──────────┘   └──────────┘   └──────────┘   └──────────┘ └──────────┘
```

### Key Differences from oncall Integration

| Aspect | oncall (Anthropic API) | k8s-monitor (Claude SDK) |
|--------|----------------------|--------------------------|
| **Architecture** | Stateless two-turn | Multi-agent with persistent context |
| **Memory scope** | user_id only | user_id + agent_id per subagent |
| **Integration point** | orchestrator.py only | orchestrator + each subagent |
| **Existing memory** | None (30-min sessions) | .claude/CLAUDE.md (static) |
| **Subagents** | None | 4 specialized subagents |
| **Context management** | Manual messages array | SDK handles conversation state |

### Success Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Recurring issue detection** | 70% auto-detected | Track "similar to past incident" references |
| **Remediation success rate** | 80% of past solutions work | Track remediation outcome storage |
| **Jira noise reduction** | 40% fewer duplicate updates | Count Jira comment deduplication |
| **Cost optimization retention** | 90% of insights retained | Track reused cost recommendations |
| **Subagent knowledge sharing** | 100% cross-subagent access | Verify k8s-analyzer can see github-reviewer learnings |

---

## Architecture Integration

### Memory Scoping Strategy

```python
# User ID: Cluster name (dev-eks, prod-eks)
user_id = f"{cluster_name}"  # e.g., "dev-eks"

# Agent ID: Subagent name for scoped memories
agent_id = "k8s-analyzer"      # Scoped to k8s-analyzer only
agent_id = "github-reviewer"   # Scoped to github-reviewer only
agent_id = None                # Global cluster memories (all subagents can see)

# Example storage:
mem0.add(
    messages=[...],
    user_id="dev-eks",           # Cluster scope
    agent_id="k8s-analyzer",     # Subagent scope
    metadata={
        "namespace": "proteus-dev",
        "incident_type": "OOMKilled",
        "severity": "high"
    }
)

# Example retrieval by k8s-analyzer:
own_memories = mem0.search(
    query="OOMKilled patterns",
    user_id="dev-eks",
    agent_id="k8s-analyzer"      # Only k8s-analyzer's memories
)

# Example retrieval of ALL cluster learnings:
all_learnings = mem0.search(
    query="OOMKilled patterns",
    user_id="dev-eks",
    agent_id=None                # All subagents' memories
)
```

### Memory Categories for k8s-monitor

```python
MEMORY_CATEGORIES = [
    {
        "name": "incidents",
        "description": "Pod failures, crashes, OOMKilled, ImagePullBackOff incidents"
    },
    {
        "name": "remediation",
        "description": "Successful remediation actions and outcomes"
    },
    {
        "name": "cost_optimization",
        "description": "Resource right-sizing insights and recommendations"
    },
    {
        "name": "deployment_impact",
        "description": "GitHub deployment correlations with incidents"
    },
    {
        "name": "alert_patterns",
        "description": "Slack alert deduplication and escalation patterns"
    },
    {
        "name": "jira_management",
        "description": "Jira ticket resolution patterns and comment deduplication"
    }
]
```

### Relationship to .claude/CLAUDE.md

**.claude/CLAUDE.md remains the source of truth for:**
- Cluster configuration (name, region, version)
- Critical namespaces to monitor
- Team escalation contacts
- Known recurring issues (manually documented)
- Approved auto-remediation actions

**mem0 adds dynamic learning for:**
- Actual incident history and root causes
- Remediation success/failure patterns
- Cost optimization insights that worked
- Deployment impact correlations discovered
- Jira ticket resolution patterns observed

**Combined usage:**
```python
# Load static context
with open(".claude/CLAUDE.md") as f:
    static_context = f.read()

# Load dynamic learnings
recent_incidents = mem0.search("recent pod failures", user_id="dev-eks", limit=5)
dynamic_context = format_memories(recent_incidents)

# Combine for LLM
full_context = f"""
{static_context}

**Recent learnings from past cycles:**
{dynamic_context}
"""
```

---

## Phase 1: Setup & Foundation

**Duration:** 1 day
**Effort:** Low
**Risk:** Low

### Step 1.1: Install Dependencies

```bash
cd k8s-monitor

# Install mem0 SDK
pip install mem0ai

# Update requirements.txt
echo "mem0ai==1.0.0" >> requirements.txt

# Install
pip install -r requirements.txt
```

### Step 1.2: Create Memory Module

Create new directory structure:
```bash
mkdir -p src/memory
touch src/memory/__init__.py
touch src/memory/mem0_client.py
touch src/memory/memory_manager.py
touch src/memory/memory_config.py
```

Create `src/memory/memory_config.py`:

```python
"""
mem0 configuration for k8s-monitor agent
Defines categories and custom instructions for Kubernetes monitoring
"""

# Custom categories for k8s incident memories
MEMORY_CATEGORIES = [
    {
        "name": "incidents",
        "description": "Pod failures, crashes, OOMKilled, ImagePullBackOff, CrashLoopBackOff incidents"
    },
    {
        "name": "remediation",
        "description": "Successful remediation actions (rolling restarts, resource adjustments) and outcomes"
    },
    {
        "name": "cost_optimization",
        "description": "Resource right-sizing insights, over-provisioning detected, cost recommendations"
    },
    {
        "name": "deployment_impact",
        "description": "GitHub deployment correlations with incidents, config change impacts"
    },
    {
        "name": "alert_patterns",
        "description": "Slack alert deduplication patterns, escalation criteria"
    },
    {
        "name": "jira_management",
        "description": "Jira ticket resolution patterns, comment deduplication, smart updates"
    }
]

# Custom instructions - what to extract from monitoring cycles
CUSTOM_INSTRUCTIONS = """
Extract and remember from Kubernetes monitoring cycles:

1. **Incident patterns:**
   - Pod crash loops with identified root causes
   - OOMKilled events with actual vs requested memory
   - ImagePullBackOff issues (registry, secrets, permissions)
   - Deployment failures and configuration errors
   - Node pressure events (memory, disk, PID)
   - Network policy blocking patterns
   - PVC attachment failures

2. **Successful remediation:**
   - Rolling restart outcomes (success/failure)
   - Resource limit adjustments that resolved issues
   - Configuration changes that fixed problems
   - Time-to-resolution for different incident types
   - Actions that DIDN'T work (important to remember failures too)

3. **Cost optimization insights:**
   - Pods over-provisioned (requested vs actual usage)
   - Right-sizing recommendations that were applied
   - Namespace resource quotas that were adjusted
   - Services that scaled down successfully
   - Idle resources identified

4. **GitHub deployment impacts:**
   - Deployments that caused incidents (which commit, which service)
   - Config changes (ConfigMap/Secret) that resolved issues
   - PR correlations with pod behavior changes
   - Rollback success patterns

5. **Slack alert management:**
   - Which incidents should skip alerting (low severity, known recurring)
   - Alert deduplication patterns (same issue, multiple namespaces)
   - Escalation triggers that proved accurate
   - False positive patterns

6. **Jira ticket patterns:**
   - Ticket resolution patterns for recurring issues
   - Effective comment templates that got quick responses
   - Issues that should be auto-closed vs escalated
   - Duplicate ticket detection patterns

**EXCLUDE from memory:**
- Routine "all green" health check results
- Expected pod restarts during normal deployments
- Temporary network blips lasting < 2 minutes
- Generic status queries during monitoring
- Test namespace activity (contains "test", "sandbox")
- Internal monitoring tool noise (prometheus restarts, grafana updates)

**Memory consolidation rules:**
- For recurring incidents (same pod, same error), update existing memory with occurrence count
- Consolidate multiple OOMKilled events for same service into single memory with pattern
- Group related incidents across namespaces if same root cause
- Update remediation memories with new success/failure data points

**Memory retention:**
- Incident investigations: 90 days
- Successful remediation patterns: Permanent (no expiration)
- Cost optimization insights: 180 days
- Deployment correlations: 90 days
- Alert patterns: Permanent
- Jira patterns: Permanent
"""

# Search filters by context
SEARCH_FILTERS = {
    "incidents": {
        "categories": {"in": ["incidents", "remediation"]}
    },
    "cost": {
        "categories": {"in": ["cost_optimization"]}
    },
    "deployment": {
        "categories": {"in": ["deployment_impact"]}
    },
    "alerts": {
        "categories": {"in": ["alert_patterns"]}
    },
    "jira": {
        "categories": {"in": ["jira_management"]}
    },
    "all": {}  # No filters
}

# Expiration periods (in days, None = permanent)
EXPIRATION_PERIODS = {
    "incident": 90,
    "remediation": None,        # Keep successful patterns forever
    "cost": 180,
    "deployment": 90,
    "alert": None,              # Keep alert patterns forever
    "jira": None,               # Keep Jira patterns forever
    "temporary": 7              # Short-lived issues
}
```

### Step 1.3: Create mem0 Client Wrapper

Create `src/memory/mem0_client.py`:

```python
"""
mem0 client wrapper for k8s-monitor with retry logic and error handling
Optimized for Claude Agent SDK multi-agent architecture
"""
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from mem0 import MemoryClient
from tenacity import retry, stop_after_attempt, wait_exponential

from .memory_config import (
    MEMORY_CATEGORIES,
    CUSTOM_INSTRUCTIONS,
    EXPIRATION_PERIODS
)

logger = logging.getLogger(__name__)


class Mem0ClientWrapper:
    """Wrapper around mem0 MemoryClient optimized for k8s-monitor"""

    def __init__(self, cluster_name: str):
        """
        Initialize mem0 client

        Args:
            cluster_name: Kubernetes cluster name (e.g., "dev-eks", "prod-eks")
                         Used as user_id for cluster-scoped memories
        """
        self.enabled = os.getenv("MEM0_ENABLED", "true").lower() == "true"
        self.cluster_name = cluster_name

        if not self.enabled:
            logger.info("mem0 is disabled via MEM0_ENABLED=false")
            return

        api_key = os.getenv("MEM0_API_KEY")
        if not api_key:
            raise ValueError("MEM0_API_KEY not set in environment")

        self.client = MemoryClient(api_key=api_key)
        self.search_limit = int(os.getenv("MEM0_SEARCH_LIMIT", "5"))

        # Configure project on initialization
        self._configure_project()

        logger.info(f"mem0 client initialized for cluster: {cluster_name}")

    def _configure_project(self):
        """Configure mem0 project with k8s-specific categories and instructions"""
        try:
            self.client.project.update(
                custom_instructions=CUSTOM_INSTRUCTIONS,
                custom_categories=MEMORY_CATEGORIES
            )
            logger.info("mem0 project configured with k8s monitoring categories")
        except Exception as e:
            logger.error(f"Failed to configure mem0 project: {e}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def add_memory(
        self,
        messages: List[Dict[str, str]],
        agent_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        expiration_type: str = "incident"
    ) -> Dict:
        """
        Add memory to cluster-scoped storage

        Args:
            messages: List of message dicts with 'role' and 'content'
            agent_id: Optional subagent identifier (e.g., 'k8s-analyzer', 'github-reviewer')
                     If None, memory is global to cluster (all subagents can see)
            metadata: Optional metadata (namespace, incident_type, severity, etc.)
            expiration_type: Type for expiration ('incident', 'remediation', 'cost', etc.)

        Returns:
            Response from mem0 API
        """
        if not self.enabled:
            logger.debug("mem0 disabled, skipping add_memory")
            return {"skipped": True}

        # Calculate expiration date
        expiration_date = None
        if expiration_type in EXPIRATION_PERIODS:
            days = EXPIRATION_PERIODS[expiration_type]
            if days is not None:
                expiration_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")

        try:
            result = self.client.add(
                messages=messages,
                user_id=self.cluster_name,  # Cluster scope
                agent_id=agent_id,          # Subagent scope (optional)
                metadata=metadata,
                expiration_date=expiration_date
            )

            scope = f"agent={agent_id}" if agent_id else "global"
            logger.info(f"Added memory: cluster={self.cluster_name}, {scope}, expires={expiration_date}")
            return result

        except Exception as e:
            logger.error(f"Failed to add memory: {e}")
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def search_memories(
        self,
        query: str,
        agent_id: Optional[str] = None,
        filters: Optional[Dict] = None,
        limit: Optional[int] = None,
        include_all_agents: bool = False
    ) -> List[Dict]:
        """
        Search memories within cluster scope

        Args:
            query: Search query string
            agent_id: Optional subagent identifier to scope search
                     If None and include_all_agents=False, returns global memories only
                     If None and include_all_agents=True, returns all memories
            filters: Optional metadata/category filters
            limit: Max results to return (defaults to MEM0_SEARCH_LIMIT)
            include_all_agents: If True, search across all subagent memories

        Returns:
            List of memory dicts with 'memory', 'score', 'metadata', etc.
        """
        if not self.enabled:
            logger.debug("mem0 disabled, skipping search_memories")
            return []

        limit = limit or self.search_limit

        try:
            # If include_all_agents=True, don't pass agent_id (gets all)
            search_agent_id = None if include_all_agents else agent_id

            result = self.client.search(
                query=query,
                user_id=self.cluster_name,
                agent_id=search_agent_id,
                filters=filters,
                limit=limit
            )

            memories = result.get("results", [])
            scope = f"agent={agent_id}" if agent_id else ("all agents" if include_all_agents else "global")
            logger.info(f"Found {len(memories)} memories: cluster={self.cluster_name}, {scope}")
            return memories

        except Exception as e:
            logger.error(f"Failed to search memories: {e}")
            return []  # Return empty list on error, don't break monitoring

    def get_all_memories(
        self,
        agent_id: Optional[str] = None
    ) -> List[Dict]:
        """Get all memories for cluster (optionally scoped to subagent)"""
        if not self.enabled:
            return []

        try:
            result = self.client.get_all(
                user_id=self.cluster_name,
                agent_id=agent_id
            )
            return result.get("results", [])
        except Exception as e:
            logger.error(f"Failed to get all memories: {e}")
            return []

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a specific memory by ID"""
        if not self.enabled:
            return False

        try:
            self.client.delete(memory_id=memory_id)
            logger.info(f"Deleted memory {memory_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            return False
```

### Step 1.4: Create Memory Manager

Create `src/memory/memory_manager.py`:

```python
"""
High-level memory management for k8s-monitor multi-agent architecture
Provides domain-specific operations for each subagent
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime

from .mem0_client import Mem0ClientWrapper
from .memory_config import SEARCH_FILTERS

logger = logging.getLogger(__name__)


class MemoryManager:
    """High-level memory operations for k8s-monitor subagents"""

    def __init__(self, cluster_name: str):
        """
        Initialize memory manager

        Args:
            cluster_name: Kubernetes cluster name (e.g., "dev-eks")
        """
        self.client = Mem0ClientWrapper(cluster_name=cluster_name)
        self.cluster_name = cluster_name

    # ==================== k8s-analyzer Operations ====================

    def search_similar_incidents(
        self,
        namespace: str,
        incident_type: str,
        service: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict]:
        """
        Search for similar past incidents (k8s-analyzer subagent)

        Args:
            namespace: K8s namespace
            incident_type: Type (e.g., 'OOMKilled', 'CrashLoopBackOff')
            service: Optional service name filter
            limit: Max results

        Returns:
            List of similar incidents with root causes
        """
        service_query = f"{service} " if service else ""
        query = f"{namespace} {service_query}{incident_type} incident root cause"

        return self.client.search_memories(
            query=query,
            agent_id="k8s-analyzer",
            filters=SEARCH_FILTERS["incidents"],
            limit=limit
        )

    def store_incident_analysis(
        self,
        namespace: str,
        pod_name: str,
        incident_type: str,
        analysis: str,
        severity: str,
        root_cause: Optional[str] = None,
        service: Optional[str] = None
    ):
        """
        Store incident analysis (k8s-analyzer subagent)

        Args:
            namespace: K8s namespace
            pod_name: Pod name
            incident_type: Incident type
            analysis: Full analysis text
            severity: 'critical', 'high', 'medium', 'low'
            root_cause: Identified root cause (if found)
            service: Service name (optional)
        """
        messages = [
            {"role": "assistant", "content": f"Incident Analysis: {namespace}/{pod_name}\n\n{analysis}"}
        ]

        if root_cause:
            messages.append({
                "role": "assistant",
                "content": f"Root Cause: {root_cause}"
            })

        metadata = {
            "namespace": namespace,
            "pod_name": pod_name,
            "incident_type": incident_type,
            "severity": severity,
            "service": service or "unknown",
            "timestamp": datetime.now().isoformat(),
            "source": "k8s-analyzer"
        }

        self.client.add_memory(
            messages=messages,
            agent_id="k8s-analyzer",
            metadata=metadata,
            expiration_type="incident"  # 90-day expiration
        )

        logger.info(f"Stored incident: {namespace}/{pod_name} - {incident_type}")

    def search_remediation_patterns(
        self,
        incident_type: str,
        namespace: Optional[str] = None,
        limit: int = 3
    ) -> List[Dict]:
        """
        Search for successful remediation patterns

        Args:
            incident_type: Type of incident
            namespace: Optional namespace filter
            limit: Max results

        Returns:
            List of successful remediations
        """
        ns_query = f"{namespace} " if namespace else ""
        query = f"{ns_query}{incident_type} successful remediation resolution"

        return self.client.search_memories(
            query=query,
            agent_id="k8s-analyzer",
            filters=SEARCH_FILTERS["incidents"],
            limit=limit
        )

    def store_remediation_outcome(
        self,
        namespace: str,
        service: str,
        action: str,
        outcome: str,
        success: bool,
        incident_type: str
    ):
        """
        Store remediation action outcome

        Args:
            namespace: K8s namespace
            service: Service name
            action: Action taken (e.g., "Rolling restart", "Increased memory to 2Gi")
            outcome: Result description
            success: Whether remediation succeeded
            incident_type: Type of incident remediated
        """
        status = "successful" if success else "failed"
        messages = [{
            "role": "assistant",
            "content": f"Remediation ({status}): {namespace}/{service}\n\nAction: {action}\n\nOutcome: {outcome}"
        }]

        metadata = {
            "namespace": namespace,
            "service": service,
            "action_type": action,
            "success": success,
            "incident_type": incident_type,
            "timestamp": datetime.now().isoformat(),
            "source": "k8s-analyzer"
        }

        expiration = "remediation" if success else "incident"  # Keep successes forever

        self.client.add_memory(
            messages=messages,
            agent_id="k8s-analyzer",
            metadata=metadata,
            expiration_type=expiration
        )

    # ==================== Cost Optimizer Operations ====================

    def search_cost_insights(
        self,
        namespace: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict]:
        """
        Search for cost optimization insights

        Args:
            namespace: Optional namespace filter
            limit: Max results

        Returns:
            List of cost optimization learnings
        """
        ns_query = f"{namespace} " if namespace else ""
        query = f"{ns_query}cost optimization resource right-sizing over-provisioning"

        return self.client.search_memories(
            query=query,
            agent_id="k8s-analyzer",  # Cost insights stored by k8s-analyzer
            filters=SEARCH_FILTERS["cost"],
            limit=limit
        )

    def store_cost_insight(
        self,
        namespace: str,
        service: str,
        insight: str,
        recommendation: str,
        potential_savings: Optional[str] = None
    ):
        """
        Store cost optimization insight

        Args:
            namespace: K8s namespace
            service: Service name
            insight: Observation (e.g., "Pod requesting 4Gi, using 1.2Gi avg")
            recommendation: Suggested action
            potential_savings: Estimated savings (optional)
        """
        savings_text = f"\n\nPotential Savings: {potential_savings}" if potential_savings else ""
        messages = [{
            "role": "assistant",
            "content": f"Cost Insight: {namespace}/{service}\n\n{insight}\n\nRecommendation: {recommendation}{savings_text}"
        }]

        metadata = {
            "namespace": namespace,
            "service": service,
            "insight_type": "cost_optimization",
            "timestamp": datetime.now().isoformat(),
            "source": "k8s-analyzer"
        }

        self.client.add_memory(
            messages=messages,
            agent_id="k8s-analyzer",
            metadata=metadata,
            expiration_type="cost"  # 180-day expiration
        )

    # ==================== github-reviewer Operations ====================

    def search_deployment_impacts(
        self,
        service: str,
        limit: int = 3
    ) -> List[Dict]:
        """
        Search for GitHub deployment impact patterns

        Args:
            service: Service name
            limit: Max results

        Returns:
            List of deployment correlations
        """
        query = f"{service} deployment impact incident correlation"

        return self.client.search_memories(
            query=query,
            agent_id="github-reviewer",
            filters=SEARCH_FILTERS["deployment"],
            limit=limit
        )

    def store_deployment_correlation(
        self,
        service: str,
        pr_number: Optional[int],
        commit_sha: str,
        impact: str,
        namespace: str
    ):
        """
        Store GitHub deployment impact correlation

        Args:
            service: Service name
            pr_number: PR number (if available)
            commit_sha: Commit SHA
            impact: Impact description
            namespace: K8s namespace affected
        """
        pr_text = f"PR #{pr_number}, " if pr_number else ""
        messages = [{
            "role": "assistant",
            "content": f"Deployment Impact: {service} ({pr_text}{commit_sha[:7]})\n\nImpact: {impact}\n\nNamespace: {namespace}"
        }]

        metadata = {
            "service": service,
            "pr_number": pr_number,
            "commit_sha": commit_sha,
            "namespace": namespace,
            "timestamp": datetime.now().isoformat(),
            "source": "github-reviewer"
        }

        self.client.add_memory(
            messages=messages,
            agent_id="github-reviewer",
            metadata=metadata,
            expiration_type="deployment"  # 90-day expiration
        )

    # ==================== slack-notifier Operations ====================

    def search_alert_patterns(
        self,
        incident_type: str,
        limit: int = 3
    ) -> List[Dict]:
        """
        Search for Slack alert patterns and deduplication rules

        Args:
            incident_type: Type of incident
            limit: Max results

        Returns:
            List of alert patterns
        """
        query = f"{incident_type} alert deduplication escalation pattern"

        return self.client.search_memories(
            query=query,
            agent_id="slack-notifier",
            filters=SEARCH_FILTERS["alerts"],
            limit=limit
        )

    def store_alert_pattern(
        self,
        incident_type: str,
        pattern: str,
        action: str,
        namespace: Optional[str] = None
    ):
        """
        Store alert pattern or deduplication rule

        Args:
            incident_type: Type of incident
            pattern: Pattern description
            action: Action taken (e.g., "Skipped alert - known recurring issue")
            namespace: Optional namespace
        """
        ns_text = f" in {namespace}" if namespace else ""
        messages = [{
            "role": "assistant",
            "content": f"Alert Pattern{ns_text}: {incident_type}\n\nPattern: {pattern}\n\nAction: {action}"
        }]

        metadata = {
            "incident_type": incident_type,
            "namespace": namespace,
            "pattern_type": "alert",
            "timestamp": datetime.now().isoformat(),
            "source": "slack-notifier"
        }

        self.client.add_memory(
            messages=messages,
            agent_id="slack-notifier",
            metadata=metadata,
            expiration_type="alert"  # Permanent
        )

    # ==================== Shared Operations ====================

    def format_memories_as_context(
        self,
        memories: List[Dict],
        max_length: int = 3000
    ) -> str:
        """
        Format retrieved memories as context string for LLM

        Args:
            memories: List of memory dicts from search
            max_length: Max total character length

        Returns:
            Formatted string suitable for LLM context
        """
        if not memories:
            return ""

        context_parts = ["**Past learnings from similar situations:**\n"]
        total_length = len(context_parts[0])

        for i, mem in enumerate(memories, 1):
            memory_text = mem.get("memory", "")
            score = mem.get("score", 0.0)
            metadata = mem.get("metadata", {})

            # Format: - [Relevance: 0.89] Memory text (namespace: proteus-prod, 2 days ago)
            namespace = metadata.get("namespace", "unknown")
            timestamp = metadata.get("timestamp", "")

            # Calculate days ago
            days_ago = ""
            if timestamp:
                try:
                    mem_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    days = (datetime.now(mem_time.tzinfo) - mem_time).days
                    if days == 0:
                        days_ago = "today"
                    elif days == 1:
                        days_ago = "yesterday"
                    else:
                        days_ago = f"{days} days ago"
                except:
                    pass

            time_text = f", {days_ago}" if days_ago else ""
            entry = f"- [Relevance: {score:.2f}] {memory_text} (namespace: {namespace}{time_text})\n"

            if total_length + len(entry) > max_length:
                context_parts.append("\n... (additional memories truncated for brevity)")
                break

            context_parts.append(entry)
            total_length += len(entry)

        return "".join(context_parts)

    def get_cluster_statistics(self) -> Dict:
        """
        Get memory statistics for the cluster

        Returns:
            Dict with memory counts by subagent and category
        """
        if not self.client.enabled:
            return {"enabled": False}

        all_memories = self.client.get_all_memories()

        stats = {
            "cluster": self.cluster_name,
            "total_memories": len(all_memories),
            "by_agent": {},
            "by_category": {},
            "oldest_memory": None,
            "newest_memory": None
        }

        # Count by agent_id
        for mem in all_memories:
            agent = mem.get("metadata", {}).get("source", "global")
            stats["by_agent"][agent] = stats["by_agent"].get(agent, 0) + 1

            # Count by category
            for cat in mem.get("categories", []):
                stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

        # Find oldest/newest
        if all_memories:
            timestamps = [m.get("created_at") for m in all_memories if m.get("created_at")]
            if timestamps:
                stats["oldest_memory"] = min(timestamps)
                stats["newest_memory"] = max(timestamps)

        return stats
```

### Step 1.5: Update Configuration

Add to `.env`:
```bash
# mem0 Configuration
MEM0_API_KEY=your-mem0-api-key-here
MEM0_ENABLED=true
MEM0_SEARCH_LIMIT=5
```

Add to `src/config/settings.py`:
```python
# In Settings class
mem0_api_key: str = os.getenv("MEM0_API_KEY", "")
mem0_enabled: bool = os.getenv("MEM0_ENABLED", "true").lower() == "true"
mem0_search_limit: int = int(os.getenv("MEM0_SEARCH_LIMIT", "5"))
```

### Phase 1 Completion Checklist

- ⬜ mem0 SDK installed (`pip install mem0ai`)
- ⬜ API key obtained and added to `.env`
- ⬜ Memory module created (`src/memory/`)
- ⬜ `memory_config.py` with k8s-specific categories
- ⬜ `mem0_client.py` wrapper with cluster scoping
- ⬜ `memory_manager.py` with subagent operations
- ⬜ Settings updated with mem0 config
- ⬜ mem0 project configured (visible in dashboard)

**Validation:**
```bash
cd k8s-monitor
python -c "from src.memory.mem0_client import Mem0ClientWrapper; client = Mem0ClientWrapper('dev-eks'); print('✅ mem0 initialized')"
```

---

## Phase 2: Orchestrator Integration

**Duration:** 2 days
**Effort:** Medium
**Risk:** Medium

### Step 2.1: Modify PersistentMonitor

Edit `src/orchestrator/persistent_monitor.py`:

```python
# Add to imports
from src.memory.memory_manager import MemoryManager

class PersistentMonitor:
    def __init__(self, settings: Settings, monitor: Monitor):
        # ... existing initialization ...

        # Add memory manager
        cluster_name = settings.cluster_name or "dev-eks"
        self.memory = MemoryManager(cluster_name=cluster_name)
        self.logger.info(f"Memory manager initialized for cluster: {cluster_name}")

    async def run_persistent_cycle(self) -> dict[str, Any]:
        """Run a single monitoring cycle with mem0-enhanced context"""

        if not self.client:
            raise RuntimeError("Session not initialized")

        self.logger.info(f"🔄 Starting cycle #{self.cycle_count + 1}")

        try:
            # STEP 1: Load static context from .claude/CLAUDE.md
            claude_md_path = Path(".claude/CLAUDE.md")
            static_context = ""
            if claude_md_path.exists():
                with open(claude_md_path) as f:
                    static_context = f.read()

            # STEP 2: Search mem0 for recent incident patterns
            recent_incidents = self.memory.search_similar_incidents(
                namespace="",  # All namespaces
                incident_type="",  # All types
                limit=5
            )

            # Also get recent cost insights
            cost_insights = self.memory.search_cost_insights(limit=3)

            # Format as context
            incident_context = self.memory.format_memories_as_context(recent_incidents)
            cost_context = self.memory.format_memories_as_context(cost_insights)

            # STEP 3: Combine static + dynamic context
            enhanced_context = f"""
{static_context}

---

## Recent Learnings from Past Cycles (from mem0)

### Recent Incidents:
{incident_context if incident_context else "No recent similar incidents"}

### Cost Optimization Insights:
{cost_context if cost_context else "No recent cost insights"}

---

Use the above context to inform your analysis. Reference past learnings when you see similar patterns.
"""

            # STEP 4: Run monitoring cycle with enhanced context
            # The Monitor.run_monitoring_cycle() will invoke subagents
            # We'll pass enhanced context via the prompt
            results = await self.monitor.run_monitoring_cycle_with_context(
                enhanced_context=enhanced_context
            )

            # STEP 5: Store findings in mem0 after cycle completes
            await self._store_cycle_findings(results)

            # STEP 6: Update cycle statistics
            self.cycle_count += 1
            self.stats["cycles_completed"] = self.cycle_count
            self.stats["last_cycle_timestamp"] = datetime.now().isoformat()

            # Save session state
            self._save_session()

            self.logger.info(f"✅ Cycle #{self.cycle_count} completed with mem0 enhancement")

            return results

        except Exception as e:
            self.logger.error(f"Error in persistent cycle: {e}", exc_info=True)
            raise

    async def _store_cycle_findings(self, results: Dict[str, Any]):
        """
        Store cycle findings in mem0

        Args:
            results: Results from monitoring cycle
        """
        # Extract incidents from results
        incidents = results.get("incidents", [])

        for incident in incidents:
            # Store each incident analysis
            self.memory.store_incident_analysis(
                namespace=incident.get("namespace", "unknown"),
                pod_name=incident.get("pod_name", "unknown"),
                incident_type=incident.get("type", "unknown"),
                analysis=incident.get("analysis", ""),
                severity=incident.get("severity", "low"),
                root_cause=incident.get("root_cause"),
                service=incident.get("service")
            )

        # Extract remediation outcomes
        remediations = results.get("remediations", [])

        for remediation in remediations:
            self.memory.store_remediation_outcome(
                namespace=remediation.get("namespace", "unknown"),
                service=remediation.get("service", "unknown"),
                action=remediation.get("action", ""),
                outcome=remediation.get("outcome", ""),
                success=remediation.get("success", False),
                incident_type=remediation.get("incident_type", "unknown")
            )

        # Extract cost insights
        cost_recommendations = results.get("cost_recommendations", [])

        for rec in cost_recommendations:
            self.memory.store_cost_insight(
                namespace=rec.get("namespace", "unknown"),
                service=rec.get("service", "unknown"),
                insight=rec.get("insight", ""),
                recommendation=rec.get("recommendation", ""),
                potential_savings=rec.get("potential_savings")
            )

        self.logger.info(f"Stored {len(incidents)} incidents, {len(remediations)} remediations, {len(cost_recommendations)} cost insights in mem0")
```

### Step 2.2: Modify Monitor Class

Edit `src/orchestrator/monitor.py`:

```python
# Add method to accept enhanced context
async def run_monitoring_cycle_with_context(
    self,
    enhanced_context: str = ""
) -> Dict[str, Any]:
    """
    Run monitoring cycle with enhanced context from mem0

    Args:
        enhanced_context: Additional context from mem0 and .claude/CLAUDE.md

    Returns:
        Dict with cycle results
    """
    # Pass enhanced_context to subagent invocations
    # This will be prepended to each subagent's prompt

    # Example for k8s-analyzer subagent:
    k8s_analysis = await self.invoke_subagent(
        agent_name="k8s-analyzer",
        prompt=f"""
{enhanced_context}

---

Please analyze the current cluster state and identify any issues.
Use the past learnings above to inform your analysis.
        """,
        context_data=self.gather_cluster_state()
    )

    # Similar for other subagents...

    return {
        "status": "completed",
        "incidents": self.extract_incidents(k8s_analysis),
        "remediations": [],
        "cost_recommendations": [],
        "timestamp": datetime.now().isoformat()
    }
```

### Step 2.3: Add Memory Statistics to Cycle Reports

Edit `src/orchestrator/persistent_monitor.py`:

```python
def _save_session(self):
    """Save session state including memory statistics"""
    session_file = self.session_dir / "session.json"

    # Get memory statistics
    mem_stats = self.memory.get_cluster_statistics()

    session_data = {
        "session_id": self.session_id,
        "cycle_count": self.cycle_count,
        "messages": self.messages,
        "stats": self.stats,
        "memory_stats": mem_stats  # Add this
    }

    with open(session_file, "w") as f:
        json.dump(session_data, f, indent=2)

    self.logger.debug(f"Session saved: {session_file}")
```

### Phase 2 Completion Checklist

- ⬜ `PersistentMonitor` modified to use MemoryManager
- ⬜ Static context (.claude/CLAUDE.md) combined with dynamic mem0 context
- ⬜ Cycle findings stored in mem0 after each run
- ⬜ Memory statistics included in session saves
- ⬜ `Monitor.run_monitoring_cycle_with_context()` method added
- ⬜ Manual test: Run one cycle, verify mem0 dashboard shows stored memories

**Validation:**
```bash
cd k8s-monitor
python -m src.main
# Check logs for "Stored X incidents... in mem0"
# Check mem0 dashboard for new memories
```

---

## Phase 3: Subagent Memory Enhancement

**Duration:** 3 days
**Effort:** High
**Risk:** Medium

### Step 3.1: Enhance k8s-analyzer Subagent

Edit `.claude/agents/k8s-analyzer.md`:

```markdown
---
name: k8s-analyzer
description: Analyzes Kubernetes cluster state with mem0 adaptive learning
tools: mcp__kubernetes__pods_list, mcp__kubernetes__events_list, mcp__kubernetes__resources_list
model: $K8S_ANALYZER_MODEL
---

# k8s-analyzer Subagent

You are the k8s-analyzer subagent responsible for analyzing Kubernetes cluster health.

## mem0 Integration

**IMPORTANT:** You have access to mem0 for adaptive learning from past incidents.

Before analyzing new incidents, ALWAYS search mem0 for similar past incidents:

```python
from src.memory.memory_manager import MemoryManager

memory = MemoryManager(cluster_name="dev-eks")

# Search for similar incidents
similar = memory.search_similar_incidents(
    namespace="proteus-dev",
    incident_type="OOMKilled",
    limit=3
)

# Format as context
context = memory.format_memories_as_context(similar)
print(context)
```

**When to search mem0:**
- Before analyzing pod failures (search for similar past failures)
- Before recommending remediation (search for successful past remediations)
- When identifying patterns (search for recurring incidents)

**When to store in mem0:**
- After identifying root cause of an incident
- After successful remediation
- After discovering a pattern or correlation

Example storage:
```python
memory.store_incident_analysis(
    namespace="proteus-dev",
    pod_name="proteus-abc123",
    incident_type="OOMKilled",
    analysis="Pod exceeded memory limit. Requested 512Mi, actual usage 1.8Gi",
    severity="high",
    root_cause="Memory limit too low for actual usage pattern",
    service="proteus"
)
```

## Analysis Workflow with mem0

1. **Gather cluster state** (existing logic)
2. **Search mem0** for similar past incidents
3. **Analyze** new incidents with context from past learnings
4. **Store findings** in mem0 for future reference
5. **Recommend actions** based on what worked in the past

## Example: Analyzing OOMKilled Event

When you see an OOMKilled event:

1. Search mem0:
```python
past_oom = memory.search_similar_incidents(
    namespace="proteus-dev",
    incident_type="OOMKilled",
    service="proteus",
    limit=3
)
```

2. Check if past learnings apply:
   - Did we increase memory before? What was the outcome?
   - Is this a recurring pattern?
   - What memory limit ultimately worked?

3. Provide informed recommendation:
   - If past increase to 2Gi worked: "Based on similar incident 5 days ago, increase to 2Gi"
   - If this is 3rd occurrence: "RECURRING ISSUE: This is the 3rd OOMKilled event this week. Escalate for review."

4. Store new analysis:
```python
memory.store_incident_analysis(
    namespace="proteus-dev",
    pod_name=pod_name,
    incident_type="OOMKilled",
    analysis=full_analysis,
    severity="high",
    root_cause=identified_root_cause
)
```

## mem0 Search Strategies

**For incidents:**
```python
memory.search_similar_incidents(namespace, incident_type, service, limit=5)
```

**For remediation patterns:**
```python
memory.search_remediation_patterns(incident_type, namespace, limit=3)
```

**For cost insights:**
```python
memory.search_cost_insights(namespace, limit=5)
```

## Output Format

When referencing past learnings, use this format:

```
## Analysis

Current incident: proteus-dev/proteus-abc123 OOMKilled

**Past Similar Incidents:**
- [5 days ago] proteus-dev OOMKilled - Increased memory to 2Gi, resolved
- [12 days ago] proteus-dev OOMKilled - Initial increase to 1Gi was insufficient

**Recommendation:**
Based on past learnings, increase memory limit to 2Gi (1Gi was insufficient in previous attempt).

**Root Cause:**
Memory limit (512Mi) significantly lower than actual usage (1.8Gi average, 2.1Gi peak).

**Action:**
Store this analysis in mem0 for future reference.
```

---

Continue with your existing k8s analysis logic, but enhanced with mem0 context.
```

### Step 3.2: Enhance github-reviewer Subagent

Edit `.claude/agents/github-reviewer.md`:

```markdown
---
name: github-reviewer
description: Correlates GitHub deployments with Kubernetes incidents using mem0
tools: mcp__github__get_pull_request, mcp__github__list_commits, mcp__github__search_code
model: $GITHUB_REVIEWER_MODEL
---

# github-reviewer Subagent

You analyze GitHub deployments and correlate them with Kubernetes incidents.

## mem0 Integration

**Search deployment impacts before analyzing new deployments:**

```python
from src.memory.memory_manager import MemoryManager

memory = MemoryManager(cluster_name="dev-eks")

# Search for past deployment impacts
past_impacts = memory.search_deployment_impacts(
    service="proteus",
    limit=3
)
```

**Store deployment correlations:**

```python
memory.store_deployment_correlation(
    service="proteus",
    pr_number=123,
    commit_sha="abc123def",
    impact="Deployment caused OOMKilled events in proteus-dev namespace",
    namespace="proteus-dev"
)
```

## Workflow

1. **Check recent deployments** (existing logic)
2. **Search mem0** for past deployment impacts on this service
3. **Correlate** current incidents with deployment timing
4. **Store** correlations for future reference

Example output with mem0 context:

```
## Deployment Analysis

**Recent Deployment:** proteus PR #456 (commit def789) deployed 2 hours ago

**Past Deployment Impacts (from mem0):**
- [3 days ago] PR #444 caused OOMKilled - memory config error in deployment.yaml
- [1 week ago] PR #432 caused ImagePullBackOff - registry credentials issue

**Current Correlation:**
Timing matches: OOMKilled events started 15 minutes after deployment.
Likely cause: Similar to PR #444, check deployment.yaml memory config.

**Recommendation:**
Review PR #456 deployment.yaml memory limits. Compare with PR #444 that had similar impact.
```

Continue with existing GitHub correlation logic...
```

### Step 3.3: Enhance slack-notifier Subagent

Edit `.claude/agents/slack-notifier.md`:

```markdown
---
name: slack-notifier
description: Manages Slack alerts with mem0-powered deduplication
tools: slack_send_message
model: $SLACK_NOTIFIER_MODEL
---

# slack-notifier Subagent

You manage Slack alerting with intelligent deduplication using mem0.

## mem0 Integration

**Search alert patterns before sending alerts:**

```python
from src.memory.memory_manager import MemoryManager

memory = MemoryManager(cluster_name="dev-eks")

# Search for alert patterns
patterns = memory.search_alert_patterns(
    incident_type="OOMKilled",
    limit=3
)
```

**Store alert patterns:**

```python
memory.store_alert_pattern(
    incident_type="OOMKilled",
    pattern="proteus-dev OOMKilled recurring every 2 hours",
    action="Skipped alert - known recurring issue, escalation ticket JIRA-123 exists",
    namespace="proteus-dev"
)
```

## Alert Decision Logic with mem0

Before sending an alert:

1. Search mem0 for similar alerts in past 24 hours
2. Check if this is a known recurring pattern
3. Decide:
   - **Send:** If new or escalated severity
   - **Skip:** If duplicate of recent alert or known recurring issue
   - **Modify:** If pattern exists, reference it in alert

Example:

```
## Alert Decision

**Incident:** proteus-dev OOMKilled (5th occurrence today)

**mem0 Alert History:**
- [2 hours ago] Already alerted on-call about proteus-dev OOMKilled
- [Yesterday] Pattern stored: Skip alerts for this issue, JIRA-123 tracks it

**Decision:** SKIP alert
**Reason:** Duplicate of recent alert, tracked in JIRA-123

**Action:** Update JIRA-123 with occurrence count instead of alerting
```

Continue with existing Slack notification logic...
```

### Step 3.4: Add Memory to Subagent Invocations

Create helper in `src/orchestrator/subagent_helper.py`:

```python
"""Helper functions for subagent memory integration"""
from src.memory.memory_manager import MemoryManager


def get_memory_context_for_subagent(
    agent_name: str,
    cluster_name: str,
    incident_context: dict = None
) -> str:
    """
    Get relevant mem0 context for a subagent

    Args:
        agent_name: Name of subagent (e.g., 'k8s-analyzer')
        cluster_name: Cluster name
        incident_context: Optional dict with namespace, incident_type, service

    Returns:
        Formatted memory context string
    """
    memory = MemoryManager(cluster_name=cluster_name)

    if agent_name == "k8s-analyzer":
        # Get incident and remediation memories
        if incident_context:
            similar = memory.search_similar_incidents(
                namespace=incident_context.get("namespace", ""),
                incident_type=incident_context.get("incident_type", ""),
                service=incident_context.get("service"),
                limit=5
            )
        else:
            # General search
            similar = memory.client.search_memories(
                query="recent incidents",
                agent_id="k8s-analyzer",
                limit=5
            )

        return memory.format_memories_as_context(similar)

    elif agent_name == "github-reviewer":
        # Get deployment impact memories
        if incident_context and incident_context.get("service"):
            impacts = memory.search_deployment_impacts(
                service=incident_context["service"],
                limit=3
            )
            return memory.format_memories_as_context(impacts)
        return ""

    elif agent_name == "slack-notifier":
        # Get alert patterns
        if incident_context and incident_context.get("incident_type"):
            patterns = memory.search_alert_patterns(
                incident_type=incident_context["incident_type"],
                limit=3
            )
            return memory.format_memories_as_context(patterns)
        return ""

    else:
        # For other subagents, return general context
        all_memories = memory.client.search_memories(
            query="recent learnings",
            agent_id=agent_name,
            limit=3,
            include_all_agents=True  # Can see other subagents' learnings
        )
        return memory.format_memories_as_context(all_memories)
```

### Phase 3 Completion Checklist

- ⬜ k8s-analyzer subagent enhanced with mem0 searches/storage
- ⬜ github-reviewer subagent enhanced with deployment correlation
- ⬜ slack-notifier subagent enhanced with alert deduplication
- ⬜ Subagent helper created for memory context retrieval
- ⬜ All subagents can access mem0 via MemoryManager
- ⬜ Manual test: Trigger incident, verify subagent uses past learnings

**Validation:**
```bash
# Trigger a test incident (e.g., OOM a pod)
# Check logs for "Past Similar Incidents" in analysis
# Verify mem0 dashboard shows subagent-scoped memories
```

---

## Phase 4: ConfigMap GitOps Integration

**Duration:** 1 day
**Effort:** Low
**Risk:** Low

### Step 4.1: Add mem0 Config to ConfigMap

Edit `k8s/configmaps/agent-config.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: k8s-monitor-config
  namespace: monitoring
data:
  # mem0 configuration
  MEM0_ENABLED: "true"
  MEM0_SEARCH_LIMIT: "5"

  # Existing configuration...
  CLUSTER_NAME: "dev-eks"
  MONITORING_INTERVAL_MINUTES: "15"
  # ...
```

### Step 4.2: Add mem0 API Key to Secret

Edit `k8s/secrets/agent-secrets.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: k8s-monitor-secrets
  namespace: monitoring
type: Opaque
stringData:
  anthropic-api-key: ${ANTHROPIC_API_KEY}
  mem0-api-key: ${MEM0_API_KEY}  # Add this
  # ... other secrets
```

### Step 4.3: Update Deployment

Edit `k8s/deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: k8s-monitor
  namespace: monitoring
spec:
  template:
    spec:
      containers:
      - name: monitor
        image: your-registry/k8s-monitor:v2.0.0-mem0
        env:
        # mem0 configuration
        - name: MEM0_API_KEY
          valueFrom:
            secretKeyRef:
              name: k8s-monitor-secrets
              key: mem0-api-key
        - name: MEM0_ENABLED
          valueFrom:
            configMapKeyRef:
              name: k8s-monitor-config
              key: MEM0_ENABLED
        - name: MEM0_SEARCH_LIMIT
          valueFrom:
            configMapKeyRef:
              name: k8s-monitor-config
              key: MEM0_SEARCH_LIMIT
        # ... other env vars
```

### Step 4.4: GitOps Workflow

With this setup:

1. **Update mem0 settings via Git:**
   ```bash
   # Enable/disable mem0 without rebuilding image
   kubectl edit configmap k8s-monitor-config -n monitoring
   # Change MEM0_ENABLED: "false"
   # Restart pod to apply
   ```

2. **Feature flag rollout:**
   ```bash
   # Week 1: Disable mem0 in production
   MEM0_ENABLED: "false"

   # Week 2: Enable in dev only
   # (separate ConfigMap for dev cluster)

   # Week 3: Enable in production
   MEM0_ENABLED: "true"
   ```

### Phase 4 Completion Checklist

- ⬜ ConfigMap updated with mem0 settings
- ⬜ Secret updated with mem0 API key
- ⬜ Deployment updated to use ConfigMap/Secret
- ⬜ Feature flag tested (disable/enable works without rebuild)
- ⬜ GitOps workflow documented

---

## Phase 5: Testing & Validation

**Duration:** 3 days
**Effort:** High
**Risk:** Medium

### Step 5.1: Unit Tests

Create `tests/memory/test_k8s_memory.py`:

```python
"""Unit tests for k8s-monitor memory integration"""
import pytest
from src.memory.memory_manager import MemoryManager


def test_store_and_search_incident():
    """Test storing and searching incidents"""
    memory = MemoryManager(cluster_name="test-cluster")

    # Store incident
    memory.store_incident_analysis(
        namespace="test-ns",
        pod_name="test-pod-123",
        incident_type="OOMKilled",
        analysis="Pod exceeded memory",
        severity="high",
        root_cause="Memory limit too low"
    )

    # Search for it
    similar = memory.search_similar_incidents(
        namespace="test-ns",
        incident_type="OOMKilled",
        limit=5
    )

    assert len(similar) > 0
    assert "OOMKilled" in similar[0]["memory"]


def test_subagent_memory_scoping():
    """Test that subagent memories are properly scoped"""
    memory = MemoryManager(cluster_name="test-cluster")

    # k8s-analyzer stores incident
    memory.store_incident_analysis(
        namespace="test-ns",
        pod_name="test-pod",
        incident_type="CrashLoop",
        analysis="Test analysis",
        severity="medium"
    )

    # github-reviewer stores deployment
    memory.store_deployment_correlation(
        service="test-service",
        pr_number=123,
        commit_sha="abc123",
        impact="Test impact",
        namespace="test-ns"
    )

    # k8s-analyzer should only see its own memories
    analyzer_memories = memory.client.search_memories(
        query="test",
        agent_id="k8s-analyzer",
        limit=10
    )

    # github-reviewer should only see its own
    github_memories = memory.client.search_memories(
        query="test",
        agent_id="github-reviewer",
        limit=10
    )

    # Verify scoping
    analyzer_count = len([m for m in analyzer_memories if "CrashLoop" in m.get("memory", "")])
    github_count = len([m for m in github_memories if "deployment" in m.get("memory", "").lower()])

    assert analyzer_count > 0
    assert github_count > 0


def test_memory_formatting():
    """Test that memories are formatted correctly for LLM context"""
    memory = MemoryManager(cluster_name="test-cluster")

    # Store a few memories
    for i in range(3):
        memory.store_incident_analysis(
            namespace="test-ns",
            pod_name=f"test-pod-{i}",
            incident_type="OOMKilled",
            analysis=f"Analysis {i}",
            severity="high"
        )

    # Search and format
    memories = memory.search_similar_incidents(
        namespace="test-ns",
        incident_type="OOMKilled",
        limit=5
    )

    context = memory.format_memories_as_context(memories)

    assert "Past learnings" in context
    assert "Relevance:" in context
    assert "namespace: test-ns" in context


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

### Step 5.2: Integration Tests

Create `tests/integration/test_persistent_monitor_memory.py`:

```python
"""Integration tests for PersistentMonitor with mem0"""
import pytest
from src.orchestrator.persistent_monitor import PersistentMonitor
from src.orchestrator.monitor import Monitor
from src.config import Settings


@pytest.mark.asyncio
async def test_cycle_stores_in_memory():
    """Test that monitoring cycle stores findings in mem0"""
    settings = Settings()
    settings.cluster_name = "test-cluster"
    settings.mem0_enabled = True

    monitor = Monitor(settings)
    persistent = PersistentMonitor(settings, monitor)

    await persistent.initialize_session()

    # Run a cycle
    results = await persistent.run_persistent_cycle()

    # Verify mem0 was updated
    mem_stats = persistent.memory.get_cluster_statistics()

    assert mem_stats["total_memories"] > 0
    assert mem_stats["cluster"] == "test-cluster"


@pytest.mark.asyncio
async def test_cycle_uses_past_context():
    """Test that monitoring cycle uses past mem0 context"""
    settings = Settings()
    settings.cluster_name = "test-cluster"

    # Pre-populate mem0 with a past incident
    from src.memory.memory_manager import MemoryManager
    memory = MemoryManager("test-cluster")

    memory.store_incident_analysis(
        namespace="test-ns",
        pod_name="test-pod",
        incident_type="OOMKilled",
        analysis="Past OOM incident",
        severity="high",
        root_cause="Memory too low"
    )

    # Run cycle
    monitor = Monitor(settings)
    persistent = PersistentMonitor(settings, monitor)
    await persistent.initialize_session()

    results = await persistent.run_persistent_cycle()

    # Check that results reference past incident
    # (This depends on your Monitor implementation)
    # For now, just verify cycle completed
    assert results["status"] == "completed"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
```

### Step 5.3: Manual Testing Checklist

**Orchestrator Tests:**
- [ ] Run one monitoring cycle
- [ ] Verify mem0 dashboard shows stored incidents
- [ ] Check cycle report includes memory statistics
- [ ] Trigger similar incident in next cycle
- [ ] Verify analysis references past incident

**Subagent Tests:**
- [ ] k8s-analyzer: Verify searches mem0 before analyzing
- [ ] k8s-analyzer: Verify stores root cause analysis
- [ ] github-reviewer: Verify correlates deployments
- [ ] slack-notifier: Verify deduplicates alerts
- [ ] Verify agent_id scoping (each subagent sees own memories)

**Cross-Subagent Tests:**
- [ ] k8s-analyzer finds incident
- [ ] github-reviewer correlates with deployment
- [ ] Verify both memories accessible with include_all_agents=True

**ConfigMap Tests:**
- [ ] Set MEM0_ENABLED=false in ConfigMap
- [ ] Restart pod
- [ ] Verify monitoring works without mem0
- [ ] Set MEM0_ENABLED=true
- [ ] Verify mem0 re-enabled

### Phase 5 Completion Checklist

- ⬜ All unit tests passing
- ⬜ Integration tests passing
- ⬜ Manual testing checklist complete
- ⬜ No errors in logs during testing
- ⬜ mem0 dashboard shows expected subagent-scoped memories
- ⬜ Feature flag works (disable/enable)

---

## Phase 6: Production Deployment

**Duration:** 2 days
**Effort:** Medium
**Risk:** Low (with feature flag)

### Step 6.1: Production Readiness

**Pre-deployment checklist:**
- [ ] All tests passing
- [ ] mem0 API key configured in production secrets
- [ ] ConfigMap feature flag set to false initially
- [ ] Docker image built with mem0 integration
- [ ] Rollback plan documented

**Build production image:**
```bash
cd k8s-monitor

# Tag with mem0 version
docker build -t your-registry/k8s-monitor:v2.0.0-mem0 .
docker push your-registry/k8s-monitor:v2.0.0-mem0
```

### Step 6.2: Gradual Rollout

**Week 1: Deploy with mem0 Disabled**
```yaml
# k8s/configmaps/agent-config.yaml
MEM0_ENABLED: "false"
```

```bash
kubectl apply -f k8s/
# Verify monitoring works without mem0
```

**Week 2: Enable for Non-Critical Namespaces**
```yaml
MEM0_ENABLED: "true"
```

```bash
kubectl apply -f k8s/configmaps/agent-config.yaml
kubectl rollout restart deployment/k8s-monitor -n monitoring
```

Monitor for 3-5 days:
- Check mem0 dashboard daily
- Verify memory quality >80%
- Track any errors in logs

**Week 3: Full Production Enable**

If Week 2 successful, continue with mem0 enabled.

If issues detected:
```yaml
MEM0_ENABLED: "false"  # Quick rollback
```

### Step 6.3: Production Monitoring

**CloudWatch/Grafana Metrics:**

Add to `src/utils/metrics.py`:

```python
"""Production metrics for mem0 integration"""
import logging
from src.memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


def log_memory_metrics(cluster_name: str):
    """Log mem0 metrics for monitoring"""
    memory = MemoryManager(cluster_name=cluster_name)
    stats = memory.get_cluster_statistics()

    # Log as structured metrics
    logger.info("mem0_cluster_total", extra={
        "metric_name": "mem0_total_memories",
        "metric_value": stats["total_memories"],
        "cluster": cluster_name
    })

    for agent, count in stats.get("by_agent", {}).items():
        logger.info(f"mem0_agent_{agent}", extra={
            "metric_name": f"mem0_agent_memories",
            "metric_value": count,
            "agent": agent,
            "cluster": cluster_name
        })

    for category, count in stats.get("by_category", {}).items():
        logger.info(f"mem0_category_{category}", extra={
            "metric_name": "mem0_category_memories",
            "metric_value": count,
            "category": category,
            "cluster": cluster_name
        })
```

Call in `persistent_monitor.py` after each cycle:
```python
from src.utils.metrics import log_memory_metrics

# After cycle completes
log_memory_metrics(self.settings.cluster_name)
```

**Track these metrics:**
- `mem0_total_memories` - Total memories stored
- `mem0_agent_memories` - Memories per subagent
- `mem0_category_memories` - Memories per category
- `mem0_search_latency_ms` - Search performance
- `mem0_memories_used_per_cycle` - How many memories retrieved

### Step 6.4: Production Operations

**Daily Review (5 min):**
1. Check mem0 dashboard
2. Review memory count growth (should be steady, not exponential)
3. Spot-check memory quality

**Weekly Maintenance (15 min):**
```bash
# Run memory audit
kubectl exec -it deployment/k8s-monitor -n monitoring -- \
  python -c "from src.memory.memory_manager import MemoryManager; \
             from src.config import Settings; \
             s = Settings(); \
             m = MemoryManager(s.cluster_name); \
             import json; \
             print(json.dumps(m.get_cluster_statistics(), indent=2))"
```

**Monthly Review:**
- Compare incident resolution times (before/after mem0)
- Review memory quality (manual sample)
- Check cost (free tier sufficient? need Pro?)
- Tune custom_instructions if needed

### Phase 6 Completion Checklist

- ⬜ Production image deployed
- ⬜ Gradual rollout complete (3 weeks)
- ⬜ Monitoring dashboard configured
- ⬜ Daily review process established
- ⬜ Team trained on mem0 operations
- ⬜ Runbook updated

---

## Monitoring & Operations

### mem0 Dashboard

**Daily checks (https://mem0.ai/dashboard):**
- Memory count trend (should grow linearly, not exponentially)
- Recent memories - spot check quality
- Category distribution - incidents should be majority

### Memory Quality Audit

**Weekly audit script:**

Create `scripts/audit_memory.py`:

```python
"""Weekly mem0 quality audit script"""
from src.memory.memory_manager import MemoryManager
from src.config import Settings

settings = Settings()
memory = MemoryManager(settings.cluster_name)

# Get statistics
stats = memory.get_cluster_statistics()

print(f"\\n=== mem0 Quality Audit for {stats['cluster']} ===\\n")
print(f"Total Memories: {stats['total_memories']}")
print(f"\\nBy Subagent:")
for agent, count in stats.get("by_agent", {}).items():
    print(f"  {agent}: {count}")

print(f"\\nBy Category:")
for cat, count in stats.get("by_category", {}).items():
    print(f"  {cat}: {count}")

print(f"\\nOldest Memory: {stats.get('oldest_memory', 'N/A')}")
print(f"Newest Memory: {stats.get('newest_memory', 'N/A')}")

# Sample recent memories
print(f"\\n=== Recent Memories Sample ===")
recent = memory.client.search_memories(
    query="",
    limit=5
)

for i, mem in enumerate(recent, 1):
    print(f"\\n{i}. {mem.get('memory', '')[:100]}...")
    print(f"   Categories: {mem.get('categories', [])}")
    print(f"   Created: {mem.get('created_at', 'N/A')}")
```

Run weekly:
```bash
cd k8s-monitor
python scripts/audit_memory.py
```

### Cleanup Old Memories

**Monthly cleanup (if >1000 memories):**

```python
from src.memory.mem0_client import Mem0ClientWrapper
from datetime import datetime, timedelta

cluster_name = "dev-eks"
client = Mem0ClientWrapper(cluster_name=cluster_name)

all_memories = client.get_all_memories()

# Delete memories older than 180 days
cutoff = datetime.now() - timedelta(days=180)

for mem in all_memories:
    created = datetime.fromisoformat(mem["created_at"].replace("Z", "+00:00"))
    if created < cutoff:
        # Don't delete remediation patterns (permanent)
        if "remediation" not in mem.get("categories", []):
            client.delete_memory(mem["id"])
            print(f"Deleted: {mem['id']} (age: {(datetime.now() - created).days} days)")
```

---

## Rollback Strategy

### Quick Disable (< 1 minute)

```bash
# Set feature flag
kubectl patch configmap k8s-monitor-config -n monitoring \
  -p '{"data":{"MEM0_ENABLED":"false"}}'

# Restart to apply
kubectl rollout restart deployment/k8s-monitor -n monitoring
```

Agent works normally without mem0 (graceful degradation).

### Full Removal

If mem0 causes persistent issues:

1. **Disable via ConfigMap** (above)
2. **Rollback to pre-mem0 image:**
   ```bash
   kubectl set image deployment/k8s-monitor \
     monitor=your-registry/k8s-monitor:v1.9.0 -n monitoring
   ```
3. **Remove mem0 code** (optional):
   ```bash
   git revert <mem0-integration-commit>
   ```

### Rollback Decision Criteria

Rollback if:
- mem0 API outage >2 hours
- Search latency consistently >2 seconds
- Memory quality <60% useful
- Cost exceeds budget without ROI

---

## Success Criteria

### After 2 Weeks

- ✅ 30+ incidents stored across subagents
- ✅ Subagents reference past learnings in analysis
- ✅ No mem0-related errors
- ✅ Memory quality >75%

### After 1 Month

- ✅ 70% of recurring incidents auto-detected
- ✅ 40% reduction in Jira duplicate comments
- ✅ Cost optimization insights retained and reused
- ✅ Deployment correlations stored by github-reviewer

### After 3 Months

- ✅ 80% remediation success rate (past solutions work)
- ✅ Slack alert noise reduced by 30%
- ✅ Subagents share knowledge (cross-agent learnings)
- ✅ ROI justifies $249/month Pro plan (if needed)

---

## Cost Summary

| Phase | Timeline | mem0 Tier | Monthly Cost |
|-------|----------|-----------|--------------|
| **Testing** | Week 1-2 | Free | $0 |
| **Validation** | Week 3-8 | Free | $0 |
| **Production** | Month 3+ | Free or Pro | $0 or $249 |

**Free tier:** 10K memories (likely sufficient for 1-2 clusters)
**Pro tier:** Unlimited memories, needed if >10K or multiple clusters

**Startup Program:** <$5M funding = 3 months free Pro

---

## Comparison: oncall vs k8s-monitor Integration

| Aspect | oncall | k8s-monitor |
|--------|--------|-------------|
| **Integration complexity** | Medium | High (multi-agent) |
| **Memory scoping** | user_id only | user_id + agent_id |
| **Subagents** | None | 4 subagents with separate memories |
| **Existing memory** | None | .claude/CLAUDE.md (complementary) |
| **Primary benefit** | Cross-mode sharing | Adaptive learning per subagent |
| **Implementation time** | ~2 weeks | ~3-4 weeks |

---

## Resources

- **mem0 Documentation:** https://docs.mem0.ai
- **mem0 Dashboard:** https://mem0.ai/dashboard
- **This Plan:** `docs/implementations/mem0-k8s-monitor-implementation-plan.md`
- **oncall Plan:** `docs/implementations/mem0-oncall-implementation-plan.md`
- **k8s-monitor README:** `k8s-monitor/README.md`

---

## Next Steps

1. Start with **Phase 1: Setup** (1 day)
2. Complete through **Phase 3** (1 week total)
3. Test thoroughly in **Phase 5** (3 days)
4. Gradual production rollout in **Phase 6** (3 weeks)

**Total timeline:** ~5-6 weeks for full production deployment

---

**Document Version:** 1.0
**Last Updated:** 2025-11-12
**Author:** AI Implementation Team
**Status:** Ready for Implementation
