# n8n On-Call Engineer Workflow - Microsoft Teams Integration

## Overview

This n8n workflow creates an **intelligent ChatOps assistant** for Kubernetes troubleshooting directly in Microsoft Teams. Engineers can ask questions about services, pods, and websites in Teams, and receive instant AI-powered analysis with Adaptive Card responses.

**Workflow Name**: `dev-eks-oncall-engineer-v2`
**File**: `dev-eks-oncall-engineer-v2.json`
**Last Updated**: 2025-10-10
**Status**: Production Ready ✅

---

## Key Features

### 🤖 AI-Powered Analysis
- Uses **Claude Sonnet 4** for intelligent Kubernetes troubleshooting
- Combines website health checks with deep K8s cluster analysis
- Provides actionable remediation steps

### 💬 Teams Integration
- Responds directly in Teams message threads
- Beautiful **Adaptive Card** formatting
- Includes query metadata (user, timestamp)

### 🧠 **Conversation Memory** (NEW!)
- **Multi-turn conversations** - AI remembers previous exchanges in thread
- **Thread isolation** - Each conversation thread maintains separate context
- **Window Buffer Memory** - Stores last 10 messages (5 exchanges) per thread
- **Automatic context** - No need to repeat service names in follow-up questions

### 💬 **Command-Based Activation** (NEW!)
- **`/oncall` prefix required** - Only processes messages starting with `/oncall`
- **Silent skip** - Ignores other messages without showing errors
- **Thread continuity** - Replies in `/oncall` threads don't need prefix
- **Clean Teams experience** - Bot only responds when explicitly invoked

### 🔧 Dual Tools
1. **website_health_query** - HTTP health checks for external endpoints
2. **oncall_agent_query** - Deep K8s analysis via internal API

### 📊 Rich Responses
- Formatted markdown in Adaptive Cards
- Severity indicators (🔴 Critical, ⚠️ Warning, ✅ Healthy)
- Detailed pod status, events, and recommendations

---

## Architecture

### Data Flow

```
User posts in Teams: "/oncall check proteus service"
    ↓
[1] Microsoft Teams Trigger
    Fires on new channel message
    Output: Message metadata (id, @odata.id)
    ↓
[2] get_teams_message (HTTP Request)
    Calls: https://graph.microsoft.com/v1.0/{@odata.id}
    Output: Full message object with body.content
    ↓
[3] filter_bot_messages (IF Node)
    Checks: Is this a bot's Adaptive Card?
    TRUE → Stop (skip bot's own messages)
    FALSE → Continue
    ↓
[4] query_parser (Code Node)
    Extracts text from body.content
    Checks for /oncall prefix (new threads only)
    Detects if reply (isReply=true)
    Strips /oncall prefix, extracts threadId
    Output: {shouldProcess, query, threadId, isReply, ...}
    ↓
[5] check_should_process (IF Node)
    Checks: shouldProcess === true?
    FALSE → Stop silently (message ignored)
    TRUE → Continue
    ↓
[6] check_if_reply (IF Node)
    Checks: isReply === true?
    TRUE → Fetch thread history (branch A)
    FALSE → Skip to merge (branch B)
    ↓
[7A] get_thread_history (HTTP Request - Branch A only)
    Calls: .../messages/{threadId}/replies
    Output: Array of all messages in thread
    ↓
[8A] format_conversation_history (Code Node - Branch A only)
    Parses user messages and bot Adaptive Cards
    Builds [{role: "user", content: "..."}, {role: "assistant", content: "..."}]
    Output: {conversationHistory: [...], messageCount: N}
    ↓
[9] Merge (Branch A + B converge)
    Combines paths with/without history
    ↓
[10] build_ai_prompt (Code Node)
    Injects conversation history into system message
    Formats as "Previous conversation: User: ... Assistant: ..."
    Output: {systemMessage, currentQuery}
    ↓
[11] AI Agent (LangChain + Claude Sonnet 4)
    System: Dynamic message with conversation context
    Tools: website_health_query, oncall_agent_query
    Memory: chat_memory (Window Buffer, session key = threadId)
    Output: Markdown analysis with context awareness
    ↓
[12] convert_response_teams (Code Node)
    Builds Adaptive Card JSON payload
    Includes query metadata in FactSet
    Output: Adaptive Card payload
    ↓
[13] build_reply_url (Code Node)
    Constructs Graph API URL using threadId
    Ensures replies go to thread root (not nested)
    Output: {url, payload}
    ↓
[14] reply_teams_thread (HTTP Request)
    POST to: .../messages/{threadId}/replies
    Posts Adaptive Card as threaded reply
    ↓
User sees formatted response in Teams thread! ✅
```

### Memory & Thread Management

**How Conversation Memory Works**:

1. **First Message** (New Thread):
   ```
   User: "/oncall check chronos"
   → isReply=false, threadId=messageId
   → No history fetched
   → AI Agent: "This is a new conversation"
   → Memory stores: User query + AI response
   ```

2. **Reply in Thread**:
   ```
   User: "Any restarts?" (replies to bot's message)
   → isReply=true, threadId=originalMessageId
   → Fetches thread history from Graph API
   → Extracts user + assistant messages
   → AI Agent: "Checking chronos restarts..." (remembers chronos!)
   → Memory updated with new exchange
   ```

3. **Concurrent Threads**:
   ```
   Thread A (User 1): "/oncall check proteus" → "Any errors?"
   Thread B (User 2): "/oncall check chronos" → "Show logs"
   → Separate threadIds → Separate memory sessions → No cross-talk
   ```

---

## Node Configuration

