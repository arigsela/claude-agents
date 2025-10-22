"""Model Inspector - Identifies which models are being used by Claude Agent SDK.

This module provides comprehensive logging and inspection of the Claude Agent SDK
to identify exactly which model each subagent is using at runtime.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from claude_agent_sdk import ClaudeSDKClient


class ModelInspector:
    """Inspects and logs model usage from Claude Agent SDK."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize model inspector.

        Args:
            logger: Logger instance (creates one if not provided)
        """
        self.logger = logger or logging.getLogger(__name__)
        self.model_usage_log: List[Dict[str, Any]] = []
        self.model_file = Path("logs/model_usage.jsonl")

    async def inspect_client_initialization(self, client: ClaudeSDKClient) -> Dict[str, str]:
        """Inspect ClaudeSDKClient to extract model information.

        Args:
            client: Initialized ClaudeSDKClient instance

        Returns:
            Dictionary mapping agent names to their models
        """
        models = {}

        self.logger.info("=" * 80)
        self.logger.info("🔍 CLAUDE AGENT SDK MODEL INSPECTION")
        self.logger.info("=" * 80)

        try:
            # Inspect the client's options
            if hasattr(client, "options"):
                options = client.options
                self.logger.info("Client Options Available ✓")

                # Check main model
                if hasattr(options, "model"):
                    main_model = options.model
                    self.logger.info(f"  Orchestrator Model: {main_model}")
                    models["orchestrator"] = main_model

                # Check if there's an agents configuration
                if hasattr(options, "setting_sources"):
                    self.logger.info(
                        f"  Setting Sources: {options.setting_sources}"
                    )

                # Try to find subagent definitions
                if hasattr(options, "agents"):
                    self.logger.info("  Subagent Definitions Found:")
                    for agent_name, agent_config in options.agents.items():
                        if isinstance(agent_config, dict):
                            agent_model = agent_config.get("model", "UNKNOWN")
                            self.logger.info(
                                f"    - {agent_name}: {agent_model}"
                            )
                            models[agent_name] = agent_model

        except Exception as e:
            self.logger.warning(f"Could not inspect client options: {e}")

        # Log findings
        self._log_model_inspection(models)
        self.logger.info("=" * 80)

        return models

    async def inspect_subagent_response(
        self, subagent_name: str, response_metadata: Optional[Dict] = None
    ) -> Optional[str]:
        """Extract model information from subagent response metadata.

        Args:
            subagent_name: Name of the subagent
            response_metadata: Optional metadata from response

        Returns:
            Model name if found
        """
        model = None

        if response_metadata:
            # Try to extract model from response metadata
            if "model" in response_metadata:
                model = response_metadata["model"]
                self.logger.info(
                    f"📊 Subagent '{subagent_name}' used model: {model}"
                )
            elif "usage" in response_metadata:
                usage = response_metadata["usage"]
                if isinstance(usage, dict) and "model" in usage:
                    model = usage["model"]
                    self.logger.info(
                        f"📊 Subagent '{subagent_name}' used model: {model}"
                    )

        return model

    async def trace_api_calls(
        self, client: ClaudeSDKClient, query: str
    ) -> Dict[str, Any]:
        """Trace API calls made by the client to identify models.

        This method instruments the client to log each API call and extract
        the model being used.

        Args:
            client: ClaudeSDKClient instance
            query: Query to send to the client

        Returns:
            Dictionary with API call details and model usage
        """
        trace_data = {
            "timestamp": datetime.now().isoformat(),
            "query": query[:100],  # First 100 chars
            "api_calls": [],
            "models_detected": set(),
        }

        self.logger.info(f"📡 Tracing API calls for query: {query[:80]}...")

        try:
            # Send query
            await client.query(query)

            # Collect responses and try to extract model info
            async for message in client.receive_response():
                msg_type = type(message).__name__
                self.logger.debug(f"  → Received: {msg_type}")

                # Try to extract model from message
                if hasattr(message, "model"):
                    model = message.model
                    trace_data["models_detected"].add(model)
                    self.logger.info(f"  ✓ Detected model in response: {model}")

                if hasattr(message, "metadata"):
                    metadata = message.metadata
                    if isinstance(metadata, dict) and "model" in metadata:
                        model = metadata["model"]
                        trace_data["models_detected"].add(model)
                        self.logger.info(
                            f"  ✓ Detected model in metadata: {model}"
                        )

        except Exception as e:
            self.logger.warning(f"Error tracing API calls: {e}")
            trace_data["error"] = str(e)

        # Convert set to list for JSON serialization
        trace_data["models_detected"] = list(trace_data["models_detected"])

        # Log trace
        self._log_trace(trace_data)

        return trace_data

    def _log_model_inspection(self, models: Dict[str, str]) -> None:
        """Log model inspection results.

        Args:
            models: Dictionary of agent names to models
        """
        self.logger.info("🔍 MODEL INSPECTION RESULTS:")
        self.logger.info("-" * 80)

        for agent_name, model in models.items():
            # Identify model type
            if "haiku" in model.lower():
                marker = "✅ HAIKU"
            elif "sonnet" in model.lower():
                marker = "⚠️ SONNET"
            else:
                marker = "❓ UNKNOWN"

            self.logger.info(f"  {marker} {agent_name:30s}: {model}")

        # Summary
        haiku_count = sum(1 for m in models.values() if "haiku" in m.lower())
        sonnet_count = sum(1 for m in models.values() if "sonnet" in m.lower())

        self.logger.info("-" * 80)
        self.logger.info(f"Summary: {haiku_count} Haiku, {sonnet_count} Sonnet")

        if sonnet_count > 0:
            self.logger.error("❌ SONNET DETECTED - This should not happen!")

        # Write to file
        self.model_file.parent.mkdir(exist_ok=True)
        with open(self.model_file, "a") as f:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "models": models,
                "haiku_count": haiku_count,
                "sonnet_count": sonnet_count,
            }
            f.write(json.dumps(log_entry) + "\n")

    def _log_trace(self, trace_data: Dict[str, Any]) -> None:
        """Log trace data to file.

        Args:
            trace_data: Trace data dictionary
        """
        # Write to file
        trace_file = Path("logs/api_trace.jsonl")
        trace_file.parent.mkdir(exist_ok=True)
        with open(trace_file, "a") as f:
            f.write(json.dumps(trace_data) + "\n")

    def print_model_summary(self) -> None:
        """Print summary of model usage from logs."""
        if not self.model_file.exists():
            self.logger.warning(
                f"Model usage log not found: {self.model_file}"
            )
            return

        self.logger.info("=" * 80)
        self.logger.info("📊 MODEL USAGE SUMMARY")
        self.logger.info("=" * 80)

        haiku_total = 0
        sonnet_total = 0

        with open(self.model_file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    haiku_total += entry.get("haiku_count", 0)
                    sonnet_total += entry.get("sonnet_count", 0)
                except json.JSONDecodeError:
                    continue

        self.logger.info(f"Total across all runs:")
        self.logger.info(f"  ✅ Haiku models: {haiku_total}")
        self.logger.info(f"  ⚠️ Sonnet models: {sonnet_total}")

        if sonnet_total > 0:
            self.logger.error(
                f"❌ WARNING: {sonnet_total} Sonnet models detected!"
            )
        else:
            self.logger.info("✅ All runs using Haiku models")

        self.logger.info("=" * 80)


# Convenience function
async def inspect_client_models(client: ClaudeSDKClient) -> Dict[str, str]:
    """Convenience function to inspect client models.

    Args:
        client: ClaudeSDKClient instance

    Returns:
        Dictionary of agent names to models
    """
    inspector = ModelInspector()
    return await inspector.inspect_client_initialization(client)
