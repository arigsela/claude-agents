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
        # Note: mem0 API requires filters if provided, so we pass None to use defaults
        return self.client.search_memories(
            query=query,
            user_id=f"api-session-{session_id}",
            agent_id=self.agent_id,
            filters=None,  # Don't pass empty dict, use None
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
        # Don't filter by metadata for now - just search all daemon memories
        return self.client.search_memories(
            query=query,
            user_id=self.daemon_user_id,
            agent_id=self.agent_id,
            filters=None,
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