### 1. Microsoft Teams Trigger

**Type**: `n8n-nodes-base.microsoftTeamsTrigger`
**Version**: 1

**Configuration**:
- **Team**: Artemis-DevOps (`7ae997d9-9ecf-458d-b709-e0c44cd0ed15`)
- **Channel**: oncall-engineer (`19:a32bba9f7d8e4d71bc25cc10ad8119e3@thread.tacv2`)
- **Credential**: Microsoft Teams OAuth2 API

**Output Fields**:
```json
{
  "id": "1760102547983",
  "@odata.type": "#Microsoft.Graph.chatMessage",
  "@odata.id": "teams('...')/channels('...')/messages('...')"
}
```

**Triggers When**: Any new message posted in the oncall-engineer channel

---

### 2. get_teams_message

**Type**: `n8n-nodes-base.httpRequest` (HTTP Request Tool)
**Version**: 4.2

**Configuration**:
- **Method**: GET
- **URL**: `https://graph.microsoft.com/v1.0/{{ $json["@odata.id"] }}`
- **Authentication**: Microsoft Graph Security OAuth2 API
- **Credential**: ms-graph-oauth-credentials

**Purpose**: Fetches the full message content including text, sender info, and metadata.

**Output Fields** (relevant):
```json
{
  "id": "1760102547983",
  "messageType": "message",
  "body": {
    "content": "Check proteus service",
    "contentType": "text"
  },
  "from": {
    "user": {
      "displayName": "Ari Sela",
      "email": "ari.sela@artemishealth.com"
    }
  },
  "createdDateTime": "2025-10-10T14:29:49.862Z"
}
```

---

### 3. filter_bot_messages

**Type**: `n8n-nodes-base.if` (IF Node)
**Version**: 2.2

**Purpose**: Prevents infinite loops by filtering out bot's own Adaptive Card messages.

**Conditions**:
- `{{ $json.body.content }}` does NOT contain `<attachment id="1">`
- AND `{{ $json.attachments.length }}` equals `0`

**Flow**:
- **TRUE** → Continue to query_parser (user message)
- **FALSE** → Stop execution (bot message, skip to prevent loop)

---

### 4. query_parser

**Type**: `n8n-nodes-base.code` (Code Node)
**Version**: 2

**Purpose**: Extracts query text, validates `/oncall` prefix, detects thread replies, and manages conversation context.

**New Features (v3.0)**:
1. **Bot message detection** - Silently skips bot Adaptive Cards (returns `shouldProcess: false`)
2. **`/oncall` prefix validation** - Only processes messages starting with `/oncall` (case-insensitive)
3. **Thread detection** - Identifies replies via `replyToId` field
4. **Thread ID extraction** - Uses `replyToId` for replies, `id` for new threads
5. **Silent skip** - Returns flags instead of throwing errors (no red errors in UI)

**Logic**:
1. **Skip bot messages** - Checks for Adaptive Card attachments
2. **Extract text** - Strips HTML from `body.content`
3. **Validate prefix** - Ensures `/oncall` prefix (skipped for thread replies)
4. **Detect reply** - Sets `isReply = true` if `replyToId` exists
5. **Extract threadId** - Root message ID for memory session key

**Input Sources Supported**:
- ✅ Teams channel messages (requires `/oncall` prefix)
- ✅ Thread replies (no prefix required)
- ✅ Direct API calls with `query` or `prompt` fields (bypass prefix check)
- ✅ Cron triggers (bypass prefix check)

**Output**:
```json
{
  "shouldProcess": true,
  "skipReason": null,
  "query": "check proteus service",  // /oncall prefix stripped
  "source": "teams",
  "user": "Ari Sela",
  "namespace": "default",
  "timestamp": "2025-10-10T14:29:49.862Z",
  "threadId": "1760124196079",     // Root message ID
  "isReply": false,                // true if this is a thread reply
  "messageId": "1760124196079",    // Current message ID
  "replyToId": null                // Parent message ID (if reply)
}
```

**Skip Scenarios** (returns `shouldProcess: false`):
- Bot's own Adaptive Card messages
- Messages without `/oncall` prefix (new threads only)
- Empty messages or messages without text content

---

### 5. check_should_process

**Type**: `n8n-nodes-base.if` (IF Node)
**Version**: 2.2

**Purpose**: Silently stops workflow for messages that shouldn't be processed (non-`/oncall` messages, bot messages).

**Condition**:
- `{{ $json.shouldProcess }}` equals `true`

**Flow**:
- **TRUE** → Continue to check_if_reply
- **FALSE** → Stop silently (no error shown)

**Why This Exists**: Allows query_parser to return status flags instead of throwing errors, preventing red "Problem" indicators in n8n UI.

---

### 6. check_if_reply

**Type**: `n8n-nodes-base.if` (IF Node)
**Version**: 2.2

**Purpose**: Routes workflow based on whether message is a thread reply (needs history) or new thread (no history).

**Condition**:
- `{{ $('query_parser').first().json.isReply }}` equals `true`

**Flow**:
- **TRUE** → get_thread_history (fetch conversation history)
- **FALSE** → Merge (skip history, proceed to AI Agent)

---

### 7. get_thread_history

**Type**: `n8n-nodes-base.httpRequest` (HTTP Request)
**Version**: 4.2

**Purpose**: Fetches all messages in a Teams conversation thread for context.

**Configuration**:
- **Method**: GET
- **URL**: `https://graph.microsoft.com/v1.0/teams/{teamId}/channels/{channelId}/messages/{threadId}/replies`
- **Authentication**: OAuth2 API (Graph API credentials)

