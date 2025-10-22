"""Formatting utilities for maintaining clean conversation history."""

import logging
from typing import Optional
from datetime import datetime


class ConversationFormatter:
    """Formats K8s data and analysis into clean conversation messages.

    This class handles formatting Kubernetes state and Claude's analysis into
    clean, readable messages suitable for long-context conversation.
    """

    def __init__(self):
        """Initialize the formatter."""
        self.logger = logging.getLogger(__name__)

    def format_cluster_state_message(
        self,
        cycle_num: int,
        k8s_data: dict,
        previous_summary: Optional[str] = None
    ) -> str:
        """Format Kubernetes cluster state into conversation message.

        Args:
            cycle_num: Monitoring cycle number
            k8s_data: Raw K8s cluster data dictionary
            previous_summary: Optional previous cycle's summary for reference

        Returns:
            Formatted user message for Claude
        """
        # Extract key metrics
        node_count = k8s_data.get("node_count", 0)
        pod_count = k8s_data.get("pod_count", 0)
        healthy_pods = k8s_data.get("healthy_pods", pod_count)
        failed_pods = pod_count - healthy_pods if pod_count > 0 else 0
        namespace_count = k8s_data.get("namespace_count", 0)

        # Format issues
        critical_issues = k8s_data.get("critical_issues", [])
        warnings = k8s_data.get("warnings", [])

        message = f"""## Monitoring Cycle #{cycle_num}
**Timestamp**: {datetime.now().isoformat()}

### Current Cluster State
- **Nodes**: {node_count}
- **Pods**: {healthy_pods}/{pod_count} healthy ({failed_pods} failed/pending)
- **Namespaces**: {namespace_count}

### Critical Issues ({len(critical_issues)})
{self._format_issues(critical_issues) if critical_issues else "None"}

### Warnings ({len(warnings)})
{self._format_issues(warnings) if warnings else "None"}

### Analysis Request
Please provide:
1. **New Issues**: Anything not seen in previous cycles
2. **Recurring Patterns**: Issues that keep appearing
3. **Improvements**: Issues that have been resolved
4. **Risk Assessment**: What needs escalation
5. **Trend Analysis**: Are things improving or degrading?
"""

        if previous_summary:
            message += f"\n### Previous Cycle Summary\n{previous_summary}\n"

        return message

    def _format_issues(self, issues: list[str], max_display: int = 5) -> str:
        """Format issue list for readability.

        Args:
            issues: List of issue strings
            max_display: Maximum issues to display

        Returns:
            Formatted issue string
        """
        if not issues:
            return "None"

        # Limit to max_display issues
        displayed = issues[:max_display]
        formatted = "\n".join(f"- {issue}" for issue in displayed)

        # Add indicator if truncated
        if len(issues) > max_display:
            formatted += f"\n- ... and {len(issues) - max_display} more"

        return formatted

    def format_analysis_summary(self, analysis: str, max_length: int = 500) -> dict:
        """Extract structured data from Claude's analysis.

        Args:
            analysis: Full analysis text from Claude
            max_length: Maximum length for summary

        Returns:
            Dict with full_analysis, summary, and metadata
        """
        summary = analysis[:max_length] + "..." if len(analysis) > max_length else analysis

        return {
            "full_analysis": analysis,
            "summary": summary,
            "timestamp": datetime.now().isoformat(),
            "length": len(analysis),
            "was_truncated": len(analysis) > max_length
        }

    def format_trend_analysis_message(
        self,
        cycle_num: int,
        current_state: dict,
        trend_metrics: dict,
        previous_cycles: int = 5
    ) -> str:
        """Format a message specifically for trend analysis across multiple cycles.

        Args:
            cycle_num: Current cycle number
            current_state: Current cluster state
            trend_metrics: Dict with trend_direction, issue_frequency, resolved_count
            previous_cycles: Number of previous cycles considered

        Returns:
            Formatted message for trend analysis
        """
        trend_direction = trend_metrics.get("trend_direction", "stable")
        issue_frequency = trend_metrics.get("issue_frequency", 0)
        resolved_count = trend_metrics.get("resolved_count", 0)

        message = f"""## Trend Analysis - Cycle #{cycle_num}
**Analysis Period**: Last {previous_cycles} cycles
**Timestamp**: {datetime.now().isoformat()}

### Cluster Stability
- **Overall Trend**: {trend_direction}
- **Issue Frequency**: {issue_frequency} issues per cycle (average)
- **Resolved Issues**: {resolved_count} issues resolved

### Current State
- **Nodes**: {current_state.get('node_count', 0)}
- **Healthy Pods**: {current_state.get('healthy_pods', 0)}/{current_state.get('pod_count', 0)}
- **Critical Issues**: {len(current_state.get('critical_issues', []))}

### Questions for Analysis
1. Is cluster health improving, degrading, or stable?
2. Are there patterns in issue occurrence times?
3. Which systems are most problematic?
4. What preventive actions are recommended?
"""
        return message

    def extract_action_items(
        self,
        analysis: str,
        keywords: Optional[list[str]] = None
    ) -> list[dict]:
        """Extract actionable recommendations from Claude's analysis.

        Args:
            analysis: Full analysis text
            keywords: Optional keywords to search for (e.g., ["should", "must", "recommend"])

        Returns:
            List of dicts with action_text and confidence
        """
        if keywords is None:
            keywords = ["should", "must", "recommend", "need", "require"]

        action_items = []
        lines = analysis.split("\n")

        for line in lines:
            line_lower = line.lower()
            for keyword in keywords:
                if keyword in line_lower and len(line.strip()) > 10:
                    action_items.append({
                        "action_text": line.strip(),
                        "keyword": keyword,
                        "confidence": "high" if keyword in ["must", "should"] else "medium"
                    })
                    break

        return action_items[:10]  # Limit to 10 action items

    def format_conversation_context_summary(self, messages: list[dict]) -> str:
        """Create a summary of conversation context for new users/operations.

        Args:
            messages: Full conversation history

        Returns:
            Formatted context summary
        """
        if not messages:
            return "No conversation history available."

        # Count message types
        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")

        # Extract last few summaries from assistant messages
        last_summaries = []
        for msg in reversed(messages[-10:]):  # Look at last 10 messages
            if msg.get("role") == "assistant":
                text = msg.get("content", "")
                if len(text) > 50:
                    preview = text[:200] + "..." if len(text) > 200 else text
                    last_summaries.append(preview)

        summary = f"""## Conversation Context Summary

- **Total Messages**: {len(messages)} ({user_msgs} user, {assistant_msgs} assistant)
- **Conversation Depth**: {user_msgs} monitoring cycles analyzed

### Recent Analysis Themes
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(last_summaries[:3]))}

This conversation has maintained continuous context across all monitoring cycles,
enabling trend detection and pattern recognition that improves over time.
"""
        return summary

    def validate_message_format(self, message: dict) -> bool:
        """Validate that a message follows expected format.

        Args:
            message: Message dict to validate

        Returns:
            True if valid, False otherwise
        """
        required_fields = ["role", "content"]
        valid_roles = ["user", "assistant", "system"]

        if not isinstance(message, dict):
            return False

        if not all(field in message for field in required_fields):
            return False

        if message.get("role") not in valid_roles:
            return False

        if not isinstance(message.get("content"), str):
            return False

        return True

    def sanitize_message_content(self, content: str, max_length: int = 10000) -> str:
        """Sanitize message content for safety and performance.

        Args:
            content: Raw message content
            max_length: Maximum allowed length

        Returns:
            Sanitized content
        """
        # Remove null characters
        sanitized = content.replace("\x00", "")

        # Limit length
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length] + "\n[... truncated ...]"

        return sanitized
