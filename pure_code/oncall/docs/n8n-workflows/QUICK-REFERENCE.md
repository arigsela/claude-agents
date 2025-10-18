# n8n On-Call Engineer - Quick Reference Guide

## Common Commands to Send in Teams

### Kubernetes Service Checks

```
Check proteus service
Check proteus pods in proteus-dev namespace
What's the status of hermes?
Show me all pods in artemis-auth-dev
Are there any pod restarts in zeus-dev?
```

### Website Health Checks

```
Is devops.artemishealth.com up?
Check https://api.artemishealth.com
Test the website https://auth.artemishealth.com
Why is devops.artemishealth.com slow?
```

### Combined Analysis

```
Do a full health check on our services
Check devops.artemishealth.com and its backend services
Why is the app down?
Troubleshoot api.artemishealth.com
```

### Specific Investigations

```
Show me recent events in proteus-dev namespace
Check for OOMKilled pods
What deployments happened in the last hour?
Are there any ImagePullBackOff errors?
```

---

## Expected Response Times

| Query Type | Typical Time |
|------------|--------------|
| Simple service check | 5-8 seconds |
| Website health | 3-5 seconds |
| Combined website + K8s | 8-12 seconds |
| Full cluster audit | 10-15 seconds |

---

## Response Format Examples

### Healthy Service
```
✅ Proteus Pods Status - HEALTHY

Overall: 5/5 pods running with zero restarts

Key Health Indicators:
✅ All pods Ready: 1/1 containers ready in each pod
✅ Zero Restarts: No stability issues detected
✅ Distributed Placement: Well-distributed across 3 nodes
```

### Critical Issue
```
🔴 Proteus Pods Status - CRITICAL

Overall: 0/5 pods ready (CrashLoopBackOff)

Issues Detected:
❌ All pods in CrashLoopBackOff
❌ 15 restarts in last 10 minutes
❌ Recent deployment may have introduced issues

Root Cause:
- Container failing to start
- Error: "ECONNREFUSED connecting to database"

Recommended Actions:
1. Check database connectivity from proteus pods
2. Verify database credentials in Secrets
3. Review recent deployment changes
```

---

## Troubleshooting Your Query

### If you get no response:

1. **Check workflow is active**: Look for green "Active" status in n8n
2. **Verify channel**: Make sure you're posting in "oncall-engineer" channel
3. **Check n8n logs**: Look for execution errors

### If response is generic (not using tools):

**Too vague**: ❌ `"Check stuff"`
**Better**: ✅ `"Check proteus service in proteus-dev"`

**Too vague**: ❌ `"Is it up?"`
**Better**: ✅ `"Is https://devops.artemishealth.com up?"`

### If you get an error message:

**"No text content in Teams message"**
→ Send a text message (not just images/files)

**"Unable to query K8s cluster (timeout)"**
→ oncall-agent API may be down or slow
→ Try a simpler query or check oncall-agent service

**"Website check failed: Invalid URL"**
→ Include full URL with https:// prefix

---

## Service Name Quick Reference

Use these exact service names for best results:

### Core Services
- `proteus` → Main application backend
- `artemis-auth` → Authentication/SSO
- `hermes` → Messaging/notifications
- `zeus` → Core service
- `plutus` → Financial processing

### Namespaces
- `proteus-dev`
- `artemis-auth-dev` (or `artemis-auth-preprod`)
- `hermes-dev`
- `zeus-dev`
- `plutus-dev`

### Websites
- `https://devops.artemishealth.com`
- `https://api.artemishealth.com`
- `https://auth.artemishealth.com`
- `https://app.artemishealth.com`

---

## Tips for Best Results

### ✅ Do:
- Be specific about service and namespace
- Include full URLs for website checks (https://)
- Ask follow-up questions in the same thread
- Use service names from the reference list

### ❌ Don't:
- Send image-only messages
- Use vague terms like "stuff" or "things"
- Expect the AI to remember context (each message is independent)
- Ask about production clusters (only dev-eks supported)

---

## Emergency Commands

### Critical Service Down
```
Check proteus service urgently - seeing 5xx errors
Full diagnostic on artemis-auth - login is broken
Emergency check on all critical services
```

### Performance Issues
```
Why is devops.artemishealth.com responding slowly?
Check for high CPU or memory in proteus pods
Are there any resource constraints in hermes-dev?
```

### After Deployment
```
Verify the proteus deployment that just completed
Check if the new hermes version is stable
Are there any issues after the recent deployment?
```

---

## Advanced Query Patterns

### Time-Based
```
Show me pod events from the last hour
What deployments happened in the last 30 minutes?
Check for restarts in the last 5 minutes
```

### Multi-Service
```
Compare health of proteus vs hermes
Check all services in artemis-auth-dev namespace
What's the overall cluster health?
```

### Correlation
```
Is the website down because of K8s issues?
Correlate devops.artemishealth.com status with backend health
Why did the site go down at 2pm?
```

---

## Metadata in Responses

Every response includes:

**Query**: Your original question
**User**: Your display name from Teams
**Timestamp**: When you asked (ISO 8601 format)

This helps with:
- Audit trail
- Troubleshooting workflow issues
- Understanding query context later

---

## Integration Points

### Oncall Agent API

**Endpoint**: `https://oncall-agent.internal.artemishealth.com/query`

**Request Format**:
```json
{
  "prompt": "Check proteus service in proteus-dev"
}
```

**Response Format**:
```json
{
  "analysis": "✅ **Proteus Pods - HEALTHY**\n\n...",
  "severity": "healthy",
  "recommendations": [...]
}
```

### Website Health Tool

**Endpoint**: Dynamic (URL from AI decision)

**Request**: HTTP GET to specified URL

**Response**: HTTP status, timing, body preview

---

## Keyboard Shortcuts (Teams)

- `Ctrl/Cmd + K` → Search for "oncall-engineer" channel
- `Shift + Enter` → New line (multi-line queries)
- `@On-Call Assistant` → Mention the bot (future feature)

---

## Best Practices

### For DevOps Team

1. **Use consistently** - Build muscle memory with common commands
2. **Share findings** - Copy AI responses to incident threads
3. **Verify critical issues** - Always double-check AI recommendations
4. **Provide feedback** - Report inaccuracies to improve system message

### For Workflow Maintenance

1. **Monitor execution logs** weekly
2. **Review query patterns** monthly
3. **Update service mappings** when new services added
4. **Test after n8n updates** to ensure compatibility

---

## Getting Help

### Workflow Issues

1. Check n8n execution logs
2. Review README.md for configuration
3. Verify credentials are valid
4. Check network connectivity

### AI Response Quality

1. Review system message in AI Agent node
2. Check if tools are being called (execution logs)
3. Verify oncall-agent API is returning good data
4. Adjust prompts to be more specific

### Microsoft Teams Integration

1. Review IMPLEMENTATION-GUIDE.md for IP allowlist
2. Check Graph API credential is valid
3. Verify webhook subscription is active
4. Test with simple message first

---

## Quick Start Checklist

For new team members using this workflow:

- [ ] Join the "oncall-engineer" Teams channel
- [ ] Post test message: `"Check hermes service"`
- [ ] Verify you get a formatted Adaptive Card response
- [ ] Review common commands above
- [ ] Bookmark this quick reference
- [ ] Try a few example queries
- [ ] Report any issues to DevOps team

---

**Need more details?** See the full README.md in this directory.

**Last Updated**: 2025-10-10
