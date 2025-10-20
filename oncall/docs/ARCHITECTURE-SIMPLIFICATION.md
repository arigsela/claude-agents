# API Architecture Simplification - Remove Nested Agentic Loops

## The Problem: Nested AI Agents

You've identified a critical architectural issue! Currently we have **two AI agents**:

```
┌─────────────────────────────────────┐
│ n8n AI Agent (Orchestrator)         │
│ - Claude Haiku 4.5                  │
│ - Conversation memory               │
│ - Multi-step reasoning              │
│ - Tools:                            │
│   ├─ oncall_agent_query ──────┐    │
│   └─ website_health_query      │    │
└────────────────────────────────│────┘
                                 │
                                 ▼
                    ┌────────────────────────────┐
                    │ OnCall API (Tool Agent)    │
                    │ - Claude Haiku 4.5         │
                    │ - NO memory (stateless)    │
                    │ - Multi-step reasoning     │ ← NESTED AGENT!
                    │ - Agentic tool loop        │
                    │ - 14 K8s/GitHub/AWS tools  │
                    └────────────────────────────┘
```

**This is problematic because:**

1. ❌ **Double LLM costs**: n8n's Claude + API's Claude both running
2. ❌ **Slower responses**: API does its own multi-round tool calling
3. ❌ **Loss of control**: n8n orchestrator can't see API's internal reasoning
4. ❌ **Harder debugging**: Two agents both "thinking" makes it unclear who decided what
5. ❌ **Complexity**: Nested agentic loops are hard to reason about

## Current API Behavior (Agentic)

From `src/api/agent_client.py` lines 476-549:

```python
async def query(self, prompt: str) -> Dict[str, Any]:
    """Send query to Claude and handle tool calls."""
    messages = [{"role": "user", "content": prompt}]

    # Initial LLM call
    response = self.client.messages.create(
        model=self.model,
        max_tokens=4096,
        system=self.system_prompt,
        messages=messages,
        tools=self.tools  # 14 K8s/GitHub/AWS tools
    )

    # AGENTIC LOOP - API does multiple rounds of thinking!
    while response.stop_reason == "tool_use":
        tool_calls = [block for block in response.content if block.type == "tool_use"]

        # Execute tools
        for tool_call in tool_calls:
            result = await self._execute_tool(tool_call.name, tool_call.input)
            tool_results.append(...)

        # Ask Claude again with tool results
        response = self.client.messages.create(...)  # ← Multiple LLM calls!

    return {"response": response.content[0].text}
```

**What happens**:
1. n8n sends: `"Check proteus pods"`
2. API's Claude thinks: "I need to call list_namespaces, then list_pods"
3. API calls list_namespaces → gets result
4. API calls Claude again with result
5. API's Claude thinks: "Now call list_pods"
6. API calls list_pods → gets result
7. API calls Claude again with result
8. API's Claude thinks: "Here's my analysis..."
9. API returns final text to n8n

**n8n AI Agent only sees the final output** - it has no visibility into the API's tool usage!

## Proposed Architecture: Simple REST API

Make the API a **"dumb" REST wrapper** - just expose K8s operations as endpoints:

```
┌─────────────────────────────────────────┐
│ n8n AI Agent (Single Orchestrator)      │
│ - Claude Haiku 4.5                      │
│ - Conversation memory                   │
│ - Multi-step reasoning                  │
│ - Tools:                                │
│   ├─ list_k8s_namespaces ─────┐        │
│   ├─ list_k8s_pods ────────────┼──┐     │
│   ├─ get_pod_logs ─────────────┼──┼──┐  │
│   ├─ get_pod_events ───────────┼──┼──┤  │
│   ├─ search_github_deployments ┼──┼──┤  │
│   ├─ check_aws_secrets ────────┼──┼──┤  │
│   ├─ query_datadog_metrics ────┼──┼──┤  │
│   └─ website_health_query ─────┘  │  │  │
└───────────────────────────────────┼──┼──┘
                                    │  │
                                    ▼  ▼
                        ┌──────────────────────┐
                        │ OnCall API (Dumb)    │
                        │ - NO LLM             │
                        │ - NO agent behavior  │
                        │ - Just REST wrappers │
                        │ - Returns raw data   │
                        └──────────────────────┘
```