**Output**: Array of message objects including user messages and bot Adaptive Cards.

**Only runs**: When `isReply=true` (message is a reply in existing thread)

---

### 8. format_conversation_history

**Type**: `n8n-nodes-base.code` (Code Node)
**Version**: 2

**Purpose**: Parses Graph API thread history and extracts both user messages and bot Adaptive Card responses.

**Key Functions**:
1. **`isBotMessage(msg)`** - Detects bot messages by Adaptive Card attachments
2. **`extractTeamsMessage(data)`** - Extracts plain text from user HTML messages
3. **`extractAdaptiveCardText(data)`** - Parses Adaptive Card TextBlocks from bot responses

**Output**:
```json
{
  "conversationHistory": [
    {"role": "user", "content": "check chronos"},
    {"role": "assistant", "content": "✅ Chronos is healthy..."},
    {"role": "user", "content": "Any restarts?"},
    {"role": "assistant", "content": "Chronos has 0 restarts..."}
  ],
  "messageCount": 4,
  "threadId": "1760124196079"
}
```

---

### 9. Merge

**Type**: `n8n-nodes-base.merge` (Merge Node)
**Version**: 3.2

**Purpose**: Combines the two workflow branches (with/without thread history) before build_ai_prompt.

**Inputs**:
- Input 1: format_conversation_history (when isReply=true)
- Input 2: check_if_reply false branch (when isReply=false)

**Why Needed**: Ensures build_ai_prompt always executes regardless of whether conversation history exists.

---

### 10. build_ai_prompt

**Type**: `n8n-nodes-base.code` (Code Node)
**Version**: 2

**Purpose**: Dynamically builds the AI Agent system message with conversation context.

**Logic**:
1. Gets conversation history from format_conversation_history (or empty array)
2. Formats history as plain text: "User: ... Assistant: ..."
3. Injects into system message under "## CONVERSATION CONTEXT"
4. Returns complete system message + current query

**Output**:
```json
{
  "systemMessage": "You are an intelligent On-Call Assistant...\n\n## CONVERSATION CONTEXT\n\nPrevious conversation:\nUser: check chronos\nAssistant: ✅ Chronos is healthy...\n\nCurrent question: Any restarts?\n\n## YOUR CAPABILITIES...",
  "currentQuery": "Any restarts?",
  "hasHistory": true,
  "historyLength": 2
}
```

**Why This Exists**: n8n doesn't support Handlebars template syntax, so we pre-format the system message in JavaScript.

---

### 11. chat_memory

**Type**: `@n8n/n8n-nodes-langchain.memoryBufferWindow` (Window Buffer Memory)
**Version**: 1.3

**Purpose**: Stores conversation history for multi-turn conversations, connected to AI Agent.

**Configuration**:
- **Session ID Type**: Custom Key
- **Session Key**: `{{ $('query_parser').first().json.threadId }}`
- **Context Window Length**: 10 messages (5 user-assistant exchanges)

**How It Works**:
- Each Teams thread has unique threadId
- Memory is isolated per threadId (no cross-thread contamination)
- Oldest messages drop off when window exceeds 10 messages
- Memory is **in-memory only** (cleared on n8n restart)

**Connection**: Connected to AI Agent via `ai_memory` link

---

### 12. AI Agent

**Type**: `@n8n/n8n-nodes-langchain.agent` (AI Agent)
**Version**: 2.1

**Configuration**:
- **Model**: Claude Sonnet 4 (`claude-sonnet-4-20250514`)
- **Credential**: Anthropic API (asela-api-key)
- **Prompt**: `{{ $('build_ai_prompt').first().json.currentQuery }}`
- **System Message**: `{{ $('build_ai_prompt').first().json.systemMessage }}`
- **Memory**: chat_memory (Window Buffer)
- **Max Iterations**: 10

**System Message**: Dynamically generated with conversation context (see build_ai_prompt)

**Tools Available**:

#### Tool 1: website_health_query
- **Type**: HTTP Request Tool (GET)
- **URL**: `{{ $json.query }}` (expects full URL from AI)
- **Purpose**: Check website availability, response time, HTTP status
- **Returns**: Status code, body preview, performance metrics

#### Tool 2: oncall_agent_query
- **Type**: HTTP Request Tool (POST)
- **URL**: `https://oncall-agent.internal.artemishealth.com/query`
- **Authentication**: HTTP Header Auth
- **Body**: `{"prompt": "{{ $json.query }}"}`
- **AI Parameter Enabled**: ✨ sparkle icon enabled on `prompt` field
- **Timeout**: 120 seconds
- **Purpose**: Deep K8s cluster analysis (pods, events, logs, deployments)
- **Returns**: Markdown-formatted analysis with recommendations

**Output**:
```json
{
  "output": "✅ **Chronos Status - HEALTHY**\n\nPod: chronos-9976797f4-j75b7\nRestarts: 0...",
  "intermediate_steps": [...],
  "sessionId": "..."
}
```

---

### 13. convert_response_teams

**Type**: `n8n-nodes-base.code` (Code Node)
**Version**: 2

**Purpose**: Transforms AI agent output into Microsoft Graph API-compatible Adaptive Card payload.

**Input**:
- AI Agent output (`$('AI Agent').first().json.output`)
- Query metadata (`$('query_parser').first().json`)

**Output**: JSON payload with Adaptive Card structure

**Adaptive Card Components**:
1. **Header**: "🤖 On-Call Assistant" (Large, Bold, Accent color)
2. **Body**: AI agent's markdown analysis (wrapped text)
3. **Footer FactSet**: Query, User, Timestamp

