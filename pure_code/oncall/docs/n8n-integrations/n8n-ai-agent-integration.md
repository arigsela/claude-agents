# n8n AI Agent Integration Guide

## Architecture: n8n AI Agent Using OnCall API as a Tool

```
┌─────────────────────────────────────────────────────────────┐
│ User: "Is proteus having issues in dev?"                    │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ n8n AI Agent (GPT-4/Claude)                                 │
│ - Maintains conversation with user                          │
│ - Decides when to use Kubernetes troubleshooting tool       │
│ - Orchestrates multiple tool calls if needed                │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼ Tool Call
┌─────────────────────────────────────────────────────────────┐
│ Your OnCall API (http://api:8000/query)                    │
│ POST /query                                                 │
│ {                                                           │
│   "prompt": "Check proteus service status in dev-eks",     │
│   "namespace": "proteus-dev"                                │
│ }                                                           │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ OnCall Agent analyzes K8s cluster                          │
│ - Checks pod status, events, logs                          │
│ - Correlates with GitHub deployments                        │
│ - Returns detailed technical analysis                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼ Returns structured data
┌─────────────────────────────────────────────────────────────┐
│ n8n AI Agent synthesizes response                          │
│ "Proteus is healthy with 3 running pods. Last deployment   │
│  was 2 hours ago with no errors detected."                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│ User gets final answer                                      │
└─────────────────────────────────────────────────────────────┘
```

## Recommended Pattern: Stateless Tool Calls

### Why NOT Use Sessions with n8n AI Agent

**n8n's AI Agent already maintains conversation context:**
- It remembers what the user asked
- It decides what tools to call and when
- It synthesizes information from multiple tool calls
- Adding sessions to your API creates **redundant context management**

### Recommended: Focused, Stateless Queries

**Configure your OnCall API as a Kubernetes expert tool:**

```javascript
// n8n AI Agent Tool Configuration
{
  "name": "kubernetes_troubleshoot",
  "description": "Expert tool for Kubernetes cluster analysis. Can check pod status, analyze incidents, review logs, and correlate with deployments. ONLY works with dev-eks cluster. Returns detailed technical analysis.",

  "parameters": {
    "prompt": {
      "type": "string",
      "description": "Specific question or instruction for K8s analysis. Be explicit - include service names, namespaces, and what to check.",
      "required": true
    },
    "namespace": {
      "type": "string",
      "description": "Kubernetes namespace to focus on (e.g., 'proteus-dev', 'hermes-dev')",
      "default": "default"
    }
  },

  "endpoint": "POST http://oncall-api:8000/query",

  "request_body": {
    "prompt": "{{ $params.prompt }}",
    "namespace": "{{ $params.namespace }}",
    "context": {
      "n8n_user": "{{ $user }}",
      "n8n_workflow": "{{ $workflow.name }}",
      "source": "n8n-ai-agent"
    }
  }
}
```

### How n8n AI Agent Will Use It

**Example Conversation:**

**User:** "Is proteus having any issues?"

**n8n AI Agent (internal):**
```
Thought: User asking about proteus service health. I should use kubernetes_troubleshoot tool.

Tool Call:
{
  "prompt": "Check the status of proteus service in dev-eks cluster. Include pod health, recent restarts, and any error events.",
  "namespace": "proteus-dev"
}
```

**Your API Response:**
```json
{
  "responses": [{
    "content": "Proteus service analysis:\n- 3 pods running (proteus-api-xxx, proteus-worker-xxx, proteus-scheduler-xxx)\n- All pods healthy, 0 restarts in last 24h\n- No error events detected\n- Last deployment: 2 hours ago via GitHub Actions (successful)"
  }]
}
```

**n8n AI Agent → User:**
"Proteus looks healthy! All 3 pods are running normally with no recent issues."

---

**User:** "What about recent deployments?"

**n8n AI Agent (internal):**
```
Thought: User asking about deployments. Context: We're discussing proteus.
I'll ask specifically about proteus deployments.

Tool Call:
{
  "prompt": "Show recent GitHub deployments for proteus service in the last 24 hours",
  "namespace": "proteus-dev"
}
```