### New API Structure (Non-Agentic)

```python
# Simple REST endpoints - NO LLM, NO agentic behavior

@app.get("/k8s/namespaces")
async def list_namespaces(pattern: Optional[str] = None):
    """List K8s namespaces, optionally filtered by pattern."""
    # Direct K8s API call
    namespaces = k8s_client.list_namespace()
    if pattern:
        namespaces = [ns for ns in namespaces if pattern in ns.metadata.name]
    return {"namespaces": [ns.metadata.name for ns in namespaces]}

@app.get("/k8s/pods")
async def list_pods(namespace: str, label_selector: Optional[str] = None):
    """List pods in a namespace."""
    # Direct K8s API call
    pods = k8s_client.list_namespaced_pod(namespace, label_selector=label_selector)
    return {"pods": [format_pod(p) for p in pods.items]}

@app.get("/k8s/logs/{namespace}/{pod_name}")
async def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 100):
    """Get pod logs."""
    # Direct K8s API call
    logs = k8s_client.read_namespaced_pod_log(pod_name, namespace, tail_lines=tail_lines)
    return {"logs": logs}

@app.get("/github/deployments/{repo}")
async def search_deployments(repo: str, hours: int = 24):
    """Search recent GitHub deployments."""
    # Direct GitHub API call
    workflows = github_client.search_workflow_runs(repo, hours)
    return {"deployments": workflows}

@app.get("/datadog/metrics")
async def query_metrics(metric: str, time_window_hours: int = 1):
    """Query Datadog metrics."""
    # Direct Datadog API call
    data = datadog_client.query_metrics(metric, time_window_hours)
    return {"metrics": data}
```

### Updated n8n Workflow

Instead of ONE tool (`oncall_agent_query`), the n8n AI Agent gets **direct access to all operations**:

```javascript
// n8n AI Agent tools (all direct API calls):

1. list_k8s_namespaces
   URL: GET http://oncall-agent/k8s/namespaces?pattern={pattern}

2. list_k8s_pods
   URL: GET http://oncall-agent/k8s/pods?namespace={namespace}&label_selector={labels}

3. get_pod_logs
   URL: GET http://oncall-agent/k8s/logs/{namespace}/{pod_name}?tail_lines={lines}

4. get_pod_events
   URL: GET http://oncall-agent/k8s/events/{namespace}?pod_name={pod}

5. search_github_deployments
   URL: GET http://oncall-agent/github/deployments/{repo}?hours={hours}

6. check_aws_secret
   URL: GET http://oncall-agent/aws/secrets/{secret_name}

7. query_datadog_metrics
   URL: GET http://oncall-agent/datadog/metrics?metric={metric}&time_window_hours={hours}

8. website_health_query
   URL: GET {url} (existing tool)
```

## Benefits of Simplification

### ✅ Single Agent (n8n Orchestrator)

