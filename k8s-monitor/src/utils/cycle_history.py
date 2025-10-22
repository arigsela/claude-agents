"""Cycle history manager for tracking findings across monitoring cycles."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models import Finding


class CycleHistory:
    """Manages historical cycle data for trend analysis."""

    def __init__(
        self,
        history_dir: Path = Path("logs"),
        max_history_cycles: int = 5,
        max_history_hours: int = 24,
    ):
        """Initialize cycle history manager.

        Args:
            history_dir: Directory containing cycle reports
            max_history_cycles: Maximum number of previous cycles to load
            max_history_hours: Maximum age of cycles to consider (in hours)
        """
        self.history_dir = history_dir
        self.max_history_cycles = max_history_cycles
        self.max_history_hours = max_history_hours
        self.logger = logging.getLogger(__name__)

    def load_recent_cycles(self) -> List[Dict[str, Any]]:
        """Load recent cycle reports for context.

        Returns:
            List of cycle reports sorted by timestamp (newest first)
        """
        try:
            # Find all cycle report files
            cycle_files = sorted(
                self.history_dir.glob("cycle_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

            if not cycle_files:
                self.logger.info("No previous cycle reports found")
                return []

            # Filter by age and limit count
            cutoff_time = datetime.now() - timedelta(hours=self.max_history_hours)
            recent_cycles = []

            for cycle_file in cycle_files[: self.max_history_cycles]:
                try:
                    # Check file modification time
                    file_time = datetime.fromtimestamp(cycle_file.stat().st_mtime)
                    if file_time < cutoff_time:
                        continue

                    # Load cycle data
                    with open(cycle_file) as f:
                        cycle_data = json.load(f)

                    recent_cycles.append(cycle_data)

                except Exception as e:
                    self.logger.warning(f"Error loading cycle file {cycle_file}: {e}")
                    continue

            self.logger.info(
                f"Loaded {len(recent_cycles)} recent cycles from last {self.max_history_hours}h"
            )
            return recent_cycles

        except Exception as e:
            self.logger.error(f"Error loading cycle history: {e}", exc_info=True)
            return []

    def format_history_summary(self, cycles: List[Dict[str, Any]]) -> str:
        """Format cycle history into a summary for Claude's context.

        Args:
            cycles: List of cycle reports

        Returns:
            Formatted summary string
        """
        if not cycles:
            return "No previous cycle history available."

        summary_parts = [
            f"## PREVIOUS CYCLES (Last {len(cycles)} cycles)",
            "",
        ]

        for idx, cycle in enumerate(cycles, 1):
            cycle_id = cycle.get("cycle_id", "unknown")
            status = cycle.get("status", "unknown")
            findings = cycle.get("findings", [])
            timestamp = cycle.get("cycle_id", "").split("_")

            summary_parts.append(f"### Cycle {idx}: {cycle_id} ({status})")

            if findings:
                summary_parts.append(f"**{len(findings)} issues detected:**")
                for finding in findings[:5]:  # Limit to top 5 per cycle
                    service = finding.get("service", "unknown")
                    severity = finding.get("severity", "unknown")
                    description = finding.get("description", "")
                    summary_parts.append(f"  - {service} [{severity}]: {description}")

                if len(findings) > 5:
                    summary_parts.append(f"  ... and {len(findings) - 5} more issues")
            else:
                summary_parts.append("**No issues detected**")

            summary_parts.append("")

        return "\n".join(summary_parts)

    def detect_recurring_issues(
        self, current_findings: List[Finding], cycles: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Detect recurring issues across cycles.

        Args:
            current_findings: Current cycle findings
            cycles: Previous cycle reports

        Returns:
            Dictionary with recurring issue analysis
        """
        recurring_analysis = {
            "new_issues": [],
            "recurring_issues": [],
            "resolved_issues": [],
            "worsening_trends": [],
        }

        if not cycles:
            # All current findings are new
            recurring_analysis["new_issues"] = [
                f.service for f in current_findings if hasattr(f, "service")
            ]
            return recurring_analysis

        # Extract services/issues from previous cycles
        previous_issues = set()
        for cycle in cycles:
            for finding in cycle.get("findings", []):
                service = finding.get("service")
                if service:
                    previous_issues.add(service)

        # Current issues
        current_issues = {f.service for f in current_findings if hasattr(f, "service")}

        # Classify issues
        recurring_analysis["new_issues"] = list(current_issues - previous_issues)
        recurring_analysis["recurring_issues"] = list(
            current_issues & previous_issues
        )
        recurring_analysis["resolved_issues"] = list(
            previous_issues - current_issues
        )

        # Detect worsening trends (same service appearing in multiple consecutive cycles)
        service_frequency = {}
        for cycle in cycles[:3]:  # Check last 3 cycles
            for finding in cycle.get("findings", []):
                service = finding.get("service")
                if service:
                    service_frequency[service] = service_frequency.get(service, 0) + 1

        # Services appearing in 2+ of last 3 cycles
        recurring_analysis["worsening_trends"] = [
            service
            for service, count in service_frequency.items()
            if count >= 2 and service in current_issues
        ]

        self.logger.info(
            f"Issue classification: {len(recurring_analysis['new_issues'])} new, "
            f"{len(recurring_analysis['recurring_issues'])} recurring, "
            f"{len(recurring_analysis['resolved_issues'])} resolved, "
            f"{len(recurring_analysis['worsening_trends'])} worsening"
        )

        return recurring_analysis

    def get_service_history(
        self, service_name: str, cycles: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Get historical findings for a specific service.

        Args:
            service_name: Name of the service to track
            cycles: Previous cycle reports

        Returns:
            List of findings for this service across cycles
        """
        service_history = []

        for cycle in cycles:
            cycle_id = cycle.get("cycle_id", "unknown")
            for finding in cycle.get("findings", []):
                if finding.get("service") == service_name:
                    service_history.append(
                        {
                            "cycle_id": cycle_id,
                            "severity": finding.get("severity"),
                            "description": finding.get("description"),
                            "timestamp": cycle_id,
                        }
                    )

        return service_history