**Key Detail**: Adaptive Card `content` is **stringified** (`JSON.stringify()`) to meet Graph API requirements.

---

### 14. build_reply_url

**Type**: `n8n-nodes-base.code` (Code Node)
**Version**: 2

**Purpose**: Constructs clean Graph API URL for posting replies using regex parsing.

**Why This Exists**: Complex nested `split()` expressions cause n8n syntax errors. This node uses regex for reliable parsing.

**Logic**:
1. Extracts teamId from `@odata.id` using regex: `/teams\('([^']+)'\)/`
2. Extracts channelId using regex: `/channels\('([^']+)'\)/`
3. Uses threadId from query_parser (ensures root-level replies)
4. Constructs URL: `https://graph.microsoft.com/v1.0/teams/{teamId}/channels/{channelId}/messages/{threadId}/replies`

**Output**:
```json
{
  "url": "https://graph.microsoft.com/v1.0/teams/7ae997d9-.../channels/19:a32b.../messages/1760124196079/replies",
  "payload": { /* Adaptive Card payload */ },
  "teamId": "7ae997d9-9ecf-458d-b709-e0c44cd0ed15",
  "channelId": "19:a32bba9f7d8e4d71bc25cc10ad8119e3@thread.tacv2",
  "threadId": "1760124196079"
}
```

---

### 15. reply_teams_thread

**Type**: `n8n-nodes-base.httpRequest` (HTTP Request)
**Version**: 4.2

**Configuration**:
- **Method**: POST
- **URL**: `{{ $('build_reply_url').first().json.url }}`
- **Authentication**: OAuth2 API (Graph API credentials)
- **Body**: `{{ $('build_reply_url').first().json.payload }}`

**Purpose**: Posts the Adaptive Card as a threaded reply to the original Teams message.

**Result**: User sees formatted response in Teams conversation thread.

---

## Prerequisites

### Required Credentials

1. **Microsoft Teams OAuth2 API**
   - Used by: Microsoft Teams Trigger
   - Setup: Azure App Registration with Teams permissions
   - Scopes: `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Read.All`

2. **Microsoft Graph Security OAuth2 API** / **OAuth2 API**
   - Used by: get_teams_message, get_thread_history, reply_teams_thread
   - Setup: Same Azure App as above, but with Graph API scopes
   - **Required Scopes**: `ChannelMessage.Read.All ChannelMessage.Send offline_access`
   - **Critical**: `offline_access` enables automatic token refresh (prevents auth failures)
   - **Grant Type**: Authorization Code
   - **Auth URL**: `https://login.microsoftonline.com/common/oauth2/v2.0/authorize`
   - **Token URL**: `https://login.microsoftonline.com/common/oauth2/v2.0/token`

3. **Anthropic API**
   - Used by: Anthropic Chat Model
   - Setup: Anthropic API key from https://console.anthropic.com
   - Model: Claude Sonnet 4

4. **HTTP Header Auth** (oncall-agent)
   - Used by: oncall_agent_query
   - Setup: API key or bearer token for oncall-agent.internal.artemishealth.com
   - Header: `Authorization: Bearer <token>`

### Required Services

- **oncall-agent.internal.artemishealth.com** - Internal K8s monitoring API
  - Must be accessible from n8n instance
  - Endpoint: `POST /query` with `{"prompt": "..."}`
  - Returns: Markdown analysis

### Network Requirements

- **External webhook endpoint**: `n8n-dev-webhook.artemishealth.com`
  - Must allow Microsoft Graph API IPs (see IP allowlist docs)
  - Valid SSL certificate from trusted CA
  - Port 443 accessible

---

## Installation

### Step 1: Import Workflow

```bash
# In n8n UI:
1. Navigate to Workflows
2. Click "Import from File"
3. Upload: dev-eks-oncall-engineer-v2.json
4. Click "Import"
```

### Step 2: Configure Credentials

Create/verify these credentials in n8n:

**Microsoft Teams OAuth2**:
1. Settings → Credentials → Add Credential
2. Select "Microsoft Teams OAuth2 API"
3. Enter Client ID and Client Secret from Azure
4. Grant permissions

**Microsoft Graph Security OAuth2**:
1. Settings → Credentials → Add Credential
2. Select "Microsoft Graph Security OAuth2 API"
3. Use **same Client ID/Secret** as Teams OAuth2
4. Set Scope: `https://graph.microsoft.com/.default`
5. Connect and authorize

**Anthropic API**:
1. Settings → Credentials → Add Credential
2. Select "Anthropic API"
3. Enter API key from Anthropic Console

**HTTP Header Auth** (oncall-agent):
1. Settings → Credentials → Add Credential
2. Select "Header Auth"
3. Name: `Authorization`
4. Value: `Bearer <your-oncall-agent-api-token>`

### Step 3: Update Team/Channel IDs (if needed)

If you want to use a different Teams channel:

1. Open workflow
2. Edit "Microsoft Teams Trigger" node
3. Select your desired Team and Channel
4. Save

The other nodes automatically reference the trigger's output, so no other changes needed.

### Step 4: Activate Workflow

1. Click the **"Active"** toggle in the top right
2. n8n will register webhook with Microsoft Graph
3. Status should show "Active" with green dot

### Step 5: Test

Post a message in your Teams channel:
```
/oncall check proteus service in proteus-dev
```

Expected: AI agent responds in thread with Adaptive Card showing pod status.

---

## Usage Examples

### Example 1: Basic Service Check with `/oncall` Prefix

**User**: `/oncall check chronos deployment in dev`

