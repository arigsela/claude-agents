# Microsoft Teams Integration for OnCall Agent

## Overview

This document outlines the implementation plan for adding Microsoft Teams channel integration to the OnCall API server. Users will be able to interact with the OnCall agent by @mentioning it in a Teams channel, with full thread-based conversation history.

## Approach: Outgoing Webhook

We chose Teams **Outgoing Webhook** because:
- Works with existing FastAPI server (no separate bot service)
- No Azure Bot registration required
- Simple HMAC authentication
- Thread responses work natively
- Mirrors existing Slack integration pattern
- Self-hosted compatible (no Azure dependencies)

### Comparison with Alternatives

| Approach | Complexity | Azure Required | Proactive Messages | Our Choice |
|----------|-----------|----------------|-------------------|------------|
| **Outgoing Webhook** | Low | No | No | **Yes** |
| Bot Framework SDK | Medium | Yes | Yes | No (archived Jan 2026) |
| Microsoft 365 Agents SDK | High | Yes | Yes | No (overkill for our needs) |

## Architecture

```
┌─────────────────┐     POST /teams/webhook      ┌─────────────────┐
│  Microsoft      │ ─────────────────────────────▶│  OnCall API     │
│  Teams          │                               │  Server         │
│  (@mention)     │ ◀───────────────────────────── │  (FastAPI)      │
└─────────────────┘     Adaptive Card Response   └────────┬────────┘
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │  Thread Storage │
                                                 │  (JSON files)   │
                                                 └─────────────────┘
                                                          │
                                                          ▼
                                                 ┌─────────────────┐
                                                 │  Agent Client   │
                                                 │  (Anthropic)    │
                                                 └─────────────────┘
```

## Request Flow

1. User @mentions the OnCall webhook in a Teams channel
2. Teams sends HTTP POST to `/teams/webhook` with activity payload
3. Server validates HMAC-SHA256 signature from Authorization header
4. Server extracts message text, thread ID, and user info
5. Server loads/creates thread history from JSON file
6. Server calls `agent_client.process_query()` with context
7. Server saves updated thread history
8. Server returns Adaptive Card response (within 5-second timeout)

## New Files

```
oncall/src/api/
├── teams_webhook.py      # FastAPI router with webhook endpoint
├── teams_models.py       # Pydantic models for Teams payloads
└── thread_storage.py     # JSON file-based thread history

oncall/data/
└── teams_threads/        # Directory for thread JSON files (gitignored)
```

## Implementation Details

### 1. Thread Storage (`thread_storage.py`)

File-based storage for conversation threads.

**File Structure:**
```
data/teams_threads/
└── {sanitized_thread_id}.json
```

**Thread Schema:**
```json
{
  "thread_id": "19:abc123@thread.tacv2",
  "channel_id": "19:channel@thread.tacv2",
  "created_at": "2025-01-13T10:00:00Z",
  "last_message_at": "2025-01-13T10:05:00Z",
  "messages": [
    {
      "role": "user",
      "content": "What pods are failing?",
      "timestamp": "2025-01-13T10:00:00Z",
      "from_name": "John Doe"
    },
    {
      "role": "assistant",
      "content": "I found 3 pods in CrashLoopBackOff...",
      "timestamp": "2025-01-13T10:00:05Z"
    }
  ]
}
```

**Key Methods:**
- `load_thread(thread_id: str) -> ThreadData` - Load or create thread
- `save_thread(data: ThreadData) -> None` - Persist to JSON file
- `append_user_message(thread_id, content, from_name) -> None`
- `append_assistant_message(thread_id, content) -> None`
- `get_anthropic_messages(thread_id) -> List[dict]` - Format for API

### 2. Teams Models (`teams_models.py`)

Pydantic models for request/response validation.

**Request Model (Teams Activity):**
```python
class TeamsFrom(BaseModel):
    id: str
    name: str
    aadObjectId: Optional[str] = None

class TeamsConversation(BaseModel):
    id: str
    conversationType: Optional[str] = None
    tenantId: Optional[str] = None
    name: Optional[str] = None

class TeamsActivity(BaseModel):
    type: str
    id: str
    timestamp: str
    text: str
    from_: TeamsFrom = Field(alias="from")
    conversation: TeamsConversation
    channelId: str = "msteams"
    serviceUrl: str
```

**Response Model (Adaptive Card):**
```python
class TeamsResponse(BaseModel):
    type: str = "message"
    attachments: List[dict]

def create_adaptive_card_response(text: str) -> TeamsResponse:
    """Create Adaptive Card response with markdown text."""
```

### 3. Teams Webhook Endpoint (`teams_webhook.py`)

FastAPI router with HMAC validation.

**Endpoint:** `POST /teams/webhook`

**HMAC Validation:**
```python
def validate_teams_hmac(body: bytes, auth_header: str, secret: str) -> bool:
    """
    Validate HMAC-SHA256 signature from Teams.

    - Secret is base64-encoded (from Teams webhook config)
    - Signature is in Authorization header: "HMAC {signature}"
    - Compare computed hash with provided signature
    """
```