1. **Full visibility**: n8n sees every tool call and result
2. **Easier debugging**: One agent's reasoning to follow
3. **Better control**: Business logic in one place
4. **Cost savings**: Only ONE LLM instance (n8n's Claude)
5. **Faster**: No nested LLM calls in the API

### ✅ Simple API (REST Wrapper)

1. **Predictable**: Just returns data, no "thinking"
2. **Testable**: Easy to test with curl
3. **Reusable**: Can be called from anywhere (not just n8n)
4. **Maintainable**: No complex agentic logic
5. **Clear contract**: REST API with defined inputs/outputs

### ✅ Example Flow

**Before** (nested agents):
```
User: "Check proteus pods"
  ↓
n8n Agent: "I'll call oncall_agent_query"
  ↓
API Agent: "Let me think... I need list_namespaces"
API calls list_namespaces → result
API Agent: "Now I need list_pods"
API calls list_pods → result
API Agent: "Here's my analysis: ..."
  ↓
n8n Agent: [receives text, no visibility into tool calls]
n8n: "Response from API: ..."
```

**After** (single agent):
```
User: "Check proteus pods"
  ↓
n8n Agent: "I need to find proteus namespaces first"
n8n calls list_k8s_namespaces(pattern="proteus") → ["proteus-dev", "proteus-prod"]
  ↓
n8n Agent: "Now check pods in proteus-dev"
n8n calls list_k8s_pods(namespace="proteus-dev") → [pod data]
  ↓
n8n Agent: "I found 3 pods, 1 has issues. Let me get logs"
n8n calls get_pod_logs(namespace="proteus-dev", pod="proteus-abc") → [logs]
  ↓
n8n Agent: "Based on the logs and business context (CRITICAL service), here's my analysis..."
n8n: [Complete response with full context]
```

**n8n has FULL visibility** into every step!

## Migration Path

### Phase 1: Add Direct REST Endpoints (parallel to existing)

Add new REST endpoints alongside the current `/query` endpoint:

```python
# api_server.py

# OLD (keep for now)
@app.post("/query")
async def query_agent(request: QueryRequest):
    """Agentic query - will be deprecated."""
    return await agent_client.query(request.prompt)

# NEW (add these)
@app.get("/k8s/namespaces")
async def list_namespaces(pattern: Optional[str] = None):
    """Direct K8s namespace listing."""
    return list_namespaces(pattern)

@app.get("/k8s/pods")
async def list_pods(namespace: str, label_selector: Optional[str] = None):
    """Direct K8s pod listing."""
    return list_pods(namespace, label_selector)

# ... add all 14 tools as direct endpoints
```

### Phase 2: Update n8n Workflow

Change from 1 tool to 14 tools:

```javascript
// OLD
oncall_agent_query: POST /query {"prompt": "..."}

// NEW (add all 14 as separate tools)
list_k8s_namespaces: GET /k8s/namespaces?pattern=...
list_k8s_pods: GET /k8s/pods?namespace=...
get_pod_logs: GET /k8s/logs/{namespace}/{pod}
// ... etc
```

### Phase 3: Test Both Approaches

Run both in parallel:
- Keep `/query` endpoint (agentic)
- Use new REST endpoints (non-agentic)
- Compare results and performance

### Phase 4: Deprecate Agentic API

Once confident:
1. Remove `/query` endpoint
2. Remove `agent_client.py` (Anthropic SDK usage)
3. Keep only simple REST wrappers
4. Update requirements.txt (remove anthropic SDK)

## Code Reduction

**Before**:
- `agent_client.py`: 600+ lines (agentic logic + tool definitions)
- Anthropic SDK dependency
- Complex error handling for LLM calls

**After**:
- Simple REST endpoints: ~200 lines
- No LLM dependency
- Simple error handling (just K8s/GitHub/AWS APIs)

**Reduction**: ~67% less code in the API!

## Recommendation

**YES - Simplify the API!**

You're absolutely right to question this. The nested agentic architecture is:
- ❌ More complex than needed
- ❌ More expensive (2 LLMs)
- ❌ Slower (nested loops)
- ❌ Less transparent (n8n can't see tool usage)

**Benefits of simplification**:
- ✅ Single source of intelligence (n8n orchestrator)
- ✅ Full visibility into reasoning
- ✅ Lower cost (1 LLM instead of 2)
- ✅ Faster responses
- ✅ Simpler codebase

## Next Steps

1. Review this proposal
2. Decide: Gradual migration (Phase 1-4) or full replacement?
3. I can implement either approach:
   - **Gradual**: Add REST endpoints, keep `/query` for now
   - **Full**: Replace entire API with simple REST wrappers

Would you like me to start the implementation?
