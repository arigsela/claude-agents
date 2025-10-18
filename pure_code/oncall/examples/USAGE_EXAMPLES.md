# Usage Examples
## On-Call Troubleshooting Agent

---

## Running the Agent

### Interactive Mode (Default)

```bash
cd /Users/ari.sela/git/olympus/oncall-agent-poc
source venv/bin/activate
python src/agent/oncall_agent.py
```

**Interactive Commands:**
```
oncall-agent> help              # Show available commands
oncall-agent> status            # Show agent status
oncall-agent> config            # Display configuration
oncall-agent> test payment-api  # Test with sample incident
oncall-agent> query What K8s events happened in the last hour?
oncall-agent> quit              # Exit agent
```

### Query Mode

Send a single query and exit:

```bash
python src/agent/oncall_agent.py --query "Check dev-eks for any pod restarts in the last 24 hours"
```

### Incident Handling Mode

Process an incident from a JSON file:

```bash
python src/agent/oncall_agent.py --incident examples/sample_incident.json
```

### Development Mode

Run with verbose logging:

```bash
python src/agent/oncall_agent.py --dev
```

---

## Example Incidents

### 1. OOMKilled Pod

**Incident File:** `examples/oom_incident.json`
```json
{
  "service": "payment-api",
  "namespace": "artemis-services",
  "error": "OOMKilled",
  "pod": "payment-api-abc123-xyz",
  "restart_count": 12,
  "timestamp": "2025-09-30T14:00:00Z",
  "cluster": "dev-eks"
}
```

**Expected Agent Actions:**
1. Check memory limits in deployment spec
2. Review recent code changes for memory leaks
3. Analyze memory usage trends
4. Suggest increasing memory limits or rollback

### 2. CrashLoopBackOff

**Incident File:** `examples/crashloop_incident.json`
```json
{
  "service": "user-service",
  "namespace": "artemis-apps",
  "error": "CrashLoopBackOff",
  "pod": "user-service-def456-abc",
  "restart_count": 8,
  "timestamp": "2025-09-30T15:30:00Z",
  "cluster": "dev-eks",
  "additional_context": {
    "last_deployment": "2025-09-30T15:00:00Z"
  }
}
```

**Expected Agent Actions:**
1. Correlate with recent deployment (30 min ago)
2. Check pod logs for startup errors
3. Verify environment variables and configs
4. Suggest rollback to previous version

### 3. ImagePullBackOff

**Incident File:** `examples/imagepull_incident.json`
```json
{
  "service": "notification-service",
  "namespace": "artemis-services",
  "error": "ImagePullBackOff",
  "pod": "notification-service-ghi789-def",
  "restart_count": 0,
  "timestamp": "2025-09-30T16:00:00Z",
  "cluster": "dev-eks"
}
```

**Expected Agent Actions:**
1. Verify image exists in ECR
2. Check image pull secrets
3. Verify registry connectivity
4. Review image tag specification

---

## Interactive Session Example

```
$ python src/agent/oncall_agent.py

============================================================
On-Call Troubleshooting Agent - Interactive Mode
============================================================

Type 'help' for available commands, 'quit' to exit

oncall-agent> status
Agent Status: Active
Config Path: /Users/ari.sela/git/olympus/oncall-agent-poc/config
MCP Servers: 4

oncall-agent> test payment-api

🚨 Handling Incident: payment-api

🔍 Analyzing incident...
   Service: payment-api
   Namespace: artemis-services
   Error: CrashLoopBackOff
   Restart Count: 5

📊 Recent Events:
   - [2025-09-30 12:25:00] Pod payment-api-test-pod restarted (count: 5)
   - [2025-09-30 12:20:00] Previous restart (count: 4)

🔗 Deployment Correlation:
   - Recent deployment found: deploy-workflow-123
   - Deployed: 2025-09-30 12:15:00
   - Confidence: 0.95 (HIGH)

💾 Similar Past Incidents:
   - incident_20250915_567 (same service, OOMKilled)
   - Resolution: Increased memory limit to 1Gi

✅ Recommended Actions:
   1. Check pod logs: kubectl logs payment-api-test-pod -n artemis-services
   2. Review deployment: kubectl describe deployment payment-api -n artemis-services
   3. Consider rollback to previous version
   4. Monitor memory usage trends

oncall-agent> quit

Shutting down agent...
```

---

## Query Examples

### Check Recent Events
```bash
python src/agent/oncall_agent.py --query "What K8s events occurred in dev-eks in the last hour?"
```

### Deployment Analysis
```bash
python src/agent/oncall_agent.py --query "Show me all GitHub deployments to artemishealth in the last 24 hours"
```

### Memory Search
```bash
python src/agent/oncall_agent.py --query "Search zeus memory for past OOMKilled incidents"
```

### Service Health Check
```bash
python src/agent/oncall_agent.py --query "Check the health of payment-api in artemis-services namespace"
```

---

## Programmatic Usage

### Python API

```python
import asyncio
from agent.oncall_agent import OnCallTroubleshootingAgent

async def main():
    # Initialize agent
    agent = OnCallTroubleshootingAgent()

    # Handle an incident
    alert = {
        "service": "payment-api",
        "namespace": "artemis-services",
        "error": "CrashLoopBackOff",
        "pod": "payment-api-abc123",
        "restart_count": 5
    }

    result = await agent.handle_incident(alert)
    print(f"Analysis: {result['agent_response']}")

    # Send custom query
    responses = await agent.query("What's the status of dev-eks cluster?")
    for response in responses:
        print(response)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Environment Setup

Before running, ensure `.env` file exists with:

```bash
ANTHROPIC_API_KEY=your-api-key
GITHUB_TOKEN=your-github-token
KUBECONFIG=/Users/yourusername/.kube/config
K8S_CONTEXT=dev-eks
```

---

## Troubleshooting

### Import Error: tools.k8s_analyzer
```bash
# Ensure you're in the project root
cd /Users/ari.sela/git/olympus/oncall-agent-poc

# Add project to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"

# Or run with module syntax
python -m agent.oncall_agent
```

### MCP Server Connection Failed
```bash
# Verify MCP server paths in config/mcp_servers.json
cat config/mcp_servers.json

# Test Kubernetes MCP server
node /Users/ari.sela/git/olympus/mcp/mcp-server-kubernetes/build/index.js
```

### Environment Variables Not Loading
```bash
# Verify .env file exists
ls -la .env

# Check if dotenv is installed
pip show python-dotenv

# Manually export for testing
export ANTHROPIC_API_KEY=your-key
```

---

**Last Updated:** 2025-09-30
**Phase:** 2.1 Complete