**Request Processing:**
1. Read raw request body for HMAC validation
2. Validate signature (return 401 if invalid)
3. Parse JSON body into TeamsActivity model
4. Strip @mention from text (Teams includes `<at>BotName</at>`)
5. Load thread history
6. Build Anthropic messages from history
7. Call agent_client with prompt + context
8. Save thread history
9. Return Adaptive Card response

**Timeout Handling:**
- Teams has 5-second timeout
- Log warning if approaching timeout
- Return partial response if needed

### 4. Configuration

**Environment Variables:**
```bash
# Required
TEAMS_WEBHOOK_SECRET=<base64-encoded-secret-from-teams>

# Optional (with defaults)
TEAMS_THREADS_DIR=data/teams_threads
TEAMS_MAX_HISTORY_MESSAGES=20
```

**Add to `.env.example`:**
```bash
# Microsoft Teams Integration
# TEAMS_WEBHOOK_SECRET=  # Base64 secret from Teams Outgoing Webhook config
# TEAMS_THREADS_DIR=data/teams_threads
```

### 5. Integration Points

**Modify `api_server.py`:**
```python
from api.teams_webhook import router as teams_router

app.include_router(teams_router, tags=["teams"])
```

**Session ID Format:**
```python
session_id = f"teams-{conversation_id}"
```
This matches the Slack pattern: `slack-thread-{thread_ts}`

## Response Format

### Adaptive Card Structure

```json
{
  "type": "message",
  "attachments": [{
    "contentType": "application/vnd.microsoft.card.adaptive",
    "content": {
      "type": "AdaptiveCard",
      "version": "1.4",
      "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
      "body": [{
        "type": "TextBlock",
        "text": "**Response from OnCall Agent**\n\nI found 3 pods...",
        "wrap": true
      }]
    }
  }]
}
```

### Markdown Support

Adaptive Cards support a subset of markdown:
- `**bold**`, `_italic_`
- `[links](url)`
- Bullet lists with `-`
- Code blocks with triple backticks

## Error Handling

| Error | Response | HTTP Code |
|-------|----------|-----------|
| Invalid HMAC | `{"error": "Unauthorized"}` | 401 |
| Missing webhook secret | `{"error": "Teams webhook not configured"}` | 503 |
| Agent timeout | Return partial response | 200 |
| Agent error | `{"error": "Processing failed"}` | 500 |

## Testing Strategy

### Unit Tests

1. **HMAC Validation**
   - Valid signature → passes
   - Invalid signature → 401
   - Missing header → 401

2. **Thread Storage**
   - Create new thread
   - Load existing thread
   - Append messages
   - Handle invalid thread IDs

3. **Message Parsing**
   - Strip @mention correctly
   - Handle various activity formats
   - Extract user info

### Integration Tests

1. Mock Teams payload → full request flow
2. Verify Adaptive Card response format
3. Thread history persistence

### Manual Testing

```bash
# Simulate Teams webhook (for local testing)
curl -X POST http://localhost:8000/teams/webhook \
  -H "Content-Type: application/json" \
  -H "Authorization: HMAC <computed-signature>" \
  -d '{
    "type": "message",
    "text": "<at>OnCall</at> what pods are failing?",
    "from": {"id": "user123", "name": "John Doe"},
    "conversation": {"id": "19:abc@thread.tacv2"},
    "channelId": "msteams",
    "serviceUrl": "https://smba.trafficmanager.net/..."
  }'
```

## Teams Admin Setup

### Creating the Outgoing Webhook

1. Open Microsoft Teams
2. Go to the team where you want the webhook
3. Click **...** → **Manage team** → **Apps** tab
4. Click **Create an outgoing webhook**
5. Configure:
   - **Name**: OnCall (this is the @mention trigger)
   - **Callback URL**: `https://your-server.com/teams/webhook`
   - **Description**: Kubernetes troubleshooting agent
6. Click **Create**
7. **Copy the security token** - this is your `TEAMS_WEBHOOK_SECRET`

### Network Requirements

- Callback URL must be HTTPS
- Must be publicly accessible (or use ngrok for testing)
- Port 443 recommended

## Security Considerations

1. **HMAC Validation**: All requests validated before processing
2. **Secret Storage**: Webhook secret in environment variable, never logged
3. **Thread ID Sanitization**: Thread IDs sanitized before use as filenames
4. **Rate Limiting**: Existing API rate limiting applies
5. **No Sensitive Data in Logs**: User names logged, but not message content

## Future Enhancements (Out of Scope)

- Proactive notifications (requires Incoming Webhook or Bot)
- Rich card interactions (buttons, forms)
- Multi-tenant support
- Database storage for threads (vs. JSON files)

## References

- [Teams Outgoing Webhooks](https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-outgoing-webhook)
- [Adaptive Cards Schema](https://adaptivecards.io/explorer/)
- [Teams Activity Schema](https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-api-reference)
