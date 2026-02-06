"""
Pydantic models for Microsoft Teams Outgoing Webhook integration.

These models handle incoming webhook payloads from Teams and
format responses as Adaptive Cards for display in Teams channels.

Uses Pydantic v2 syntax.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TeamsFrom(BaseModel):
    """User who sent the message in Teams."""

    id: str
    name: str
    aadObjectId: str | None = None


class TeamsConversation(BaseModel):
    """Teams conversation context."""

    id: str
    conversationType: str | None = None
    tenantId: str | None = None
    name: str | None = None


class TeamsActivity(BaseModel):
    """
    Teams Activity payload for Outgoing Webhook.

    This is the payload Teams sends when a user @mentions
    the bot in a channel.
    """

    type: str  # "message"
    id: str
    timestamp: str
    text: str  # User's message (includes @mention)
    from_: TeamsFrom = Field(alias="from")
    conversation: TeamsConversation
    channelId: str = "msteams"
    serviceUrl: str

    model_config = ConfigDict(populate_by_name=True)


class TeamsResponse(BaseModel):
    """Teams webhook response with Adaptive Card."""

    type: str = "message"
    attachments: list[dict[str, Any]]


def create_adaptive_card_response(
    text: str, title: str | None = None, theme: str = "default"
) -> TeamsResponse:
    """
    Create Adaptive Card response for Teams.

    Builds a simple Adaptive Card with a text block that supports
    a subset of markdown formatting.

    Args:
        text: Response text (supports bold, italic, links, code blocks)
        title: Optional title for the card
        theme: Card theme - 'default', 'good' (green), 'attention' (yellow), 'warning' (red)

    Returns:
        TeamsResponse with Adaptive Card attachment ready to send to Teams
    """
    # Map theme to accent color
    accent_colors = {
        "default": None,
        "good": "good",
        "attention": "attention",
        "warning": "warning",
    }

    body: list[dict[str, Any]] = []

    # Add title if provided
    if title:
        body.append(
            {"type": "TextBlock", "text": title, "wrap": True, "weight": "Bolder", "size": "Medium"}
        )

    # Add main text
    body.append({"type": "TextBlock", "text": text, "wrap": True, "size": "Default"})

    card: dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }

    # Add colored accent bar if theme specified
    accent_color = accent_colors.get(theme)
    if accent_color:
        card["style"] = accent_color

    return TeamsResponse(
        type="message",
        attachments=[{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}],
    )


def create_error_card(error_message: str, error_type: str = "Error") -> TeamsResponse:
    """
    Create an error Adaptive Card for Teams.

    Args:
        error_message: Description of the error
        error_type: Type of error (e.g., "Error", "Timeout", "Configuration")

    Returns:
        TeamsResponse with error card
    """
    return create_adaptive_card_response(text=f"**{error_type}**: {error_message}", theme="warning")


def create_welcome_card() -> TeamsResponse:
    """
    Create a welcome Adaptive Card for empty messages.

    Returns:
        TeamsResponse with welcome message
    """
    welcome_text = """**Hi! I'm the OnCall troubleshooting agent.**

I can help you with:
- Kubernetes cluster health checks
- Pod troubleshooting and log analysis
- Deployment status and recent changes
- NAT gateway traffic analysis
- Zeus job correlation

**Try asking me:**
- "Check artemis-auth health"
- "What pods are failing in proteus-dev?"
- "Show recent deployments for hermes"
"""
    return create_adaptive_card_response(text=welcome_text, title="OnCall Agent", theme="default")
