# Microsoft Teams Integration via Power Automate

This guide explains how to set up Teams integration using Power Automate when native Outgoing Webhooks are disabled in your organization.

## Why Power Automate?

Many organizations disable Outgoing Webhooks for security reasons. Power Automate provides an alternative way to trigger the OnCall Agent from Teams:

| Feature | Outgoing Webhook | Power Automate |
|---------|-----------------|----------------|
| Setup | Team settings | Power Automate portal |
| Authentication | HMAC-SHA256 | API Key |
| Admin Required | Team owner | Flow creator |
| Availability | Often restricted | Usually available |

## Prerequisites

1. **Power Automate access** (Microsoft 365 license)
2. **OnCall Agent deployed** with external ingress:
   - Endpoint: `https://oncall-agent-webhook.artemishealth.com/teams/webhook`
3. **API Key configured** in the deployment:
   ```bash
   TEAMS_API_KEY=your-secure-api-key
   ```

## Step-by-Step Setup

### Step 1: Generate API Key

Generate a secure API key for Power Automate:

```bash
# Generate a strong random key
openssl rand -base64 32

# Example output: x7K9mNpQrS2tVwXyZ1234567890abcdefghij==
```

Add this key to your deployment:
- **Local**: Add to `.env` file: `TEAMS_API_KEY=your-key`
- **Kubernetes**: Add to Secret and update deployment

### Step 2: Create Power Automate Flow

1. Go to [Power Automate](https://make.powerautomate.com/)
2. Click **Create** → **Automated cloud flow**
3. Name it: "OnCall Agent Teams Integration"
4. Search for trigger: **"When a keyword is mentioned"** (Teams)
5. Click **Create**

### Step 3: Configure Teams Trigger

1. **Select Team**: Choose your team
2. **Select Channel**: Choose the channel to monitor
3. **Keyword to monitor**: `@OnCall` or any trigger word you prefer

### Step 4: Add HTTP Action

1. Click **+ New step**
2. Search for **HTTP**
3. Select **HTTP** action
4. Configure:

   **Method**: `POST`

   **URI**: `https://oncall-agent-webhook.artemishealth.com/teams/webhook`

   **Headers**:
   ```
   Content-Type: application/json
   Authorization: Bearer YOUR_API_KEY_HERE
   ```

   **Body**:
   ```json
   {
     "type": "message",
     "id": "@{triggerOutputs()?['body/messageId']}",
     "timestamp": "@{utcNow()}",
     "text": "@{triggerOutputs()?['body/messageText']}",
     "from": {
       "id": "@{triggerOutputs()?['body/from/id']}",
       "name": "@{triggerOutputs()?['body/from/displayName']}"
     },
     "conversation": {
       "id": "@{triggerOutputs()?['body/channelIdentity/channelId']}",
       "tenantId": "@{triggerOutputs()?['body/tenantId']}"
     },
     "channelId": "msteams",
     "serviceUrl": "https://smba.trafficmanager.net/teams/"
   }
   ```

### Step 5: Add Response Action

1. Click **+ New step**
2. Search for **"Post message in a chat or channel"** (Teams)
3. Configure:
   - **Post as**: Flow bot
   - **Post in**: Channel
   - **Team**: Same team
   - **Channel**: Same channel
   - **Message**:
   ```
   @{body('HTTP')?['attachments']?[0]?['content']?['body']?[0]?['text']}
   ```

   Or for Adaptive Card response:
   ```
   @{body('HTTP')}
   ```

### Step 6: Save and Test

1. Click **Save**
2. Go to your Teams channel
3. Type: `@OnCall check cluster health`
4. Wait for response (may take 5-15 seconds)

## Alternative: Simpler Message Parsing

If the dynamic content above is complex, use this simplified body:

```json
{
  "type": "message",
  "id": "pa-@{guid()}",
  "timestamp": "@{utcNow()}",
  "text": "@{triggerOutputs()?['body/messageText']}",
  "from": {
    "id": "@{triggerOutputs()?['body/from/id']}",
    "name": "@{coalesce(triggerOutputs()?['body/from/displayName'], 'Teams User')}"
  },
  "conversation": {
    "id": "pa-@{triggerOutputs()?['body/channelIdentity/teamId']}"
  },
  "channelId": "msteams",
  "serviceUrl": "https://smba.trafficmanager.net/teams/"
}
```

## Testing Locally

Test the API key authentication before deploying:

```bash
# Start local server
docker compose up -d

# Test with API key
python3 scripts/test_teams_webhook.py --api-key "hello"

# Or with custom key
python3 scripts/test_teams_webhook.py --api-key --key "your-key" "check health"
```

## Security Considerations

1. **Strong API Key**: Use at least 32 characters
2. **HTTPS Only**: Never use HTTP for webhook URL
3. **WAF Protection**: The external ingress uses AWS WAF
4. **Key Rotation**: Rotate API keys periodically
5. **Audit Logging**: All requests are logged

## Troubleshooting

### Flow not triggering
- Check keyword matches exactly (case-sensitive)
- Verify channel/team selection
- Check flow is turned on

### HTTP 401 Unauthorized
- Verify API key in `Authorization: Bearer {key}` header
- Check `TEAMS_API_KEY` environment variable is set
- Ensure no trailing spaces in API key

### HTTP 503 Service Unavailable
- Neither `TEAMS_WEBHOOK_SECRET` nor `TEAMS_API_KEY` is configured
- Check environment variables in deployment

### Response not posting to Teams
- Check HTTP action succeeded (200 response)
- Verify Teams action has correct channel
- Check response format matches expected structure

## Flow Template

Here's the complete flow in pseudo-JSON:

```json
{
  "trigger": {
    "type": "When a keyword is mentioned (Teams)",
    "team": "Your Team",
    "channel": "Your Channel",
    "keyword": "@OnCall"
  },
  "actions": [
    {
      "type": "HTTP",
      "method": "POST",
      "uri": "https://oncall-agent-webhook.artemishealth.com/teams/webhook",
      "headers": {
        "Content-Type": "application/json",
        "Authorization": "Bearer YOUR_API_KEY"
      },
      "body": "{ Teams Activity JSON }"
    },
    {
      "type": "Post message in a chat or channel",
      "team": "Your Team",
      "channel": "Your Channel",
      "message": "@{HTTP response}"
    }
  ]
}
```

## Comparison with Native Webhook

| Aspect | Native Outgoing Webhook | Power Automate |
|--------|------------------------|----------------|
| Response Time | ~2-5 seconds | ~5-15 seconds |
| Setup Complexity | Low | Medium |
| Admin Required | Team owner | None (flow creator) |
| Customization | Limited | High (conditional logic, etc.) |
| Cost | Free | Included in M365 |
| HMAC Security | Yes | API Key only |

## Next Steps

1. Set up the Power Automate flow
2. Test with a simple message
3. Add error handling to the flow (try/catch)
4. Consider adding conditional logic (e.g., only respond to specific keywords)
5. Set up monitoring for flow failures