**AI Response**:
```
✅ Chronos Dev Environment - HEALTHY

Deployment Details:
- Namespace: chronos-dev
- Desired Replicas: 1/1 ✅
- Pod Status: Running and ready
- Restarts: 0 (stable)
```

---

### Example 2: Multi-Turn Conversation (Conversation Memory)

**User**: `/oncall check chronos deployment`

**AI Response**:
```
✅ Chronos is healthy
- Pod: chronos-9976797f4-j75b7
- Status: Running, 1/1 ready
- Restarts: 0
```

**User** (replies in thread): `Any restarts?` ← No `/oncall` prefix needed!

**AI Response**:
```
Based on the chronos deployment I just checked, there are 0 container restarts.
✅ The chronos container has been running stably...
```

**User** (replies again): `Show me the logs` ← Still remembers chronos!

**AI Response**:
```
Checking chronos pod logs in chronos-dev namespace...
[Shows logs for chronos-9976797f4-j75b7]
```

**How It Works**: AI maintains conversation context across all replies in the thread!

---

### Example 3: Website Health Check

**User**: `/oncall is devops.artemishealth.com up?`

**AI Actions**:
1. Calls `website_health_query` with URL
2. Returns status and response time

**AI Response**:
```
✅ devops.artemishealth.com: Healthy
- HTTP 200, response time: 245ms
- Site is accessible and responding normally
```

---

### Example 4: Troubleshooting Slow Website

**User**: `/oncall why is api.artemishealth.com slow?`

**AI Actions**:
1. Calls `website_health_query` → measures response time
2. Calls `oncall_agent_query` → checks backend K8s services
3. Correlates findings

**AI Response**:
```
⚠️ api.artemishealth.com: SLOW
- HTTP 200, response time: 8500ms (expected <2000ms)

Backend Analysis:
- proteus-dev: High CPU usage detected (85%)
- hermes-dev: 2 pods restarting (ImagePullBackOff)

Recommended Actions:
1. Scale proteus deployment to handle load
2. Fix hermes image reference
```

---

### Example 5: Concurrent Multi-User Threads

**User A** (Thread 1): `/oncall check proteus`
```
Bot: ✅ Proteus healthy, 5/5 pods running
```

**User B** (Thread 2, same time): `/oncall check chronos`
```
Bot: ✅ Chronos healthy, 1/1 pods running
```

**User A** (replies in Thread 1): `Any errors in logs?`
```
Bot: Checking proteus logs... ← Remembers Thread 1 context
```

**User B** (replies in Thread 2): `What about restarts?`
```
Bot: Chronos has 0 restarts... ← Remembers Thread 2 context
```

**Thread Isolation**: Each conversation maintains separate context, no cross-talk!

---

### Example 6: Non-`/oncall` Messages Silently Ignored

**User**: `hello everyone!` ← No `/oncall` prefix

**Bot**: (No response, workflow skips silently)

**User**: `/oncall check hermes`

**Bot**: ✅ Responds normally (prefix detected)

---

## Using the `/oncall` Command

### Command Syntax

**Start a new conversation**:
```
/oncall <your question>
```

**Examples**:
```
/oncall check proteus service
/oncall is devops.artemishealth.com up?
/oncall show me all pods in chronos-dev
/ONCALL check hermes  ← Case-insensitive
```

**Reply in thread** (no prefix needed):
```
Initial: /oncall check chronos
Reply 1: Any restarts?        ← No /oncall needed
Reply 2: Show me the logs     ← Still no /oncall needed
Reply 3: What about CPU usage? ← AI remembers chronos context
```

### What Gets Ignored (Silent Skip)

These messages will be **silently ignored** (no bot response, no error):

```
hello everyone               ← No /oncall prefix
check proteus               ← No /oncall prefix
@mention someone            ← No /oncall prefix
[Any casual chat]           ← Bot only responds to /oncall
```

### Direct API Bypass

Direct API calls to `/query` endpoint **don't require** `/oncall` prefix:
```bash
curl -X POST https://oncall-agent.internal.artemishealth.com/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "check proteus"}'  ← No /oncall needed
```

This allows programmatic access and scheduled jobs to work normally.

---

## Configuration Details

### AI Agent System Message

The AI agent is configured with detailed instructions for:
- **Service to website mappings** (e.g., devops.artemishealth.com → proteus + artemis-auth)
- **Intelligent troubleshooting workflows** (when to use each tool)
- **Severity classification** (Critical/Warning/Healthy)
- **Response formatting** (consistent markdown structure)

Full system message: See `dev-eks-oncall-engineer-v2.json` lines 9-10 (embedded in workflow).

### Tool Configurations

**website_health_query**:
- Simple HTTP GET to provided URL
- Returns: status code, response time, body preview
- Used for: External endpoint availability checks

**oncall_agent_query**:
- POST to `https://oncall-agent.internal.artemishealth.com/query`
- Payload: `{"prompt": "<K8s question>"}`
- Timeout: 120 seconds
- Returns: Markdown-formatted K8s analysis
- Used for: Pod health, events, logs, deployment history

---

## Adaptive Card Format

The AI response is formatted as an Adaptive Card with:

### Header Section
```
🤖 On-Call Assistant
```
(Large, Bold, Accent color)

### Content Section
```
[AI Agent's full markdown response with pod status, analysis, recommendations]
```
(Wrapped text, supports markdown)

### Metadata Footer
```
Query:     Check proteus service
User:      Ari Sela
Timestamp: 2025-10-10T14:29:49.862Z
```
(FactSet format)

---

## Troubleshooting

### Issue: Trigger not activating

