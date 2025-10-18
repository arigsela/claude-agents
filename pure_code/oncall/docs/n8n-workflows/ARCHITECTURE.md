# dev-eks-oncall-engineer-v2 - Architecture Diagram

## Visual Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Microsoft Teams Channel                          │
│                        "oncall-engineer" Channel                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                        User posts: "Check proteus service"
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE 1: Microsoft Teams Trigger                                        │
│  ─────────────────────────────────────────────────────────────────────  │
│  Type: Webhook (Graph API subscription)                                 │
│  Listens: New messages in oncall-engineer channel                       │
│                                                                          │
│  Output:                                                                 │
│  {                                                                       │
│    "id": "1760102547983",                                               │
│    "@odata.id": "teams('..')/channels('..')/messages('..')"            │
│  }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE 2: get_teams_message (HTTP Request)                               │
│  ─────────────────────────────────────────────────────────────────────  │
│  Method: GET                                                             │
│  URL: https://graph.microsoft.com/v1.0/{{ @odata.id }}                  │
│  Auth: Microsoft Graph Security OAuth2                                  │
│                                                                          │
│  Purpose: Fetch full message content (text, sender, timestamp)          │
│                                                                          │
│  Output:                                                                 │
│  {                                                                       │
│    "id": "1760102547983",                                               │
│    "body": {                                                             │
│      "content": "Check proteus service"                                 │
│    },                                                                    │
│    "from": {                                                             │
│      "user": {"displayName": "Ari Sela"}                                │
│    },                                                                    │
│    "createdDateTime": "2025-10-10T14:29:49.862Z"                        │
│  }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE 3: query_parser (Code Node)                                       │
│  ─────────────────────────────────────────────────────────────────────  │
│  Logic:                                                                  │
│  1. Detect source (teams/webhook/cron)                                  │
│  2. Extract text from body.content                                      │
│  3. Strip HTML tags                                                      │
│  4. Capture user and timestamp                                          │
│                                                                          │
│  Supports:                                                               │
│  ✓ Teams messages                                                        │
│  ✓ Direct API calls (query/prompt fields)                               │
│  ✓ Cron triggers (default query)                                        │
│                                                                          │
│  Output:                                                                 │
│  {                                                                       │
│    "query": "Check proteus service",                                    │
│    "source": "teams",                                                    │
│    "user": "Ari Sela",                                                  │
│    "namespace": "default",                                              │
│    "timestamp": "2025-10-10T14:29:49.862Z"                              │
│  }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE 4: AI Agent (LangChain + Claude Sonnet 4)                         │
│  ─────────────────────────────────────────────────────────────────────  │
│  Model: claude-sonnet-4-20250514                                        │
│  Prompt: {{ $json.query }}                                              │
│  Max Iterations: 10                                                      │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  System Message: Kubernetes Operations Assistant                 │  │
│  │                                                                   │  │
│  │  • Service to website mappings                                   │  │
│  │  • Intelligent troubleshooting workflows                         │  │
│  │  • Severity classification rules                                 │  │
│  │  • Response formatting guidelines                                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─────────────────────────┐  ┌──────────────────────────────────────┐│
│  │ TOOL 1:                 │  │ TOOL 2:                              ││
│  │ website_health_query    │  │ oncall_agent_query                   ││
│  ├─────────────────────────┤  ├──────────────────────────────────────┤│
│  │ HTTP GET                │  │ HTTP POST                            ││
│  │ URL: <from AI>          │  │ URL: oncall-agent.internal...        ││
│  │                         │  │                                      ││
│  │ Returns:                │  │ Body: {"prompt": "..."}              ││
│  │ • HTTP status           │  │ Timeout: 120s                        ││
│  │ • Response time         │  │                                      ││
│  │ • Body preview          │  │ Returns:                             ││
│  │                         │  │ • Pod status & health                ││
│  │ Use: External checks    │  │ • K8s events & logs                  ││
│  └─────────────────────────┘  │ • Deployment history                 ││
│                                │ • Recommendations                    ││
│                                │                                      ││
│                                │ Use: K8s troubleshooting             ││
│                                └──────────────────────────────────────┘│
│                                                                          │
│  AI Reasoning:                                                           │
│  1. Understands query intent                                            │
│  2. Chooses appropriate tool(s)                                         │
│  3. Correlates findings                                                 │
│  4. Formats response with severity indicators                           │
│                                                                          │
│  Output:                                                                 │
│  {                                                                       │
│    "output": "✅ **Proteus Pods - HEALTHY**\n\n5/5 pods running..."       │
│  }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE 5: convert_response_teams (Code Node)                             │
│  ─────────────────────────────────────────────────────────────────────  │
│  Purpose: Transform AI output into Adaptive Card JSON                   │
│                                                                          │
│  Process:                                                                │
│  1. Get AI output from previous node                                    │
│  2. Get query metadata from query_parser                                │
│  3. Build Adaptive Card structure:                                      │
│     • Header: "🤖 On-Call Assistant"                                    │
│     • Body: AI markdown response                                        │
│     • Footer: FactSet with query/user/timestamp                         │
│  4. Stringify Adaptive Card content                                     │
│  5. Wrap in Graph API payload format                                    │
│                                                                          │
│  Output:                                                                 │
│  {                                                                       │
│    "body": {                                                             │
│      "contentType": "html",                                             │
│      "content": "<attachment id=\"1\"></attachment>"                    │
│    },                                                                    │
│    "attachments": [{                                                     │
│      "contentType": "application/vnd.microsoft.card.adaptive",          │
│      "content": "{\"type\":\"AdaptiveCard\",...}"  ← STRINGIFIED        │
│    }]                                                                    │
│  }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  NODE 6: reply_teams_thread (HTTP Request)                              │
│  ─────────────────────────────────────────────────────────────────────  │
│  Method: POST                                                            │
│  URL: https://graph.microsoft.com/v1.0/                                 │
│       teams/{teamId}/channels/{channelId}/messages/{messageId}/replies  │
│  Auth: Microsoft Graph Security OAuth2                                  │
│  Body: {{ $json }} ← Adaptive Card payload                              │
│                                                                          │
│  Purpose: Post formatted response as threaded reply                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Microsoft Teams Channel                          │
│                                                                          │
│  Original Message:                                                       │
│  👤 Ari Sela: "Check proteus service"                                   │
│                                                                          │
│  ↳ Reply (Adaptive Card):                                               │
│    ┌────────────────────────────────────────────────────────────────┐  │
│    │ 🤖 On-Call Assistant                                            │  │
│    ├────────────────────────────────────────────────────────────────┤  │
│    │ ✅ Proteus Pods Status - HEALTHY                                │  │
│    │                                                                 │  │
│    │ Overall: 5/5 pods running with zero restarts                   │  │
│    │                                                                 │  │
│    │ Key Health Indicators:                                          │  │
│    │ ✅ All pods Ready                                               │  │
│    │ ✅ Zero Restarts                                                │  │
│    │ ✅ Distributed across 3 nodes                                   │  │
│    ├────────────────────────────────────────────────────────────────┤  │
│    │ Query:     Check proteus service                                │  │
│    │ User:      Ari Sela                                             │  │
│    │ Timestamp: 2025-10-10T14:29:49.862Z                             │  │
│    └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Network Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           External Internet                               │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  Microsoft Graph API (graph.microsoft.com)                       │    │
│  │                                                                  │    │
│  │  • Webhook subscription validation                              │    │
│  │  • Message content delivery                                     │    │
│  │  • Reply posting                                                 │    │
│  │                                                                  │    │
│  │  Source IPs: 20.20.32.0/19, 20.190.128.0/18, etc.              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                       HTTPS (Port 443) ↓
                                    │
