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


def _split_text_into_blocks(text: str, max_len: int = 2900) -> list[dict]:
    """Split long text into multiple section blocks respecting Slack's 3000 char limit.

    Tries to split at paragraph boundaries (double newlines), then single newlines,
    then hard-truncates as a last resort.
    """
    if len(text) <= max_len:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    blocks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": remaining}})
            break

        # Try to split at a paragraph boundary
        split_at = remaining.rfind("\n\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            # Try single newline
            split_at = remaining.rfind("\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            # Hard split
            split_at = max_len

        chunk = remaining[:split_at].rstrip()
        remaining = remaining[split_at:].lstrip()
        if chunk:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})

    return blocks


def format_query_response(text: str, query: str, duration_ms: float) -> list[dict]:
    """Format agent response as Slack Block Kit blocks.

    Args:
        text: Agent response text
        query: Original user query
        duration_ms: Processing duration in milliseconds

    Returns:
        List of Block Kit block dicts
    """
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Query:* `{query}`"},
        },
        {"type": "divider"},
    ]

    # Split response into multiple blocks if needed (Slack 3000 char limit per block)
    blocks.extend(_split_text_into_blocks(text))

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