**Symptom**: Workflow stays inactive or shows error on activation

**Causes**:
1. **IP allowlist blocking Graph API** - See network requirements
2. **Missing Teams permissions** - Check Azure app permissions
3. **Webhook endpoint unreachable** - Verify DNS and SSL

**Solution**:
- Follow IP allowlist guide: `docs/n8n-integrations/IMPLEMENTATION-GUIDE.md`
- Ensure Graph API IPs allowed: `microsoft-graph-webhook-ips.txt`
- Check webhook endpoint responds to validation requests

---

### Issue: "No text content in Teams message"

**Symptom**: Error thrown by query_parser

**Cause**: User sent image-only message or empty message

**Solution**: Query parser validates text exists - user must send text message

---

### Issue: oncall_agent_query timeout

**Symptom**: HTTP Request times out after 120s

**Causes**:
1. oncall-agent.internal.artemishealth.com unreachable
2. K8s query taking too long
3. Authentication failure

**Solution**:
- Verify oncall-agent service is running
- Check HTTP Header Auth credential is valid
- Test endpoint manually: `curl -X POST https://oncall-agent.internal.artemishealth.com/query -H "Authorization: Bearer <token>" -d '{"prompt":"test"}'`

---

### Issue: Adaptive Card not rendering

**Symptom**: Plain text or error in Teams

**Causes**:
1. Adaptive Card JSON structure invalid
2. Content not properly stringified
3. Teams client version doesn't support Adaptive Cards v1.4

**Solution**:
- Verify `convert_response_teams` is stringifying content: `JSON.stringify(adaptiveCardContent)`
- Test card at: https://adaptivecards.io/designer/
- Fallback: Use simple text/HTML response

---

### Issue: AI Agent not using tools

**Symptom**: Generic response without calling website_health_query or oncall_agent_query

**Causes**:
1. Query too vague
2. Tool descriptions unclear
3. System message not emphasizing tool usage
4. **Tool parameters not AI-enabled** - ✨ sparkle icon not clicked

**Solution**:
- Be specific: "Check the website https://devops.artemishealth.com"
- Review system message emphasizes using tools
- Check tool connection in workflow editor (should show ai_tool links)
- **Verify oncall_agent_query has ✨ enabled** on the `prompt` parameter

---

### Issue: Bot responds to every message in channel

**Symptom**: Bot replies to all messages, including casual chat

**Cause**: `/oncall` prefix not implemented or check_should_process node missing

**Solution**:
1. Verify query_parser includes `/oncall` prefix validation code
2. Ensure check_should_process IF node exists after query_parser
3. Check condition: `{{ $json.shouldProcess }}` equals `true`
4. Verify false branch is **not connected** (workflow should stop)

---

### Issue: Conversation memory not working

**Symptom**: AI doesn't remember previous exchanges in thread

**Causes**:
1. **chat_memory not connected** to AI Agent
2. **Thread detection failing** - isReply always false
3. **format_conversation_history not extracting assistant messages** - Only showing user messages

**Debugging**:
1. Check `query_parser` output:
   - Reply messages should have `isReply: true`
   - `threadId` should match root message ID
2. Check `format_conversation_history` output:
   - Should show both `role: "user"` and `role: "assistant"` messages
   - `messageCount` should be > 0 for replies
3. Check `chat_memory` connection:
   - Should connect to AI Agent via `ai_memory` link
   - Session Key should be `{{ $('query_parser').first().json.threadId }}`
4. Check `build_ai_prompt` output:
   - `hasHistory` should be `true` for replies
   - `systemMessage` should include "Previous conversation:" section

**Solution**:
- Verify all memory nodes exist: get_thread_history → format_conversation_history → build_ai_prompt
- Ensure chat_memory connected to AI Agent
- Confirm format_conversation_history correctly detects bot Adaptive Cards
- Check Graph API credentials have `offline_access` scope for refresh tokens

---

### Issue: Thread replies not appearing in Teams

**Symptom**: Bot sends reply but message not visible in thread

**Causes**:
1. **Nested reply problem** - Replying to reply instead of thread root
2. **URL construction error** - Incorrect threadId in URL

**Solution**:
1. Verify `build_reply_url` uses `{{ $('query_parser').first().json.threadId }}`
2. Thread ID should be **root message ID**, not current message ID
3. Check reply_teams_thread URL: `.../messages/{threadId}/replies` (not nested)
4. Test: Look for message via Graph API Explorer to confirm it exists

---

### Issue: OAuth token expired / refreshToken required

**Symptom**: Graph API calls fail with "refreshToken is required" error

**Causes**:
1. **Missing `offline_access` scope** - Can't refresh tokens automatically
2. **Credential needs re-authentication**

**Solution**:
1. In Azure Portal → App Registration → API Permissions:
   - Add `offline_access` (Delegated permission)
   - Grant admin consent
2. In n8n → OAuth2 credential settings:
   - Set Scope: `ChannelMessage.Read.All ChannelMessage.Send offline_access`
   - Re-authenticate credential (click "Connect my account")
3. Tokens will now auto-refresh

---

## Monitoring

### Workflow Execution Logs

View execution history:
1. Open workflow
2. Click "Executions" tab
3. Review successful/failed runs

**Metrics to track**:
- Success rate (should be >95%)
- Execution time (typically 5-15 seconds)
- Tool usage frequency (website vs oncall_agent)

### Teams Channel Activity

Monitor the oncall-engineer Teams channel:
- Response accuracy
- User satisfaction
- Common query patterns

### Cost Tracking

**Claude API Usage**:
- Model: Claude Sonnet 4
- Typical cost: $0.003-0.01 per query
- Monitor usage at: https://console.anthropic.com