Notice: **n8n AI Agent** added "proteus" to the prompt based on its conversation memory!

## Alternative: Sessions for Audit Trail Only

If you want to track what n8n asks for audit purposes:

```javascript
// In n8n: Create session per execution
const sessionId = $workflow.id + '-' + $execution.id;

// All tool calls use this session
{
  "prompt": "{{ $params.prompt }}",
  "session_id": sessionId,  // Track all queries in this n8n execution
  "context": {
    "n8n_user": "{{ $user }}",
    "n8n_execution_id": "{{ $execution.id }}"
  }
}
```

**Benefits:**
- ✅ Audit trail of all queries per n8n execution
- ✅ Can review what n8n AI Agent asked
- ✅ Rate limiting per execution (prevent runaway loops)

**Drawback:**
- Session context won't help n8n AI Agent (it maintains its own context)
- But still useful for logging/debugging

## Specific Recommendations

### For Your Use Case (n8n AI Agent + K8s Troubleshooting)

**1. Keep Sessions for Audit, NOT for Context**
```javascript
// n8n workflow
const sessionId = `n8n-${$workflow.id}-${$execution.id}`;

// Every tool call
{
  "prompt": "Detailed, specific question with all needed context",
  "session_id": sessionId,  // For audit trail only
  "context": {
    "user": $user,
    "execution": $execution.id
  }
}
```

**2. Make n8n AI Agent's prompts EXPLICIT**

Instead of:
```javascript
❌ "prompt": "Check if it's having issues"  // Who is "it"?
```

n8n AI Agent should call with:
```javascript
✅ "prompt": "Check if proteus service in proteus-dev namespace is having issues"
```

**3. Configure Your API as a Specialized Tool**

The n8n AI Agent tool description should guide it to make focused calls:

```javascript
{
  "description": "Kubernetes troubleshooting expert for dev-eks cluster.

  When calling this tool:
  - Always specify the service name explicitly
  - Include the namespace if known
  - Ask specific questions (e.g., 'Check pod restarts for proteus in proteus-dev')
  - Don't use pronouns like 'it' - be explicit

  The tool can:
  - Check pod status and health
  - Analyze error events and logs
  - Correlate with recent deployments
  - Provide remediation recommendations

  Returns detailed technical analysis suitable for DevOps teams."
}
```

## Implementation Choice

Based on your n8n AI Agent use case, I recommend:

### **Keep Current Implementation (No Context Passing)**

**Why:**
- ✅ n8n AI Agent will make explicit, focused queries
- ✅ Each API call is self-contained and specific
- ✅ Simpler, more predictable behavior
- ✅ Lower token costs
- ✅ Easier to debug (each call independent)

**But keep sessions for:**
- Audit trail (what did n8n AI Agent ask?)
- Rate limiting per n8n execution
- Tracking API usage by user

### Alternative: Add Context Only for Direct Human Use

Add a parameter to control context passing:

```python
class QueryRequest(BaseModel):
    prompt: str
    namespace: Optional[str] = "default"
    session_id: Optional[str] = None
    use_session_context: bool = False  # ← New parameter
```

Then in the endpoint:
```python
if session and query_request.use_session_context:
    # Include conversation history
    history_text = build_context(session.conversation_history)
    full_query = f"{history_text}\n\n{full_query}"
```

**Usage:**
- n8n AI Agent: `use_session_context: false` (default)
- Direct human API calls: `use_session_context: true`

## What Should I Implement?

Given your n8n AI Agent use case, I recommend:

**Option A (Recommended):** Keep current implementation
- Sessions store audit trail
- No automatic context passing
- n8n AI Agent makes explicit queries

**Option B:** Add `use_session_context` flag
- Default false for n8n
- Optional true for direct human interaction

**Option C:** Implement smart context (last 3 messages)
- Always pass context
- May be redundant with n8n AI Agent

Which approach fits your workflow best?