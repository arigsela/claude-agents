# mem0 Integration for OnCall Agent - Implementation Plan
## Persistent Memory for Incident Troubleshooting

---

## Table of Contents

1. [Overview & Goals](#overview--goals)
2. [Architecture Changes](#architecture-changes)
3. [Phase 1: Setup & Configuration](#phase-1-setup--configuration)
4. [Phase 2: Daemon Mode Integration](#phase-2-daemon-mode-integration)
5. [Phase 3: API Mode Integration](#phase-3-api-mode-integration)
6. [Phase 4: Memory Quality Tuning](#phase-4-memory-quality-tuning)
7. [Phase 5: Testing & Validation](#phase-5-testing--validation)
8. [Phase 6: Production Deployment](#phase-6-production-deployment)
9. [Monitoring & Operations](#monitoring--operations)
10. [Rollback Strategy](#rollback-strategy)

---

## Overview & Goals

### Current State

The oncall agent currently has **no persistent memory**:
- **Daemon mode**: Stateless monitoring cycles, repeats similar investigations
- **API mode**: 30-minute session TTL, no long-term learning
- **No knowledge sharing** between daemon and API modes
- **No correlation** of incidents beyond 30-minute time windows

### What mem0 Adds

```
┌────────────────────────────────────────────────────────────────┐
│                    mem0 Memory Layer                            │
│  - Persistent incident history across all sessions             │
│  - Semantic search for similar past incidents                  │
│  - Knowledge sharing between daemon and API modes              │
│  - Long-term learning from troubleshooting patterns            │
└────────────────────────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────────┐          ┌─────────────────────┐
│   Daemon Mode       │          │    API Mode         │
│  (orchestrator.py)  │          │  (api_server.py)    │
│                     │          │                     │
│  Before incident:   │          │  Before query:      │
│  - Search mem0 for  │          │  - Search session   │
│    similar past     │          │    memory           │
│    incidents        │          │  - Search daemon    │
│                     │          │    learnings        │
│  After resolution:  │          │                     │
│  - Store incident   │          │  After response:    │
│    & root cause     │          │  - Store in session │
│  - Store remediation│          │    memory           │
│    patterns         │          │                     │
└─────────────────────┘          └─────────────────────┘
```

### Success Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Duplicate investigations** | 50-75% reduction | Track similar incidents resolved faster |
| **Incident resolution time** | 30% improvement | Before/after comparison |
| **LLM calls** | 20-30% reduction | Token usage tracking |
| **Knowledge sharing** | 100% | API mode can reference daemon learnings |
| **Memory quality** | >80% useful | Manual review of stored memories |

---

## Architecture Changes

### New Dependencies

```python
# oncall/requirements.txt
mem0ai==1.0.0  # Add this line
```

### New Configuration

```bash
# oncall/.env
MEM0_API_KEY=your-mem0-api-key-here
MEM0_PROJECT_ID=oncall-agent  # Optional, for organization

# Memory configuration
MEM0_ENABLED=true  # Feature flag for rollback
MEM0_SEARCH_LIMIT=5  # How many memories to retrieve per query
MEM0_EXPIRATION_DAYS=90  # Auto-expire old incident memories
```

### New Files

```
oncall/
├── src/
│   ├── memory/                    # NEW: Memory management
│   │   ├── __init__.py
│   │   ├── mem0_client.py         # mem0 wrapper with retry logic
│   │   ├── memory_manager.py      # High-level memory operations
│   │   └── memory_config.py       # Categories and custom instructions
│   └── utils/
│       └── memory_metrics.py      # NEW: Track memory usage and savings
└── tests/
    └── memory/                    # NEW: Memory integration tests
        ├── test_mem0_client.py
        └── test_memory_manager.py
```

---

## Phase 1: Setup & Configuration

**Duration:** 1 day
**Effort:** Low
**Risk:** Low

### Step 1.1: Install mem0 and Sign Up

```bash
cd oncall

# Install mem0 SDK
pip install mem0ai

# Update requirements.txt
echo "mem0ai==1.0.0" >> requirements.txt

# Freeze dependencies
pip freeze > requirements.txt
```

**Sign up for mem0:**
1. Visit https://mem0.ai
2. Create account (free tier: 10K memories)
3. Get API key from dashboard
4. Add to `.env`:
   ```bash
   MEM0_API_KEY=m0-xxx-your-key-here
   ```

### Step 1.2: Create Memory Configuration

Create `src/memory/memory_config.py`:

```python
"""
mem0 configuration for oncall agent
Defines categories and custom instructions for memory filtering
"""

# Custom categories for incident memories
MEMORY_CATEGORIES = [
    {
        "name": "incidents",
        "description": "Kubernetes incidents, root causes, and resolutions"
    },
    {
        "name": "aws_resources",
        "description": "AWS resource relationships and dependencies"
    },
    {
        "name": "github_deploys",
        "description": "GitHub deployment correlations and impact patterns"
    },
    {
        "name": "troubleshooting",
        "description": "Investigation patterns and successful diagnostic steps"
    }
]

# Custom instructions - what to extract from conversations
CUSTOM_INSTRUCTIONS = """
Extract and remember from oncall troubleshooting conversations:

1. **Incident patterns:**
   - Pod crash loops with identified root causes
   - OOMKilled events and actual memory requirements needed
   - ImagePullBackOff issues and registry/secret problems
   - Deployment failures and configuration errors
   - Service degradation patterns and correlations

2. **AWS resource relationships:**
   - Load Balancer -> Target Group -> Pod mappings
   - EBS volume attachment issues
   - IAM role permission problems
   - Security group blocking patterns

3. **GitHub deployment impacts:**
   - Deployments that caused incidents
   - Config changes that resolved issues
   - Correlation between code changes and pod behavior

4. **Successful troubleshooting patterns:**
   - Diagnostic commands that revealed root cause
   - Log patterns that indicated specific issues
   - Resolution steps that worked
   - Time-to-resolution for different incident types

5. **Service dependencies:**
   - Which services depend on each other
   - Critical path services (must stay up)
   - Known recurring issues per service

**EXCLUDE from memory:**
- Health check queries when all systems green
- Generic "status" or "how do I" questions
- Test queries during development (contains "test" keyword)
- Casual conversation or greetings
- Temporary network blips lasting < 1 minute
- Expected pod restarts during normal deployments
- Informational queries about documentation

**Memory expiration rules:**
- Incident investigations: Keep for 90 days
- Temporary issues (networking blips): Keep for 7 days
- Permanent patterns (service dependencies): No expiration
"""

# Memory search filters by context
SEARCH_FILTERS = {
    "incident": {
        "categories": {"in": ["incidents", "troubleshooting"]}
    },
    "aws": {
        "categories": {"in": ["aws_resources"]}
    },
    "deployment": {
        "categories": {"in": ["github_deploys"]}
    },
    "all": {}  # No filters, search everything
}

# Expiration periods (in days)
EXPIRATION_PERIODS = {
    "incident": 90,        # Keep incident memories for 3 months
    "temporary": 7,        # Short-lived issues expire quickly
    "permanent": None,     # Service dependencies never expire
}
```

### Step 1.3: Create mem0 Client Wrapper

Create `src/memory/mem0_client.py`:

```python
"""
mem0 client wrapper with retry logic and error handling
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
    """Wrapper around mem0 MemoryClient with oncall-specific configurations"""

    def __init__(self):
        self.enabled = os.getenv("MEM0_ENABLED", "true").lower() == "true"

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

        logger.info("mem0 client initialized successfully")

    def _configure_project(self):
        """Configure mem0 project with custom categories and instructions"""
        try:
            self.client.project.update(
                custom_instructions=CUSTOM_INSTRUCTIONS,
                custom_categories=MEMORY_CATEGORIES
            )
            logger.info("mem0 project configured with custom categories and instructions")
        except Exception as e:
            logger.error(f"Failed to configure mem0 project: {e}")
            # Don't fail initialization, just log the error

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def add_memory(
        self,
        messages: List[Dict[str, str]],
        user_id: str,
        agent_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        expiration_type: str = "incident"
    ) -> Dict:
        """
        Add memory with automatic expiration

        Args:
            messages: List of message dicts with 'role' and 'content'
            user_id: Unique identifier (e.g., 'oncall-daemon' or 'session-123')
            agent_id: Optional agent identifier (e.g., 'oncall-troubleshooter')
            metadata: Optional metadata dict (cluster, namespace, severity, etc.)
            expiration_type: Type of memory for expiration ('incident', 'temporary', 'permanent')

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
                user_id=user_id,
                agent_id=agent_id,
                metadata=metadata,
                expiration_date=expiration_date
            )
            logger.info(f"Added memory for user_id={user_id}, expiration={expiration_date}")
            return result
        except Exception as e:
            logger.error(f"Failed to add memory: {e}")
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def search_memories(
        self,
        query: str,
        user_id: str,
        agent_id: Optional[str] = None,
        filters: Optional[Dict] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Search memories with semantic similarity

        Args:
            query: Search query string
            user_id: User identifier to search within
            agent_id: Optional agent identifier filter
            filters: Optional metadata/category filters
            limit: Max results to return (defaults to MEM0_SEARCH_LIMIT)

        Returns:
            List of memory dicts with 'memory', 'score', 'metadata', etc.
        """
        if not self.enabled:
            logger.debug("mem0 disabled, skipping search_memories")
            return []

        limit = limit or self.search_limit

        try:
            result = self.client.search(
                query=query,
                user_id=user_id,
                agent_id=agent_id,
                filters=filters,
                limit=limit
            )
            memories = result.get("results", [])
            logger.info(f"Found {len(memories)} memories for query='{query[:50]}...'")
            return memories
        except Exception as e:
            logger.error(f"Failed to search memories: {e}")
            # Return empty list on error, don't break the flow
            return []

    def get_all_memories(
        self,
        user_id: str,
        agent_id: Optional[str] = None
    ) -> List[Dict]:
        """Get all memories for a user/agent"""
        if not self.enabled:
            return []

        try:
            result = self.client.get_all(user_id=user_id, agent_id=agent_id)
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

    def delete_all_memories(
        self,
        user_id: str,
        agent_id: Optional[str] = None
    ) -> bool:
        """Delete all memories for a user/agent"""
        if not self.enabled:
            return False

        try:
            self.client.delete_all(user_id=user_id, agent_id=agent_id)
            logger.info(f"Deleted all memories for user_id={user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete all memories: {e}")
            return False
```

### Step 1.4: Update Environment Configuration

```bash
# oncall/.env - Add these lines
MEM0_API_KEY=your-api-key-here
MEM0_ENABLED=true
MEM0_SEARCH_LIMIT=5
MEM0_EXPIRATION_DAYS=90
```

### Step 1.5: Verify Setup

Create `tests/memory/test_mem0_client.py`:

```python
"""
Basic tests for mem0 client wrapper
"""
import pytest
from datetime import datetime
from src.memory.mem0_client import Mem0ClientWrapper


def test_mem0_client_initialization():
    """Test that mem0 client initializes correctly"""
    client = Mem0ClientWrapper()
    assert client.enabled is True
    assert client.search_limit == 5


def test_add_and_search_memory():
    """Test adding and searching memories"""
    client = Mem0ClientWrapper()

    # Add a test memory
    messages = [
        {"role": "user", "content": "Pod proteus-prod-123 is crashing"},
        {"role": "assistant", "content": "Root cause: OOMKilled. Increase memory to 2Gi"}
    ]

    result = client.add_memory(
        messages=messages,
        user_id="test-user",
        agent_id="oncall-troubleshooter",
        metadata={"namespace": "proteus-prod", "severity": "critical"},
        expiration_type="incident"
    )

    assert result is not None

    # Search for it
    memories = client.search_memories(
        query="proteus pod crashing",
        user_id="test-user",
        limit=5
    )

    assert len(memories) > 0
    assert "OOMKilled" in memories[0]["memory"]


def test_memory_disabled():
    """Test that client respects MEM0_ENABLED=false"""
    import os
    os.environ["MEM0_ENABLED"] = "false"

    client = Mem0ClientWrapper()
    assert client.enabled is False

    # Operations should be no-ops
    result = client.add_memory(
        messages=[{"role": "user", "content": "test"}],
        user_id="test"
    )
    assert result.get("skipped") is True

    # Cleanup
    os.environ["MEM0_ENABLED"] = "true"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

Run the test:
```bash
cd oncall
python -m pytest tests/memory/test_mem0_client.py -v
```

### Phase 1 Completion Checklist

- ⬜ mem0 SDK installed (`pip install mem0ai`)
- ⬜ API key obtained and added to `.env`
- ⬜ `memory_config.py` created with categories and instructions
- ⬜ `mem0_client.py` wrapper created with retry logic
- ⬜ Basic tests passing
- ⬜ mem0 project configured (visible in dashboard)

**Validation:** Run `python tests/memory/test_mem0_client.py` - all tests should pass.

---

## Phase 2: Daemon Mode Integration

**Duration:** 2 days
**Effort:** Medium
**Risk:** Medium

### Step 2.1: Create Memory Manager

Create `src/memory/memory_manager.py`:

```python
"""
High-level memory management for oncall agent
Provides domain-specific memory operations
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime

from .mem0_client import Mem0ClientWrapper
from .memory_config import SEARCH_FILTERS

logger = logging.getLogger(__name__)


class MemoryManager:
    """High-level memory operations for oncall agent"""

    def __init__(self):
        self.client = Mem0ClientWrapper()
        self.daemon_user_id = "oncall-daemon"
        self.agent_id = "oncall-troubleshooter"

    # Daemon mode operations

    def search_similar_incidents(
        self,
        namespace: str,
        service: str,
        incident_type: str,
        limit: int = 5
    ) -> List[Dict]:
        """
        Search for similar past incidents

        Args:
            namespace: K8s namespace (e.g., 'proteus-prod')
            service: Service name (e.g., 'proteus')
            incident_type: Type of incident (e.g., 'OOMKilled', 'CrashLoopBackOff')
            limit: Max results to return

        Returns:
            List of similar incidents with root causes and resolutions
        """
        query = f"{namespace} {service} {incident_type} incident root cause resolution"

        memories = self.client.search_memories(
            query=query,
            user_id=self.daemon_user_id,
            agent_id=self.agent_id,
            filters=SEARCH_FILTERS["incident"],
            limit=limit
        )

        return memories

    def store_incident_investigation(
        self,
        incident_details: str,
        analysis: str,
        namespace: str,
        service: str,
        severity: str,
        root_cause: Optional[str] = None,
        resolution: Optional[str] = None
    ):
        """
        Store an incident investigation in memory

        Args:
            incident_details: Description of the incident
            analysis: Claude's investigation and findings
            namespace: K8s namespace
            service: Service name
            severity: 'critical', 'high', 'medium', 'low'
            root_cause: Identified root cause (if found)
            resolution: How it was resolved (if resolved)
        """
        messages = [
            {"role": "user", "content": incident_details},
            {"role": "assistant", "content": analysis}
        ]

        if root_cause:
            messages.append({
                "role": "assistant",
                "content": f"Root cause: {root_cause}"
            })

        if resolution:
            messages.append({
                "role": "assistant",
                "content": f"Resolution: {resolution}"
            })

        metadata = {
            "namespace": namespace,
            "service": service,
            "severity": severity,
            "source": "daemon",
            "timestamp": datetime.now().isoformat(),
            "cluster": "dev-eks"  # TODO: Make configurable
        }

        self.client.add_memory(
            messages=messages,
            user_id=self.daemon_user_id,
            agent_id=self.agent_id,
            metadata=metadata,
            expiration_type="incident"  # 90-day expiration
        )

        logger.info(f"Stored incident investigation for {service} in {namespace}")

    def search_aws_resource_patterns(
        self,
        resource_type: str,
        issue: str,
        limit: int = 3
    ) -> List[Dict]:
        """Search for AWS resource relationship patterns"""
        query = f"{resource_type} {issue} AWS resource relationship"

        return self.client.search_memories(
            query=query,
            user_id=self.daemon_user_id,
            filters=SEARCH_FILTERS["aws"],
            limit=limit
        )

    def store_aws_resource_learning(
        self,
        resource_mapping: str,
        context: str
    ):
        """Store AWS resource relationship learnings"""
        messages = [{
            "role": "assistant",
            "content": f"AWS Resource Discovery: {resource_mapping}\n\nContext: {context}"
        }]

        self.client.add_memory(
            messages=messages,
            user_id=self.daemon_user_id,
            agent_id=self.agent_id,
            metadata={"source": "daemon", "type": "aws_resources"},
            expiration_type="permanent"  # Keep resource mappings indefinitely
        )

    def search_deployment_impacts(
        self,
        service: str,
        limit: int = 3
    ) -> List[Dict]:
        """Search for GitHub deployment impact patterns"""
        query = f"{service} deployment impact incident correlation"

        return self.client.search_memories(
            query=query,
            user_id=self.daemon_user_id,
            filters=SEARCH_FILTERS["deployment"],
            limit=limit
        )

    def store_deployment_correlation(
        self,
        service: str,
        deployment_info: str,
        impact: str
    ):
        """Store GitHub deployment impact learnings"""
        messages = [{
            "role": "assistant",
            "content": f"Deployment Impact for {service}:\n{deployment_info}\n\nImpact: {impact}"
        }]

        self.client.add_memory(
            messages=messages,
            user_id=self.daemon_user_id,
            agent_id=self.agent_id,
            metadata={"service": service, "source": "daemon", "type": "deployment"},
            expiration_type="incident"
        )

    # API mode operations

    def search_session_memories(
        self,
        session_id: str,
        query: str,
        limit: int = 5
    ) -> List[Dict]:
        """Search memories within an API session"""
        return self.client.search_memories(
            query=query,
            user_id=f"api-session-{session_id}",
            agent_id=self.agent_id,
            limit=limit
        )

    def store_api_interaction(
        self,
        session_id: str,
        user_query: str,
        agent_response: str,
        metadata: Optional[Dict] = None
    ):
        """Store an API interaction in session memory"""
        messages = [
            {"role": "user", "content": user_query},
            {"role": "assistant", "content": agent_response}
        ]

        session_metadata = {
            "source": "api",
            "timestamp": datetime.now().isoformat(),
            **(metadata or {})
        }

        self.client.add_memory(
            messages=messages,
            user_id=f"api-session-{session_id}",
            agent_id=self.agent_id,
            metadata=session_metadata,
            expiration_type="temporary"  # 7-day expiration for API sessions
        )

    # Shared operations

    def get_daemon_learnings_for_api(
        self,
        query: str,
        limit: int = 3
    ) -> List[Dict]:
        """
        Get daemon mode learnings for use in API mode
        Allows API sessions to benefit from daemon investigations
        """
        return self.client.search_memories(
            query=query,
            user_id=self.daemon_user_id,
            agent_id=self.agent_id,
            filters={"metadata": {"source": "daemon"}},
            limit=limit
        )

    def format_memories_as_context(
        self,
        memories: List[Dict],
        max_length: int = 2000
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

        context_parts = ["**Relevant past incidents and learnings:**\n"]

        total_length = len(context_parts[0])

        for i, mem in enumerate(memories, 1):
            memory_text = mem.get("memory", "")
            score = mem.get("score", 0.0)
            metadata = mem.get("metadata", {})

            # Format: - [Relevance: 0.89] Memory text (namespace: proteus-prod)
            namespace = metadata.get("namespace", "unknown")
            entry = f"- [Relevance: {score:.2f}] {memory_text} (namespace: {namespace})\n"

            if total_length + len(entry) > max_length:
                context_parts.append("\n... (additional memories truncated)")
                break

            context_parts.append(entry)
            total_length += len(entry)

        return "".join(context_parts)
```

### Step 2.2: Modify Daemon Orchestrator

Modify `src/integrations/orchestrator.py`:

```python
# Add to imports
from src.memory.memory_manager import MemoryManager

class OnCallOrchestrator:
    def __init__(self):
        # ... existing initialization ...

        # Add memory manager
        self.memory = MemoryManager()
        logger.info("Memory manager initialized")

    async def handle_incident(self, incident: K8sIncident):
        """Handle a Kubernetes incident with memory-enhanced investigation"""

        # STEP 1: Search for similar past incidents
        similar_incidents = self.memory.search_similar_incidents(
            namespace=incident.namespace,
            service=incident.service_name,
            incident_type=incident.event_reason,  # e.g., 'OOMKilled'
            limit=3
        )

        # Format past learnings as context
        past_context = self.memory.format_memories_as_context(similar_incidents)

        if past_context:
            logger.info(f"Found {len(similar_incidents)} similar past incidents")

        # STEP 2: First turn - assess severity with past context
        first_turn_prompt = f"""
{past_context}

**New incident to investigate:**

Namespace: {incident.namespace}
Service: {incident.service_name}
Pod: {incident.pod_name}
Event: {incident.event_reason}
Message: {incident.event_message}
Restart Count: {incident.restart_count}

Based on the past similar incidents above and this new incident:
1. Assess severity (critical/high/medium/low)
2. Determine if this is a recurring pattern
3. Recommend investigation steps
"""

        first_turn_response = await self.anthropic_client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": first_turn_prompt}]
        )

        assessment = first_turn_response.content[0].text

        # STEP 3: Gather additional data (pod logs, events, AWS resources)
        # ... existing data collection logic ...

        # STEP 4: Search for AWS resource patterns if relevant
        aws_context = ""
        if "LoadBalancer" in incident.event_message or "TargetGroup" in incident.event_message:
            aws_memories = self.memory.search_aws_resource_patterns(
                resource_type="LoadBalancer",
                issue=incident.event_reason,
                limit=2
            )
            aws_context = self.memory.format_memories_as_context(aws_memories)

        # STEP 5: Search for deployment correlations
        deployment_context = ""
        deployment_memories = self.memory.search_deployment_impacts(
            service=incident.service_name,
            limit=2
        )
        if deployment_memories:
            deployment_context = self.memory.format_memories_as_context(deployment_memories)

        # STEP 6: Second turn - deep analysis with all context
        second_turn_prompt = f"""
**Previous assessment:**
{assessment}

**Additional context from past incidents:**
{past_context}

{aws_context}

{deployment_context}

**Data collected:**
Pod logs: {pod_logs[:1000]}...
Recent events: {recent_events}
AWS resources: {aws_resources}

Provide:
1. Root cause analysis
2. Specific remediation steps
3. Whether this should be escalated
"""

        second_turn_response = await self.anthropic_client.messages.create(
            model=self.model,
            max_tokens=3000,
            messages=[
                {"role": "user", "content": first_turn_prompt},
                {"role": "assistant", "content": assessment},
                {"role": "user", "content": second_turn_prompt}
            ]
        )

        analysis = second_turn_response.content[0].text

        # STEP 7: Store the investigation in memory
        root_cause = self._extract_root_cause(analysis)  # Helper method
        resolution = self._extract_resolution(analysis)  # Helper method

        self.memory.store_incident_investigation(
            incident_details=f"Incident in {incident.namespace}/{incident.pod_name}: {incident.event_reason} - {incident.event_message}",
            analysis=analysis,
            namespace=incident.namespace,
            service=incident.service_name,
            severity=self._extract_severity(assessment),  # Helper method
            root_cause=root_cause,
            resolution=resolution
        )

        # STEP 8: Store AWS resource learnings if discovered
        if aws_resources:
            self.memory.store_aws_resource_learning(
                resource_mapping=f"Service {incident.service_name} uses {aws_resources}",
                context=f"Discovered during {incident.event_reason} investigation"
            )

        # STEP 9: Send to Teams (existing logic)
        await self.send_teams_notification(incident, analysis)

        logger.info(f"Incident investigation complete and stored in memory")

    def _extract_root_cause(self, analysis: str) -> Optional[str]:
        """Extract root cause from analysis text"""
        # Simple regex or LLM call to extract just the root cause
        # For now, just look for common patterns
        if "root cause:" in analysis.lower():
            # Extract the line after "root cause:"
            lines = analysis.lower().split("\\n")
            for i, line in enumerate(lines):
                if "root cause:" in line and i + 1 < len(lines):
                    return lines[i + 1].strip()
        return None

    def _extract_severity(self, assessment: str) -> str:
        """Extract severity from assessment"""
        assessment_lower = assessment.lower()
        if "critical" in assessment_lower:
            return "critical"
        elif "high" in assessment_lower:
            return "high"
        elif "medium" in assessment_lower:
            return "medium"
        else:
            return "low"

    def _extract_resolution(self, analysis: str) -> Optional[str]:
        """Extract resolution steps from analysis"""
        if "remediation" in analysis.lower() or "resolution" in analysis.lower():
            # Extract remediation section
            lines = analysis.split("\\n")
            for i, line in enumerate(lines):
                if "remediation" in line.lower() or "resolution" in line.lower():
                    # Return next 3 lines
                    return "\\n".join(lines[i:i+4])
        return None
```

### Step 2.3: Test Daemon Integration

Create `tests/memory/test_daemon_memory.py`:

```python
"""
Test daemon mode memory integration
"""
import pytest
from src.integrations.orchestrator import OnCallOrchestrator
from src.memory.memory_manager import MemoryManager


@pytest.mark.asyncio
async def test_daemon_stores_incident():
    """Test that daemon stores incidents in memory"""
    orchestrator = OnCallOrchestrator()

    # Simulate an incident
    from dataclasses import dataclass

    @dataclass
    class MockIncident:
        namespace = "proteus-dev"
        service_name = "proteus"
        pod_name = "proteus-dev-abc123"
        event_reason = "OOMKilled"
        event_message = "Container exceeded memory limit"
        restart_count = 3

    incident = MockIncident()

    # Handle it (should store in memory)
    await orchestrator.handle_incident(incident)

    # Verify it was stored
    memory = MemoryManager()
    similar = memory.search_similar_incidents(
        namespace="proteus-dev",
        service="proteus",
        incident_type="OOMKilled",
        limit=5
    )

    assert len(similar) > 0
    # Should find the incident we just stored


@pytest.mark.asyncio
async def test_daemon_uses_past_context():
    """Test that daemon retrieves and uses past incident context"""
    memory = MemoryManager()

    # Store a past incident
    memory.store_incident_investigation(
        incident_details="proteus-dev pod OOMKilled",
        analysis="Increase memory to 2Gi based on usage patterns",
        namespace="proteus-dev",
        service="proteus",
        severity="high",
        root_cause="Memory limit too low (512Mi) for actual usage (1.8Gi)",
        resolution="Increased memory limit to 2Gi in deployment config"
    )

    # Search for it
    similar = memory.search_similar_incidents(
        namespace="proteus-dev",
        service="proteus",
        incident_type="OOMKilled",
        limit=5
    )

    assert len(similar) > 0
    assert "2Gi" in similar[0]["memory"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
```

### Phase 2 Completion Checklist

- ⬜ `MemoryManager` class created with daemon operations
- ⬜ `orchestrator.py` modified to search memories before investigation
- ⬜ `orchestrator.py` stores incident investigations after analysis
- ⬜ Helper methods created (`_extract_root_cause`, etc.)
- ⬜ Tests passing for daemon memory integration
- ⬜ Manual test: Create incident → Verify stored in mem0 dashboard

**Validation:**
1. Trigger a test incident
2. Check mem0 dashboard - should see the incident stored
3. Trigger similar incident - should reference past incident in analysis

---

## Phase 3: API Mode Integration

**Duration:** 2 days
**Effort:** Medium
**Risk:** Low

### Step 3.1: Modify API Server

Modify `src/api/api_server.py`:

```python
# Add to imports
from src.memory.memory_manager import MemoryManager

# Add to API server initialization
memory = MemoryManager()

@app.post("/query")
async def query(request: QueryRequest):
    """
    Handle user query with memory-enhanced responses
    Combines session memory + daemon learnings
    """
    session_id = request.session_id or str(uuid.uuid4())

    # STEP 1: Search session-specific memories
    session_memories = memory.search_session_memories(
        session_id=session_id,
        query=request.query,
        limit=3
    )

    session_context = memory.format_memories_as_context(session_memories)

    # STEP 2: Search daemon learnings (cross-session knowledge)
    daemon_learnings = memory.get_daemon_learnings_for_api(
        query=request.query,
        limit=3
    )

    daemon_context = memory.format_memories_as_context(daemon_learnings)

    # STEP 3: Build context-aware prompt
    system_prompt = f"""You are an oncall troubleshooting assistant.

{daemon_context}

{session_context}

Use the past incidents and learnings above to inform your response.
If you see a similar past incident, reference it and apply those learnings.
"""

    # STEP 4: Call LLM with enhanced context
    response = await anthropic_client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=2000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.query}
        ]
    )

    agent_response = response.content[0].text

    # STEP 5: Store the interaction in session memory
    memory.store_api_interaction(
        session_id=session_id,
        user_query=request.query,
        agent_response=agent_response,
        metadata={
            "cluster": request.cluster or "dev-eks",
            "namespace": request.namespace
        }
    )

    return {
        "response": agent_response,
        "session_id": session_id,
        "memories_used": len(session_memories) + len(daemon_learnings)
    }


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and its memories"""
    success = memory.client.delete_all_memories(
        user_id=f"api-session-{session_id}",
        agent_id="oncall-troubleshooter"
    )

    if success:
        return {"status": "deleted", "session_id": session_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete session")


@app.get("/session/{session_id}/memories")
async def get_session_memories(session_id: str):
    """Get all memories for a session"""
    memories = memory.client.get_all_memories(
        user_id=f"api-session-{session_id}",
        agent_id="oncall-troubleshooter"
    )

    return {
        "session_id": session_id,
        "memory_count": len(memories),
        "memories": memories
    }
```

### Step 3.2: Test API Integration

Create `tests/api/test_api_memory.py`:

```python
"""
Test API mode memory integration
"""
import pytest
from fastapi.testclient import TestClient
from src.api.api_server import app

client = TestClient(app)


def test_api_stores_interaction():
    """Test that API stores user queries in session memory"""
    response = client.post("/query", json={
        "query": "Why is proteus-dev pod crashing?",
        "cluster": "dev-eks",
        "namespace": "proteus-dev"
    })

    assert response.status_code == 200
    data = response.json()
    session_id = data["session_id"]

    # Check that memory was stored
    memories_response = client.get(f"/session/{session_id}/memories")
    assert memories_response.status_code == 200

    memories_data = memories_response.json()
    assert memories_data["memory_count"] > 0


def test_api_uses_daemon_learnings():
    """Test that API can access daemon mode learnings"""
    # First, store a daemon learning
    from src.memory.memory_manager import MemoryManager
    memory = MemoryManager()

    memory.store_incident_investigation(
        incident_details="proteus-dev OOMKilled",
        analysis="Memory limit too low, increase to 2Gi",
        namespace="proteus-dev",
        service="proteus",
        severity="high"
    )

    # Now query via API
    response = client.post("/query", json={
        "query": "What causes proteus-dev to crash with OOMKilled?",
        "cluster": "dev-eks"
    })

    assert response.status_code == 200
    data = response.json()

    # Should have found daemon learnings
    assert data["memories_used"] > 0
    assert "2Gi" in data["response"]  # Should reference past solution


def test_session_deletion():
    """Test that sessions can be deleted"""
    # Create a session
    response = client.post("/query", json={
        "query": "Test query"
    })
    session_id = response.json()["session_id"]

    # Delete it
    delete_response = client.delete(f"/session/{session_id}")
    assert delete_response.status_code == 200

    # Verify memories are gone
    memories_response = client.get(f"/session/{session_id}/memories")
    assert memories_response.json()["memory_count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

### Phase 3 Completion Checklist

- ⬜ API server modified to search session + daemon memories
- ⬜ API stores interactions in session memory
- ⬜ Session deletion endpoint implemented
- ⬜ Session memories endpoint implemented
- ⬜ Tests passing for API memory integration
- ⬜ Manual test via Swagger UI (`/docs`)

**Validation:**
1. Send query via API: `POST /query`
2. Check `memories_used` in response (should be > 0)
3. Get session memories: `GET /session/{id}/memories`
4. Verify daemon learnings appear in API responses

---

## Phase 4: Memory Quality Tuning

**Duration:** 3-5 days (ongoing)
**Effort:** Low-Medium
**Risk:** Low

### Step 4.1: Monitor Memory Quality

Create `src/utils/memory_metrics.py`:

```python
"""
Track memory usage and quality metrics
"""
import logging
from typing import Dict, List
from datetime import datetime, timedelta
from src.memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class MemoryMetrics:
    """Track memory operations and quality"""

    def __init__(self):
        self.memory = MemoryManager()

    def get_memory_stats(self) -> Dict:
        """Get overall memory statistics"""
        daemon_memories = self.memory.client.get_all_memories(
            user_id="oncall-daemon",
            agent_id="oncall-troubleshooter"
        )

        # Count by category
        category_counts = {}
        for mem in daemon_memories:
            cats = mem.get("categories", [])
            for cat in cats:
                category_counts[cat] = category_counts.get(cat, 0) + 1

        return {
            "total_memories": len(daemon_memories),
            "category_breakdown": category_counts,
            "oldest_memory": min([m.get("created_at") for m in daemon_memories]) if daemon_memories else None,
            "newest_memory": max([m.get("created_at") for m in daemon_memories]) if daemon_memories else None
        }

    def find_duplicate_memories(self, threshold: float = 0.95) -> List[Dict]:
        """Find near-duplicate memories that should be merged"""
        all_memories = self.memory.client.get_all_memories(
            user_id="oncall-daemon"
        )

        duplicates = []

        for i, mem1 in enumerate(all_memories):
            for mem2 in all_memories[i+1:]:
                # Simple similarity check (you could use embeddings for better accuracy)
                mem1_text = mem1.get("memory", "")
                mem2_text = mem2.get("memory", "")

                # Jaccard similarity
                words1 = set(mem1_text.lower().split())
                words2 = set(mem2_text.lower().split())

                if not words1 or not words2:
                    continue

                similarity = len(words1 & words2) / len(words1 | words2)

                if similarity >= threshold:
                    duplicates.append({
                        "memory1_id": mem1["id"],
                        "memory2_id": mem2["id"],
                        "similarity": similarity,
                        "memory1_text": mem1_text[:100],
                        "memory2_text": mem2_text[:100]
                    })

        return duplicates

    def find_stale_memories(self, days: int = 90) -> List[Dict]:
        """Find memories older than threshold that might be outdated"""
        all_memories = self.memory.client.get_all_memories(
            user_id="oncall-daemon"
        )

        cutoff_date = datetime.now() - timedelta(days=days)
        stale = []

        for mem in all_memories:
            created_at = datetime.fromisoformat(mem.get("created_at", "").replace("Z", "+00:00"))
            if created_at < cutoff_date:
                stale.append({
                    "id": mem["id"],
                    "memory": mem.get("memory", "")[:100],
                    "age_days": (datetime.now() - created_at).days,
                    "categories": mem.get("categories", [])
                })

        return stale

    def audit_memory_quality(self) -> Dict:
        """Run full memory quality audit"""
        stats = self.get_memory_stats()
        duplicates = self.find_duplicate_memories()
        stale = self.find_stale_memories()

        return {
            "stats": stats,
            "quality_issues": {
                "duplicate_count": len(duplicates),
                "duplicates": duplicates[:10],  # Top 10
                "stale_count": len(stale),
                "stale_sample": stale[:10]
            },
            "recommendations": self._generate_recommendations(stats, duplicates, stale)
        }

    def _generate_recommendations(
        self,
        stats: Dict,
        duplicates: List,
        stale: List
    ) -> List[str]:
        """Generate recommendations based on audit"""
        recommendations = []

        if stats["total_memories"] > 1000:
            recommendations.append(
                f"⚠️ High memory count ({stats['total_memories']}). "
                "Consider pruning old memories or adjusting expiration."
            )

        if len(duplicates) > 10:
            recommendations.append(
                f"⚠️ Found {len(duplicates)} duplicate memories. "
                "Review custom_instructions to improve filtering."
            )

        if len(stale) > 50:
            recommendations.append(
                f"⚠️ {len(stale)} memories older than 90 days. "
                "Consider deleting outdated incident memories."
            )

        if not recommendations:
            recommendations.append("✅ Memory quality looks good!")

        return recommendations


# CLI command for manual audits
if __name__ == "__main__":
    import json

    metrics = MemoryMetrics()
    audit = metrics.audit_memory_quality()

    print(json.dumps(audit, indent=2))
```

Run manual audit:
```bash
cd oncall
python -m src.utils.memory_metrics
```

### Step 4.2: Iterate on Custom Instructions

Based on audit results, refine `src/memory/memory_config.py`:

```python
# Example refinement after seeing too many duplicates:

CUSTOM_INSTRUCTIONS = """
... existing instructions ...

**Additional filtering rules:**
- If an incident is identical to one in the last 24 hours, update the existing memory instead of creating a new one
- Consolidate repeated "OOMKilled" events for the same pod into a single memory with frequency count
- Don't store "all systems healthy" status checks
- Don't store "checking..." or "investigating..." intermediate steps - only store final findings

**Memory consolidation:**
- When storing incident resolutions, include: service name, root cause, resolution steps, and date
- For recurring incidents, append new occurrences to existing memory rather than creating duplicates
"""
```

After updating, re-configure project:
```python
# In mem0_client.py, add method:
def reconfigure_project(self):
    """Re-apply custom instructions after updates"""
    self._configure_project()
```

### Step 4.3: Clean Up Test Data

Before production:
```python
# Script to delete all test memories
from src.memory.mem0_client import Mem0ClientWrapper

client = Mem0ClientWrapper()

# Get all memories
all_memories = client.get_all_memories(user_id="oncall-daemon")

# Delete test memories (contain "test" keyword)
for mem in all_memories:
    if "test" in mem.get("memory", "").lower():
        client.delete_memory(mem["id"])
        print(f"Deleted test memory: {mem['id']}")

print(f"Cleanup complete. Deleted {len([m for m in all_memories if 'test' in m.get('memory', '').lower()])} test memories")
```

### Phase 4 Completion Checklist

- ⬜ Memory metrics module created
- ⬜ Manual audit run and reviewed
- ⬜ Custom instructions refined based on audit
- ⬜ Duplicate memories cleaned up
- ⬜ Test data deleted from production project
- ⬜ Memory quality >80% useful (manual review of sample)

---

## Phase 5: Testing & Validation

**Duration:** 2-3 days
**Effort:** Medium
**Risk:** Medium

### Step 5.1: Integration Tests

Create comprehensive test suite `tests/memory/test_integration.py`:

```python
"""
End-to-end memory integration tests
"""
import pytest
from src.memory.memory_manager import MemoryManager
from src.integrations.orchestrator import OnCallOrchestrator
from fastapi.testclient import TestClient
from src.api.api_server import app


@pytest.fixture
def clean_memory():
    """Clean up memory before and after tests"""
    memory = MemoryManager()

    # Clean before
    memory.client.delete_all_memories(
        user_id="oncall-daemon",
        agent_id="oncall-troubleshooter"
    )

    yield memory

    # Clean after
    memory.client.delete_all_memories(
        user_id="oncall-daemon",
        agent_id="oncall-troubleshooter"
    )


@pytest.mark.asyncio
async def test_full_incident_lifecycle(clean_memory):
    """
    Test full incident lifecycle:
    1. Daemon detects incident
    2. Stores investigation
    3. API user asks about similar issue
    4. API references daemon learning
    """
    memory = clean_memory

    # STEP 1: Daemon stores incident
    memory.store_incident_investigation(
        incident_details="proteus-prod pod OOMKilled repeatedly",
        analysis="Root cause: Memory limit 512Mi too low. Actual usage 1.8Gi. Solution: Increase to 2Gi.",
        namespace="proteus-prod",
        service="proteus",
        severity="critical",
        root_cause="Memory limit too low (512Mi vs 1.8Gi actual)",
        resolution="Increased memory limit to 2Gi in deployment"
    )

    # STEP 2: Later, API user asks similar question
    client = TestClient(app)
    response = client.post("/query", json={
        "query": "Why does proteus pod keep crashing with OOM?",
        "namespace": "proteus-prod"
    })

    assert response.status_code == 200
    data = response.json()

    # Should reference daemon learning
    assert data["memories_used"] > 0
    assert "2Gi" in data["response"] or "512Mi" in data["response"]

    print(f"✅ API successfully referenced daemon learning")


@pytest.mark.asyncio
async def test_session_continuity(clean_memory):
    """
    Test that sessions maintain context across queries
    """
    client = TestClient(app)

    # Query 1
    resp1 = client.post("/query", json={
        "query": "What's the status of proteus-dev?"
    })
    session_id = resp1.json()["session_id"]

    # Query 2 in same session
    resp2 = client.post("/query", json={
        "query": "Show me the logs for that service",
        "session_id": session_id
    })

    # Should remember "that service" = proteus-dev
    assert resp2.status_code == 200
    # mem0 should have linked "that service" to proteus-dev context


@pytest.mark.asyncio
async def test_memory_expiration(clean_memory):
    """
    Test that expired memories are not retrieved
    (Note: This test requires waiting or mocking time)
    """
    # For now, just test that expiration_type is set correctly
    memory = clean_memory

    memory.client.add_memory(
        messages=[{"role": "assistant", "content": "Temporary network blip"}],
        user_id="oncall-daemon",
        agent_id="oncall-troubleshooter",
        metadata={"type": "temporary"},
        expiration_type="temporary"  # 7-day expiration
    )

    # In production, this would expire after 7 days
    # For testing, just verify it was stored with expiration
    all_memories = memory.client.get_all_memories(
        user_id="oncall-daemon"
    )

    # mem0 API should return expiration_date field
    temp_mem = [m for m in all_memories if "Temporary network blip" in m.get("memory", "")]
    assert len(temp_mem) == 1
    # expiration_date should be set (verify in mem0 dashboard)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
```

Run all tests:
```bash
cd oncall
python -m pytest tests/memory/ -v --cov=src/memory --cov-report=html
```

### Step 5.2: Load Testing

Create `tests/memory/test_performance.py`:

```python
"""
Performance tests for memory operations
"""
import pytest
import time
from src.memory.memory_manager import MemoryManager


def test_search_latency():
    """Test that memory searches complete within acceptable time"""
    memory = MemoryManager()

    # Store 10 memories
    for i in range(10):
        memory.store_incident_investigation(
            incident_details=f"Test incident {i}",
            analysis=f"Analysis {i}",
            namespace="test",
            service="test-service",
            severity="low"
        )

    # Measure search latency
    start = time.time()
    results = memory.search_similar_incidents(
        namespace="test",
        service="test-service",
        incident_type="OOMKilled",
        limit=5
    )
    latency = time.time() - start

    print(f"Search latency: {latency*1000:.2f}ms")

    # Should complete in < 500ms
    assert latency < 0.5, f"Search too slow: {latency}s"


def test_concurrent_operations():
    """Test concurrent memory operations"""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    memory = MemoryManager()

    def add_memory(i):
        memory.store_incident_investigation(
            incident_details=f"Concurrent test {i}",
            analysis=f"Analysis {i}",
            namespace="test",
            service="test",
            severity="low"
        )

    # Add 20 memories concurrently
    start = time.time()
    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(add_memory, range(20)))
    duration = time.time() - start

    print(f"Added 20 memories in {duration:.2f}s ({duration/20*1000:.2f}ms per memory)")

    # Should handle concurrency without errors
    assert duration < 10, "Concurrent operations too slow"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
```

### Step 5.3: Manual Testing Checklist

**Daemon Mode:**
- [ ] Trigger a test incident (e.g., OOM a pod)
- [ ] Verify daemon detects and investigates
- [ ] Check mem0 dashboard - incident should be stored
- [ ] Trigger similar incident
- [ ] Verify daemon references past incident in investigation
- [ ] Check Teams notification - should mention past similar incident

**API Mode:**
- [ ] Send query via `/query` endpoint
- [ ] Verify response references daemon learnings (check `memories_used`)
- [ ] Send follow-up query in same session
- [ ] Verify session context is maintained
- [ ] Check `/session/{id}/memories` - should show conversation history
- [ ] Delete session - verify memories are removed

**Cross-Mode:**
- [ ] Daemon stores incident
- [ ] Query via API about same topic
- [ ] Verify API response includes daemon learning

### Phase 5 Completion Checklist

- ⬜ All unit tests passing
- ⬜ Integration tests passing
- ⬜ Performance tests passing (latency < 500ms)
- ⬜ Manual testing checklist complete
- ⬜ No errors in logs during testing
- ⬜ Memory dashboard shows expected data

---

## Phase 6: Production Deployment

**Duration:** 1-2 days
**Effort:** Low-Medium
**Risk:** Low (with feature flag)

### Step 6.1: Environment Configuration

Update production `.env`:
```bash
# Production .env
MEM0_API_KEY=m0-prod-key-here
MEM0_ENABLED=true
MEM0_SEARCH_LIMIT=5
MEM0_EXPIRATION_DAYS=90

# Start with free tier, upgrade to Pro if needed
# Pro tier: $249/month for unlimited memories
```

### Step 6.2: Docker Configuration

Update `docker-compose.yml`:

```yaml
version: '3.8'

services:
  oncall-agent-daemon:
    build: .
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - MEM0_API_KEY=${MEM0_API_KEY}  # Add this
      - MEM0_ENABLED=${MEM0_ENABLED:-true}
      - MEM0_SEARCH_LIMIT=${MEM0_SEARCH_LIMIT:-5}
      - K8S_CONTEXT=dev-eks
      # ... other env vars ...
    volumes:
      - ~/.kube/config:/root/.kube/config:ro
    restart: unless-stopped

  oncall-agent-api:
    build: .
    command: uvicorn src.api.api_server:app --host 0.0.0.0 --port 8000
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - MEM0_API_KEY=${MEM0_API_KEY}  # Add this
      - MEM0_ENABLED=${MEM0_ENABLED:-true}
      - MEM0_SEARCH_LIMIT=${MEM0_SEARCH_LIMIT:-5}
      # ... other env vars ...
    ports:
      - "8000:8000"
    restart: unless-stopped
```

Update `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/
COPY tests/ ./tests/

# Run daemon by default
CMD ["python", "-m", "src.integrations.orchestrator"]
```

### Step 6.3: Kubernetes Deployment

Update `k8s/deployment.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: oncall-agent-secrets
  namespace: monitoring
type: Opaque
stringData:
  anthropic-api-key: ${ANTHROPIC_API_KEY}
  mem0-api-key: ${MEM0_API_KEY}  # Add this
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oncall-agent-daemon
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app: oncall-agent-daemon
  template:
    metadata:
      labels:
        app: oncall-agent-daemon
    spec:
      containers:
      - name: oncall-agent
        image: your-registry/oncall-agent:v2.0.0-mem0  # Tag with mem0 version
        env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: oncall-agent-secrets
              key: anthropic-api-key
        - name: MEM0_API_KEY  # Add this
          valueFrom:
            secretKeyRef:
              name: oncall-agent-secrets
              key: mem0-api-key
        - name: MEM0_ENABLED
          value: "true"
        - name: MEM0_SEARCH_LIMIT
          value: "5"
        # ... other env vars ...
```

### Step 6.4: Gradual Rollout Plan

**Phase 1: Feature Flag (Week 1)**
```bash
# Deploy with mem0 disabled initially
MEM0_ENABLED=false

# Verify everything works without mem0
# Then enable for daemon mode only
MEM0_ENABLED=true  # In daemon deployment only
```

**Phase 2: Monitor (Week 2)**
- Monitor daemon logs for mem0 errors
- Check mem0 dashboard for memory quality
- Verify Teams notifications reference past incidents
- Track incident resolution times

**Phase 3: Full Rollout (Week 3)**
```bash
# Enable for API mode
MEM0_ENABLED=true  # In API deployment
```

**Phase 4: Optimize (Week 4)**
- Review memory metrics
- Tune `SEARCH_LIMIT` if needed
- Adjust expiration periods
- Clean up duplicate memories

### Step 6.5: Monitoring Setup

Create CloudWatch dashboard or Grafana panel:

```python
# Add to src/utils/memory_metrics.py

def log_memory_metrics():
    """Log metrics for CloudWatch/Grafana"""
    metrics = MemoryMetrics()
    stats = metrics.get_memory_stats()

    logger.info("mem0_total_memories", extra={
        "metric_value": stats["total_memories"],
        "metric_type": "gauge"
    })

    for category, count in stats["category_breakdown"].items():
        logger.info(f"mem0_category_{category}", extra={
            "metric_value": count,
            "metric_type": "gauge"
        })

# Call this in orchestrator.py every 15 minutes
```

Track these metrics:
- `mem0_total_memories` - Total memories stored
- `mem0_searches_per_hour` - Search query rate
- `mem0_search_latency_ms` - Average search time
- `mem0_memories_used_per_incident` - How many memories retrieved per investigation
- `incident_resolution_time_seconds` - Before/after comparison

### Phase 6 Completion Checklist

- ⬜ Production API key obtained and secured
- ⬜ Docker configuration updated
- ⬜ Kubernetes secrets created
- ⬜ Feature flag tested (disable/enable works)
- ⬜ Gradual rollout plan documented
- ⬜ Monitoring dashboard created
- ⬜ Runbook updated with mem0 operations
- ⬜ Team trained on mem0 dashboard

---

## Monitoring & Operations

### Daily Operations

**mem0 Dashboard Review (5 min/day):**
1. Login to https://mem0.ai/dashboard
2. Check memory count (should grow steadily, not exponentially)
3. Review recent memories - spot check quality
4. Look for duplicates or noise

**Metrics to Watch:**
- Memory count growth rate (should be ~10-20/day in steady state)
- Search latency (should stay < 300ms)
- Memory category distribution (incidents should be majority)

### Weekly Maintenance

**Memory Quality Audit (15 min/week):**
```bash
cd oncall
python -m src.utils.memory_metrics > memory_audit_$(date +%Y%m%d).json
```

Review output:
- Duplicate count - should be < 5
- Stale count - prune if > 50
- Total memories - should be < 1000 for free tier

**Clean Up Old Memories:**
```python
from src.memory.mem0_client import Mem0ClientWrapper
from datetime import datetime, timedelta

client = Mem0ClientWrapper()
all_memories = client.get_all_memories(user_id="oncall-daemon")

# Delete memories older than 90 days
cutoff = datetime.now() - timedelta(days=90)
for mem in all_memories:
    created = datetime.fromisoformat(mem["created_at"].replace("Z", "+00:00"))
    if created < cutoff:
        client.delete_memory(mem["id"])
```

### Monthly Review

**Impact Analysis (30 min/month):**
1. Compare incident resolution times (before/after mem0)
2. Review LLM token usage reduction
3. Check Teams notification quality improvements
4. Survey team: "Has oncall agent improved?"

**Cost Review:**
- Free tier: 10K memories (sufficient?)
- Pro tier: $249/month (if needed)
- Compare to engineering time savings

---

## Rollback Strategy

### Quick Disable (< 1 minute)

```bash
# Set feature flag to false
kubectl set env deployment/oncall-agent-daemon MEM0_ENABLED=false -n monitoring
kubectl set env deployment/oncall-agent-api MEM0_ENABLED=false -n monitoring

# Pods will restart with mem0 disabled
```

Agents will work normally without mem0 (graceful degradation).

### Full Removal (if needed)

1. **Disable mem0:**
   ```bash
   MEM0_ENABLED=false
   ```

2. **Remove code (optional):**
   ```bash
   git revert <mem0-integration-commit>
   # Or create a branch without mem0 code
   ```

3. **Clean up dependencies:**
   ```bash
   pip uninstall mem0ai
   # Remove from requirements.txt
   ```

4. **Preserve data (optional):**
   - Export memories before deleting project
   - Keep for historical analysis

### Rollback Decision Criteria

Rollback if:
- mem0 API has >1 hour outage
- Search latency consistently > 1 second
- Memory quality audit shows >50% noise
- Cost exceeds $500/month without ROI

---

## Success Criteria

### After 2 Weeks

- ✅ 20+ incidents stored in memory
- ✅ API mode can reference daemon learnings
- ✅ No mem0-related errors in logs
- ✅ Memory quality audit: <10% duplicates

### After 1 Month

- ✅ 50% reduction in duplicate investigations
- ✅ 30% faster incident resolution times
- ✅ Positive team feedback on agent improvements
- ✅ ROI justifies $249/month Pro plan (if upgraded)

### After 3 Months

- ✅ 75% reduction in repeated similar investigations
- ✅ Agent proactively suggests solutions from past incidents
- ✅ Teams notifications reference past resolutions
- ✅ n8n users report more helpful responses

---

## Cost Summary

| Phase | Timeline | mem0 Tier | Cost |
|-------|----------|-----------|------|
| **Testing** | Week 1-2 | Free | $0 |
| **Validation** | Week 3-4 | Free | $0 |
| **Production** | Month 2+ | Free or Pro | $0 or $249/mo |

**Startup Program:** If <$5M funding, apply for 3 months free Pro (https://mem0.ai/startup-program)

**Break-even:** If mem0 saves >5 hours/month of engineering time, it pays for itself at Pro pricing.

---

## Resources

- **mem0 Documentation:** https://docs.mem0.ai
- **mem0 Dashboard:** https://mem0.ai/dashboard
- **Support:** support@mem0.ai
- **GitHub Issues:** https://github.com/mem0ai/mem0/issues
- **This Implementation Plan:** `docs/implementations/mem0-oncall-implementation-plan.md`
- **k8s-monitor Plan (Next):** `docs/implementations/mem0-k8s-monitor-implementation-plan.md`

---

## Next Steps

After completing oncall integration:
1. Measure impact for 2-4 weeks
2. Create similar plan for k8s-monitor agent
3. Evaluate OSS self-hosted option if costs exceed budget
4. Consider advanced features (graph memory, custom embeddings)

---

**Document Version:** 1.0
**Last Updated:** 2025-11-12
**Author:** AI Implementation Team
**Status:** Ready for Implementation
