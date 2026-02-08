"""
Pydantic models and Block Kit formatters for Slack integration.
"""

from pydantic import BaseModel, Field


class SlackSlashCommand(BaseModel):
    """Parse incoming Slack slash command payload (application/x-www-form-urlencoded)."""

    token: str = Field(default="", description="Verification token (deprecated, use signing secret)")
    command: str = Field(..., description="The slash command that was typed (e.g., /oncall)")
    text: str = Field(default="", description="Text after the command")
    response_url: str = Field(..., description="URL to send deferred responses to")
    trigger_id: str = Field(default="", description="Trigger ID for opening modals")
    user_id: str = Field(..., description="Slack user ID")
    user_name: str = Field(default="", description="Slack username")
    channel_id: str = Field(default="", description="Channel where command was invoked")
    channel_name: str = Field(default="", description="Channel name")
    team_id: str = Field(default="", description="Slack team/workspace ID")


def format_query_response(text: str, query: str, duration_ms: float) -> list[dict]:
    """Format agent response as Slack Block Kit blocks.

    Args:
        text: Agent response text
        query: Original user query
        duration_ms: Processing duration in milliseconds

    Returns:
        List of Block Kit block dicts
    """
    # Slack Block Kit section text limit is 3000 chars.
    # Split long responses into multiple section blocks.
    max_section_len = 2900  # Leave margin for safety

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Query:* `{query[:200]}`"},
        },
        {"type": "divider"},
    ]

    # Split text into chunks that fit within Slack's limit
    remaining = text
    while remaining:
        chunk = remaining[:max_section_len]
        remaining = remaining[max_section_len:]

        # Try to break at a newline to avoid splitting mid-sentence
        if remaining and "\n" in chunk[max_section_len // 2 :]:
            break_at = chunk.rfind("\n", max_section_len // 2)
            remaining = chunk[break_at + 1 :] + remaining
            chunk = chunk[: break_at + 1]

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": chunk},
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Processed in {duration_ms:.0f}ms | OnCall Agent",
                }
            ],
        },
    )
    return blocks


def format_incident_alert(
    alert: dict, analysis: list, severity: str
) -> list[dict]:
    """Format incident alert as Slack Block Kit blocks with severity color coding.

    Args:
        alert: Alert dict with service, namespace, error, etc.
        analysis: List of ResponseMessage-like dicts with analysis text
        severity: Severity level (critical, high, medium, low)

    Returns:
        List of Block Kit block dicts
    """
    severity_emoji = {
        "critical": ":red_circle:",
        "high": ":large_orange_circle:",
        "medium": ":large_yellow_circle:",
        "low": ":white_circle:",
    }
    emoji = severity_emoji.get(severity, ":white_circle:")

    service = alert.get("service", "unknown")
    namespace = alert.get("namespace", "unknown")
    error = alert.get("error", "unknown")
    restart_count = alert.get("restart_count", 0)

    # Combine analysis text
    analysis_text = ""
    for item in analysis:
        content = item.get("content", "") if isinstance(item, dict) else getattr(item, "content", "")
        if content:
            analysis_text += content + "\n"
    analysis_text = analysis_text.strip() or "No detailed analysis available."

    # Truncate if too long for Slack (max 3000 chars per text block)
    if len(analysis_text) > 2900:
        analysis_text = analysis_text[:2900] + "\n... _(truncated)_"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Incident Alert: {service}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Service:*\n{service}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{severity.upper()}"},
                {"type": "mrkdwn", "text": f"*Namespace:*\n{namespace}"},
                {"type": "mrkdwn", "text": f"*Restarts:*\n{restart_count}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Error:*\n```{error}```"},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Analysis:*\n{analysis_text}"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "OnCall Agent | Automated Incident Analysis"}
            ],
        },
    ]
    return blocks