**n8n Workflow Executions**:
- Each Teams message = 1 execution
- Each execution calls Claude API once (plus tool calls)

---

## Customization

### Adding New Service Mappings

Edit the AI Agent system message to add new services:

```javascript
// In AI Agent node → Options → System Message
**newservice.artemishealth.com**:
- Services: new-service
- Namespaces: new-service-dev
- Critical path: new-service only
```

### Changing Response Format

Edit `convert_response_teams` code node to modify Adaptive Card:

**Add severity color coding**:
```javascript
{
  "type": "TextBlock",
  "text": aiOutput,
  "wrap": true,
  "color": aiOutput.includes("🔴") ? "Attention" :
           aiOutput.includes("⚠️") ? "Warning" : "Good"
}
```

**Add action buttons**:
```javascript
"actions": [
  {
    "type": "Action.OpenUrl",
    "title": "View in ArgoCD",
    "url": "https://argocd.artemishealth.com/applications/proteus-dev"
  }
]
```

### Supporting Multiple Channels

To monitor multiple Teams channels:

1. **Duplicate the workflow**
2. **Change trigger channel** in each copy
3. **Keep all other nodes identical**

Or create a **single workflow** that dynamically handles any channel by removing channel selection from trigger.

---

## Security Considerations

### Read-Only Operations

Both tools are **read-only**:
- ✅ website_health_query - Only performs HTTP GET
- ✅ oncall_agent_query - Read-only K8s analysis
- ❌ No deployments, restarts, or modifications possible

### Cluster Protection

oncall-agent API enforces:
- **Allowed clusters**: dev-eks only
- **Protected clusters**: prod-eks, staging-eks (hard-coded protection)
- Any attempt to query protected clusters raises `PermissionError`

### Credential Security

- **Teams OAuth2**: Scoped to channel message reading only
- **Graph Security OAuth2**: Minimal required permissions
- **Anthropic API**: Usage tracked and rate-limited
- **oncall-agent Auth**: Internal API with header-based auth

### Audit Trail

Every interaction is logged:
- n8n execution logs (full request/response)
- Teams message history (questions and responses)
- oncall-agent API logs (K8s queries performed)

---

## Maintenance

### Monthly Updates Required

**Microsoft Graph API IPs**:
- Microsoft updates IP ranges monthly
- Review: https://learn.microsoft.com/en-us/microsoft-365/enterprise/urls-and-ip-address-ranges
- Update ingress allowlist if new IPs added

**n8n Version**:
- Keep n8n updated for Teams trigger bug fixes
- Current known issue: #17887 (may be fixed in future releases)

**Claude Model**:
- Monitor for new Claude models (currently Sonnet 4)
- Consider upgrading when new versions released

### Backup Strategy

**Export workflow monthly**:
```bash
# In n8n UI:
Workflows → dev-eks-oncall-engineer-v2 → ⋮ → Export Workflow
Save to: docs/n8n-workflows/dev-eks-oncall-engineer-v2-YYYY-MM-DD.json
```

**Backup credentials separately** (store securely):
- Client IDs, Client Secrets
- API tokens
- Don't commit credentials to git!

---

## Performance Optimization

### Current Performance

**Typical execution time**:
- **New thread** (no memory): 5-8 seconds
  - Teams trigger: <1s
  - Get message: ~500ms
  - Query parser: <100ms
  - AI Agent: 3-6s (depends on tool calls)
  - Response formatting: <100ms
  - Reply to Teams: ~500ms

- **Thread reply** (with memory): 7-12 seconds
  - Teams trigger: <1s
  - Get message: ~500ms
  - Query parser: <100ms
  - **Thread history fetch**: ~1-2s (Graph API call)
  - **Format conversation**: ~100ms
  - Build AI prompt: <100ms
  - **AI Agent with context**: 4-8s (higher due to conversation context)
  - Response formatting: <100ms
  - Reply to Teams: ~500ms

**Memory Overhead**:
- **+2-3 seconds** per reply (thread history fetch + formatting)
- **+1-2 seconds** AI processing (larger context with conversation history)
- **Token usage increase**: ~500 tokens/message → ~1500-2500 tokens/message (with 5-exchange history)

### Optimization Tips

1. **Reduce AI thinking time**:
   - Make queries more specific
   - Pre-filter data when possible
   - Use prompt caching (future Claude feature)

2. **Parallel tool execution**:
   - AI agent already handles this automatically
   - website_health_query and oncall_agent_query can run in parallel

3. **Caching** (future enhancement):
   - Cache oncall_agent responses for 60s
   - Deduplicate similar queries within 5 minutes

---

## Extending the Workflow

### Add Response Reactions

Add a node after `reply_teams_thread` to add reactions:

**HTTP Request**:
```
POST https://graph.microsoft.com/v1.0/teams/{teamId}/channels/{channelId}/messages/{messageId}/reactions
Body: {"reactionType": "like"}
```

### Add Incident Ticket Creation

Add conditional logic after AI Agent:

```javascript
// Check if critical issue detected
if (aiOutput.includes("🔴") || aiOutput.includes("CRITICAL")) {
  // Create Jira ticket automatically
  // Or send alert to PagerDuty
}
```

### Multi-Cluster Support

Extend to monitor multiple clusters:
1. Update oncall-agent API to support cluster parameter
2. Add cluster detection in query_parser
3. Route to appropriate oncall-agent endpoint

---

### Upgrade to Persistent Memory (Redis)

For production environments requiring persistent conversation memory:

