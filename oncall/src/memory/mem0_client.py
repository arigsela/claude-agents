"""
mem0 client wrapper with retry logic and error handling
"""
import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from mem0 import MemoryClient

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
            # Return error dict instead of raising to prevent breaking the flow
            return {"error": str(e), "skipped": True}

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
            # mem0 API requires filters parameter
            # If no filters specified, use wildcard to match all memories for the user
            if not filters:
                # Use wildcard filter to match all memories (based on mem0 docs)
                filters = {"AND": [{"user_id": user_id}]}

            search_params = {
                "query": query,
                "user_id": user_id,
                "filters": filters,
                "limit": limit
            }

            # Only add agent_id if provided
            if agent_id:
                search_params["agent_id"] = agent_id

            logger.debug(f"Searching mem0 with params: {search_params}")
            result = self.client.search(**search_params)
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
            # mem0 API changed - get_all now requires filters
            # Use search with wildcard query to get all memories
            result = self.search_memories(
                query="*",  # Wildcard to match all
                user_id=user_id,
                agent_id=agent_id,
                filters={"AND": [{"user_id": user_id}]},
                limit=100  # Get up to 100 memories
            )
            return result
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