┌──────────────────────────────────────────────────────────────────────────┐
│                     External Webhook Ingress                              │
│                 n8n-dev-webhook.artemishealth.com                        │
│                                                                           │
│  • Valid SSL certificate (Let's Encrypt)                                 │
│  • IP Allowlist: Microsoft Graph + Power Automate IPs                   │
│  • Forwards to internal n8n service                                      │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                       Internal K8s Network ↓
                                    │
┌──────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster (dev-eks)                       │
│                                                                           │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │  n8n Service (n8n-dev.internal.artemishealth.com)              │     │
│  │                                                                 │     │
│  │  • Receives webhook from ingress                                │     │
│  │  • Processes workflow                                           │     │
│  │  • Makes outbound API calls                                     │     │
│  └────────────────────────────────────────────────────────────────┘     │
│                                                                           │
│  Outbound Connections:                                                   │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  oncall-agent.internal.artemishealth.com                        │    │
│  │                                                                  │    │
│  │  • Internal K8s monitoring API                                  │    │
│  │  • Analyzes dev-eks cluster                                     │    │
│  │  • Returns pod status, events, logs                             │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                       External API Calls ↓
                                    │
┌──────────────────────────────────────────────────────────────────────────┐
│                         External API Services                             │
│                                                                           │
│  ┌───────────────────────────────┐  ┌──────────────────────────────┐   │
│  │  Anthropic API                │  │  Microsoft Graph API          │   │
│  │  (api.anthropic.com)          │  │  (graph.microsoft.com)        │   │
│  │                               │  │                               │   │
│  │  • Claude Sonnet 4 inference  │  │  • Get message content        │   │
│  │  • Tool calling               │  │  • Post replies               │   │
│  │  • Response generation        │  │  • Adaptive Card rendering    │   │
│  └───────────────────────────────┘  └──────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Tool Execution Flow

```
AI Agent receives query: "Check proteus service"
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ AI Decision: This is a K8s service query            │
│ Tool to use: oncall_agent_query                     │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ oncall_agent_query Tool Execution                   │
│                                                      │
│ POST oncall-agent.internal.artemishealth.com/query  │
│ Body: {"prompt": "Check proteus service"}           │
│                                                      │
│ ↓ (2-8 seconds)                                     │
│                                                      │
│ Response: Markdown with pod status                  │
│ {                                                    │
│   "analysis": "✅ 5/5 pods running...",             │
│   "recommendations": ["..."]                         │
│ }                                                    │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ AI Agent Synthesis                                   │
│                                                      │
│ Combines tool output with reasoning                 │
│ Formats response with severity indicators           │
│ Adds context and recommendations                    │
└─────────────────────────────────────────────────────┘
    │
    ▼
Final response formatted and sent to Teams
```

---

## Alternative Flow: Website Health Check

```
AI Agent receives: "Is devops.artemishealth.com up?"
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ AI Decision: This is a website availability query   │
│ Tools to use: website_health_query first            │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ website_health_query Execution                       │
│                                                      │
│ GET https://devops.artemishealth.com                │
│                                                      │
│ ↓ (<1 second)                                       │
│                                                      │
│ Response: HTTP 200, 245ms                           │
└─────────────────────────────────────────────────────┘
    │
    ├─ IF HTTP 200 and fast: Report healthy ✅
    │
    └─ IF HTTP 5xx or slow:
            ▼
       ┌─────────────────────────────────────────────┐
       │ AI calls oncall_agent_query                 │
       │ Prompt: "Check backend services..."         │
       │                                             │
       │ ↓                                           │
       │                                             │
       │ Correlates website down + K8s issues        │
       │ Provides root cause analysis                │
       └─────────────────────────────────────────────┘
```

---

## Authentication Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                    Azure Active Directory                         │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  App Registration: n8n-teams-integration                    │ │
│  │                                                             │ │
│  │  Permissions:                                               │ │
│  │  • ChannelMessage.Read.All (delegated)                     │ │
│  │  • ChannelMessage.Send (delegated)                         │ │
│  │  • Team.ReadBasic.All (delegated)                          │ │
│  │  • offline_access (for refresh tokens)                     │ │
│  │                                                             │ │
│  │  Credentials:                                               │ │
│  │  • Client ID: <redacted>                                    │ │
│  │  • Client Secret: <redacted>                                │ │
│  │  • Tenant ID: 26405e3d-7860-4104-af91-84d019caf705         │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
                                │
                ┌───────────────┴────────────────┐
                ▼                                ▼
┌─────────────────────────────┐   ┌──────────────────────────────┐
│ n8n Credential:             │   │ n8n Credential:              │
│ Microsoft Teams OAuth2      │   │ MS Graph Security OAuth2     │
│                             │   │                              │
│ Used by:                    │   │ Used by:                     │
│ • Teams Trigger             │   │ • get_teams_message          │
│                             │   │ • reply_teams_thread         │
│                             │   │                              │
│ Scopes:                     │   │ Scopes:                      │
│ • Team/Channel reading      │   │ • ChannelMessage.Read.All    │
│ • Webhook subscriptions     │   │ • ChannelMessage.Send        │
└─────────────────────────────┘   └──────────────────────────────┘
```

---

## Data Format at Each Stage

### Stage 1: Teams Trigger Output
```json
{
  "id": "1760102547983",
  "@odata.type": "#Microsoft.Graph.chatMessage",
  "@odata.id": "teams('7ae...')/channels('19:a32...')/messages('1760...')"
}
```

### Stage 2: get_teams_message Output
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

### Stage 3: query_parser Output
```json
{
  "query": "Check proteus service",
  "source": "teams",
  "user": "Ari Sela",
  "namespace": "default",
  "timestamp": "2025-10-10T14:29:49.862Z"
}
```

### Stage 4: AI Agent Output
```json
{
  "output": "✅ **Proteus Pods Status - HEALTHY**\n\nOverall: 5/5 pods running...",
  "intermediate_steps": [
    {
      "tool": "oncall_agent_query",
      "input": "Check proteus service health...",
      "output": "..."
    }
  ]
}
```

### Stage 5: convert_response_teams Output
```json
{
  "body": {
    "contentType": "html",
    "content": "<attachment id=\"1\"></attachment>"
  },
  "attachments": [
    {
      "id": "1",
      "contentType": "application/vnd.microsoft.card.adaptive",
      "content": "{\"type\":\"AdaptiveCard\",\"version\":\"1.4\",\"body\":[...]}"
    }
  ]
}
```

### Stage 6: Teams Reply (Visual)
```
╔══════════════════════════════════════════════════════╗
║ 🤖 On-Call Assistant                                 ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║ ✅ Proteus Pods Status - HEALTHY                     ║
║                                                      ║
║ Overall: 5/5 pods running with zero restarts        ║
║                                                      ║
║ Key Health Indicators:                              ║
║ ✅ All pods Ready: 1/1 containers ready             ║
║ ✅ Zero Restarts: No stability issues               ║
║ ✅ Distributed Placement: 3 nodes                   ║
║                                                      ║
╠══════════════════════════════════════════════════════╣
║ Query:     Check proteus service                     ║
║ User:      Ari Sela                                  ║
║ Timestamp: 2025-10-10T14:29:49.862Z                 ║
╚══════════════════════════════════════════════════════╝
```

---

## Error Handling & Edge Cases

### Case 1: Empty Message
```
User sends image-only message (no text)
    ↓
query_parser detects no text content
    ↓
Throws error: "No text content in Teams message"
    ↓
Workflow fails gracefully (no spam in Teams)
```

### Case 2: oncall_agent_query Timeout
```
AI calls oncall_agent_query
    ↓
Request takes >120 seconds
    ↓
HTTP Request times out
    ↓
AI Agent receives timeout error
    ↓
AI responds: "Unable to query K8s cluster (timeout)"
```

### Case 3: Website Unreachable
```
AI calls website_health_query
    ↓
GET https://down-site.com fails
    ↓
Returns HTTP error details
    ↓
AI analyzes error → calls oncall_agent_query
    ↓
Provides root cause: "Site down, backend pods failing"
```

### Case 4: Multiple Tool Calls
```
User: "Check if devops.artemishealth.com is up and analyze proteus"
    ↓
AI plans: Use both tools
    ↓
Parallel execution:
  ├─ website_health_query → HTTP 200, 245ms
  └─ oncall_agent_query → 5/5 pods healthy
    ↓
AI correlates: "Website healthy, backend healthy"
```

---

## Performance Characteristics

### Execution Metrics

| Stage | Average Time | Notes |
|-------|--------------|-------|
| Teams Trigger | <100ms | Webhook delivery |
| get_teams_message | 300-800ms | Graph API call |
| query_parser | <50ms | JavaScript processing |
| AI Agent | 3-10s | Depends on tool calls |
| • website_health_query | 200ms-2s | External website speed |
| • oncall_agent_query | 2-8s | K8s cluster analysis |
| convert_response_teams | <50ms | JSON transformation |
| reply_teams_thread | 300-800ms | Graph API call |
| **Total** | **5-15 seconds** | End-to-end latency |

### Resource Usage

**Claude API Costs**:
- Input tokens: ~500-2000 per query (system message + query)
- Output tokens: ~500-1500 per response
- Tool calls: 0-2 per query
- Estimated cost: $0.003-0.01 per interaction

**n8n Executions**:
- 1 execution per Teams message
- Typical daily volume: 10-50 executions
- Monthly cost: Negligible (self-hosted n8n)

---

## Security Model

### Principle of Least Privilege

**What the Workflow CAN Do**:
- ✅ Read Teams channel messages
- ✅ Post replies to Teams
- ✅ HTTP GET to external websites
- ✅ Query oncall-agent API (read-only K8s analysis)

**What the Workflow CANNOT Do**:
- ❌ Deploy or modify K8s resources
- ❌ Restart pods or services
- ❌ Access production clusters (dev-eks only)
- ❌ Execute arbitrary commands
- ❌ Access user credentials

### Defense in Depth

**Layer 1: Network**
- IP allowlist on webhook ingress
- Internal network isolation
- SSL/TLS for all connections

**Layer 2: Authentication**
- OAuth2 for Teams/Graph API
- API keys for Claude and oncall-agent
- No shared credentials

**Layer 3: Application**
- oncall-agent enforces cluster restrictions
- AI agent limited to read-only tools
- No destructive operations available

**Layer 4: Audit**
- All queries logged in n8n executions
- Teams conversation history preserved
- oncall-agent logs all K8s API calls

---

## Comparison: Teams Integration vs Direct API

### Before (Direct API Mode)
```
User → Slack → n8n webhook → oncall-agent → Response
```
- Manual webhook setup
- No threading
- Plain text responses
- Single tool (oncall_agent only)

### After (Teams + AI Agent)
```
User → Teams → Graph API → n8n → AI Agent → Tools → Adaptive Card Reply
```
- Native Teams integration
- Threaded conversations
- Rich Adaptive Card formatting
- Dual tools (website + K8s analysis)
- Intelligent tool selection

---

## Future Enhancements

### Planned Features

1. **Conversation Context**
   - Track conversation threads
   - Maintain context across messages
   - "Remember what we discussed earlier"

2. **Proactive Monitoring**
   - Scheduled health checks
   - Post alerts to Teams automatically
   - Daily/weekly status reports

3. **Interactive Actions**
   - Adaptive Card buttons: "View Logs", "Check ArgoCD"
   - Action.Submit to trigger follow-up queries
   - Quick action menu: "Scale up", "View metrics"

4. **Multi-Cluster Support**
   - Extend to staging/production (with proper safeguards)
   - Cluster selection in query
   - Cross-cluster correlation

5. **Incident Management**
   - Create Jira tickets from critical findings
   - Link to PagerDuty incidents
   - Incident correlation across services

---

## Version History

### v2.0 (2025-10-10)
- ✅ Microsoft Teams integration with webhook subscription fix
- ✅ Adaptive Card responses with rich formatting
- ✅ Threaded replies (conversation context)
- ✅ Dual tool system (website + K8s)
- ✅ Enhanced query parser (multi-source support)
- ✅ Claude Sonnet 4 upgrade
- ✅ Comprehensive error handling

### v1.0 (Previous)
- Basic Slack webhook integration
- Single tool (oncall_agent only)
- Plain text responses
- No threading

---

## Support & Maintenance

### Responsibility

**Maintained By**: ArtemisHealth DevOps Team
**Primary Contact**: Ari Sela
**SLA**: Best effort (internal tool)

### Update Schedule

**Monthly**:
- Review Microsoft Graph API IP ranges
- Update ingress allowlist if needed
- Check for n8n version updates

**Quarterly**:
- Review AI agent system message for accuracy
- Analyze usage patterns and optimize prompts
- Update service mappings for new services

**As Needed**:
- Respond to Microsoft Graph API changes
- Fix bugs reported by users
- Add new features based on feedback

### Backup & Recovery

**Workflow Backup**:
- Exported to: `docs/n8n-workflows/dev-eks-oncall-engineer-v2.json`
- Version controlled in git
- Re-importable at any time

**Credential Backup**:
- Store Client IDs, Secrets in secure password manager
- Document in team wiki (not in git!)
- Rotate credentials quarterly

---

## FAQs

### Q: Why do I need two different Microsoft credentials?

**A**: Microsoft Teams OAuth2 is for the trigger (webhook subscriptions), while Graph Security OAuth2 is for API calls (get/send messages). They use the same Azure app but different scope configurations in n8n.

---

### Q: Can I use this in other Teams channels?

**A**: Yes! Either duplicate the workflow and change the channel in the trigger, or modify the trigger to respond to all channels in the team.

---

### Q: How much does this cost to run?

**A**: Minimal:
- n8n: Self-hosted (no per-execution cost)
- Claude API: ~$0.005 per query
- Graph API: Free (within standard limits)
- Monthly total: <$5 for typical usage

---

### Q: What happens if oncall-agent is down?

**A**: The workflow fails gracefully. The AI agent receives a timeout/error from the tool and can respond with: "Unable to query K8s cluster. Please check oncall-agent service status."

---

### Q: Can the AI make changes to K8s?

**A**: No. Both tools are read-only. The AI can only analyze and recommend - it cannot deploy, restart, or modify resources.

---

### Q: How do I add a new service to monitor?

**A**: Update the AI Agent system message with the new service mapping:
```
**newservice.artemishealth.com**:
- Services: new-service
- Namespaces: new-service-dev
- Critical path: new-service only
```

The AI will automatically include it in health checks.

---

## References

- **n8n Workflow**: `dev-eks-oncall-engineer-v2.json`
- **IP Allowlist Guide**: `../n8n-integrations/IMPLEMENTATION-GUIDE.md`
- **oncall-agent API**: `../../src/integrations/orchestrator.py`
- **Claude Agent SDK**: https://github.com/anthropics/anthropic-agent-sdk
- **Microsoft Graph API**: https://learn.microsoft.com/en-us/graph/
- **Adaptive Cards**: https://adaptivecards.io/

---

**Status**: ✅ Production Ready
**Last Tested**: 2025-10-10
**Workflow ID**: lfMAty5yRDS1lIuA