**Why Upgrade**:
- Window Buffer Memory is in-memory only (cleared on n8n restart)
- Redis Chat Memory persists conversations across restarts
- Useful for long-running conversations spanning days/weeks

**How to Upgrade**:

1. **Deploy Redis instance** (or use existing)
   ```bash
   # Docker Compose
   docker run -d -p 6379:6379 redis:7-alpine
   ```

2. **Replace chat_memory node**:
   - Delete Window Buffer Memory node
   - Add new **Redis Chat Memory** node
   - Configure:
     - **Redis URL**: `redis://redis:6379`
     - **Session Key**: `{{ $('query_parser').first().json.threadId }}`
     - **TTL**: `604800` (7 days)
   - Connect to AI Agent via `ai_memory` link

3. **Add Redis credential** in n8n:
   - Credential Type: Redis
   - Host: your Redis instance
   - Port: 6379
   - Database: 0

**Benefits**:
- ✅ Conversations persist across n8n restarts
- ✅ Memory survives container deployments
- ✅ Can set custom TTL (e.g., 7 days, 30 days)
- ✅ Centralized memory storage for clustered n8n

**Trade-offs**:
- Requires Redis infrastructure
- Slightly slower memory access (~10-50ms vs instant)
- Need to manage Redis backups/persistence

---

## Known Limitations

1. **Teams Trigger Issue**: GitHub issue #17887
   - Workaround: Using Graph API directly for message fetch/reply
   - May be fixed in future n8n versions

2. **Single Channel**: Currently monitors one channel only
   - Workaround: Duplicate workflow for additional channels

3. **Synchronous Processing**: Blocks while AI processes
   - Future: Could add queue for long-running queries

4. **In-Memory Conversation Storage**: Window Buffer Memory is not persistent
   - Limitation: Conversation history cleared on n8n restart
   - Workaround: Upgrade to Redis Chat Memory for persistence
   - Impact: Typically minimal (threads rarely span n8n restarts)

5. **Context Window Limit**: 10 messages (5 exchanges) per thread
   - Limitation: Older messages drop off in long conversations
   - Workaround: Increase window size in chat_memory node (may increase token costs)
   - Current: Sufficient for most troubleshooting conversations

---

## Support & References

### Documentation
- **Microsoft Graph API**: https://learn.microsoft.com/en-us/graph/api/channel-post-messages
- **Adaptive Cards**: https://adaptivecards.io/
- **n8n LangChain**: https://docs.n8n.io/integrations/builtin/cluster-nodes/root-nodes/n8n-nodes-langchain.agent/
- **Claude API**: https://docs.anthropic.com/

### Related Files
- **IP Allowlist Guide**: `docs/n8n-integrations/IMPLEMENTATION-GUIDE.md`
- **Graph API IPs**: `docs/n8n-integrations/microsoft-graph-webhook-ips.txt`
- **Combined IPs**: `docs/n8n-integrations/combined-webhook-ips.txt`

### GitHub Issues
- **n8n Teams Trigger Bug**: https://github.com/n8n-io/n8n/issues/17887

---

## Changelog

### Version 3.0 (2025-10-10) - **Conversation Memory & Command Prefix**
- ✅ **Conversation Memory** - Multi-turn conversations with context retention
  - Window Buffer Memory with 10-message window
  - Thread-based session isolation
  - Extracts both user and assistant messages from Graph API
- ✅ **`/oncall` Command Prefix** - Command-based activation
  - Silent skip for non-prefixed messages
  - Thread replies don't require prefix
  - Clean Teams channel experience
- ✅ **Thread History Retrieval** - Fetches full conversation from Graph API
- ✅ **Bot Message Filtering** - Prevents infinite loops
- ✅ **Dynamic System Messages** - Injects conversation context
- ✅ **Fixed Thread Nesting** - Replies always at root level
- ✅ **Clean Error Handling** - Silent skips without red errors

### Version 2.0 (2025-10-10)
- ✅ **Fixed Teams trigger** - Added Graph API IPs to allowlist
- ✅ **Threaded replies** - Responses now appear in conversation threads
- ✅ **Adaptive Cards** - Rich formatting with metadata
- ✅ **Enhanced query parser** - Supports Teams, webhooks, and cron triggers
- ✅ **Dual tool system** - website_health_query + oncall_agent_query

### Version 1.0 (Previous)
- Basic Teams integration
- Single tool support
- Simple text responses

---

## Contributors

- **Ari Sela** - Initial implementation and Microsoft Graph integration
- **Claude AI** - Workflow design assistance and documentation

---

## License

Internal ArtemisHealth tool. Not for external distribution.

---

**Last Updated**: 2025-10-10
**Workflow Version**: 3.0 - Conversation Memory & Command Prefix
**n8n Version**: 1.111.0
**Maintained By**: ArtemisHealth DevOps Team

---

## Quick Reference

### Command Format
```
/oncall <question>          ← Start new conversation
<reply in thread>           ← Continue conversation (no prefix)
```

### Key Nodes
- **query_parser** - Validates `/oncall` prefix, detects replies, extracts threadId
- **check_should_process** - Silently skips non-`/oncall` messages
- **check_if_reply** - Routes to thread history fetch or direct to AI
- **chat_memory** - Window Buffer (10 messages, sessionKey = threadId)
- **build_ai_prompt** - Injects conversation context into system message

### Memory Behavior
- **Thread isolation** - Each thread = separate memory session
- **Context window** - Last 10 messages (5 exchanges) retained
- **Storage** - In-memory (cleared on n8n restart)
- **Auto-expiry** - Threads expire after 24 hours inactivity
