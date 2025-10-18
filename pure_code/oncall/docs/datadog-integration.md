# Datadog Integration Guide

## Overview

The oncall-agent-api now integrates with Datadog to provide historical Kubernetes metrics analysis for incident troubleshooting. This integration complements real-time Kubernetes API data with time-series metrics for trend analysis, memory leak detection, and performance correlation.

## Architecture

The Datadog integration follows the same pattern as the existing AWS integration:

```
User Query (via Teams/API)
    ↓
OnCallAgentClient (agent_client.py)
    ↓
Custom Tools (custom_tools.py)
    ↓
DatadogIntegrator (datadog_integrator.py)
    ↓
Datadog API (datadog-api-client library)
```

### Key Components

1. **DatadogIntegrator** (`src/tools/datadog_integrator.py`):
   - Core integration class
   - Lazy-loaded Datadog API client
   - Methods: `query_timeseries()`, `query_pod_metrics()`, `query_container_metrics()`, `query_network_metrics()`

2. **Custom Tools** (`src/api/custom_tools.py`):
   - `query_datadog_metrics()` - General metric queries
   - `get_resource_usage_trends()` - CPU/memory trend analysis
   - `check_network_traffic()` - Network traffic patterns

3. **Agent Client** (`src/api/agent_client.py`):
   - Registers all 3 Datadog tools
   - System prompt guides Claude on when to use Datadog
   - Tool execution routing

## Setup

### 1. Obtain Datadog Credentials

Get your API and Application keys from Datadog:
- Visit: https://app.datadoghq.com/organization-settings/api-keys
- Create or copy your **API Key**
- Create or copy your **Application Key**

### 2. Configure Environment Variables

Add to your `.env` file:

```bash
# Datadog Integration
DATADOG_API_KEY=your-datadog-api-key-here
DATADOG_APP_KEY=your-datadog-app-key-here
DATADOG_SITE=datadoghq.com  # or datadoghq.eu for EU region
```

### 3. Verify Installation

```bash
# Test Datadog client is installed
./venv/bin/python -c "from datadog_api_client import Configuration; print('✓ Datadog client available')"

# Test integrator initialization
PYTHONPATH=src ./venv/bin/python -c "from tools.datadog_integrator import DatadogIntegrator; d = DatadogIntegrator(); print(f'✓ Integrator ready, site: {d.site}')"
```

### 4. Run Tests

```bash
# Run unit tests
PYTHONPATH=src ./venv/bin/pytest tests/tools/test_datadog_integrator.py -v

# Expected: 9/9 tests pass with 80% coverage
```

## Available Metrics

The integration supports querying any Datadog metric, with focus on Kubernetes infrastructure metrics:

### CPU Metrics
- `kubernetes.cpu.usage` - CPU usage in cores
- `kubernetes.cpu.limits` - CPU limits configured
- `kubernetes.cpu.requests` - CPU requests configured

### Memory Metrics
- `kubernetes.memory.rss` - Resident Set Size (actual RAM usage)
- `kubernetes.memory.working_set` - Working set memory (includes cache)
- `kubernetes.memory.usage` - Total memory usage
- `kubernetes.memory.limits` - Memory limits configured

### Network Metrics
- `kubernetes.network.tx_bytes` - Network bytes transmitted
- `kubernetes.network.rx_bytes` - Network bytes received
- `kubernetes.network.errors` - Network errors count

### Pod Metrics
- `kubernetes.pods.running` - Number of running pods
- `kubernetes.containers.restarts` - Container restart count

## Usage Examples

### Example 1: Query CPU Usage Over Time

**Via API**:
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What was the CPU usage for proteus-dev over the last 24 hours?"
  }'
```

**Via Teams**:
```
/oncall What was the CPU usage for proteus-dev over the last 24 hours?
```

**What Happens**:
1. Claude recognizes "over the last 24 hours" as historical query
2. Calls `query_datadog_metrics` tool with:
   - metric: `kubernetes.cpu.usage`
   - namespace: `proteus-dev`
   - time_window_hours: `24`
3. Returns timeseries data with peaks, averages, trends

### Example 2: Detect Memory Leaks

**Via Teams**:
```
/oncall Is artemis-auth leaking memory?
```

**What Happens**:
1. Claude calls `get_resource_usage_trends` with:
   - namespace: `artemis-auth-dev`
   - time_window_hours: `168` (1 week)
2. Queries CPU, memory RSS, and working set metrics
3. Analyzes trend for gradual increases
4. Correlates with pod restart patterns
5. Provides specific remediation if leak detected

### Example 3: Correlate Network Traffic with NAT Spikes

**Via Teams**:
```
/oncall What caused the NAT spike at 2am yesterday?
```

**What Happens**:
1. Claude calls `correlate_nat_spike_with_zeus_jobs` (existing tool)
2. Additionally calls `check_network_traffic` for pod-level analysis:
   - namespace: (determined from Zeus jobs)
   - time_window_hours: `2`
3. Combines CloudWatch NAT data + Datadog pod network data
4. Identifies specific pods contributing to spike
5. Provides confidence-scored root cause assessment

### Example 4: Performance Degradation Investigation

**Via Teams**:
```
/oncall Proteus seems slower than usual, what's going on?
```

**What Happens**:
1. Claude checks current pod status with `list_pods`
2. Queries Datadog for last 24h trends with `get_resource_usage_trends`
3. Compares current vs historical performance
4. Checks recent deployments for correlation
5. Provides specific remediation based on trend analysis

## Tool Reference

### query_datadog_metrics

**Purpose**: Query any Datadog metric with flexible filtering

**Parameters**:
- `metric` (required): Metric name (e.g., `kubernetes.cpu.usage`)
- `namespace` (required): Kubernetes namespace
- `pod_name` (optional): Filter to specific pod
- `time_window_hours` (optional): Hours to look back (default: 1, max: 168)
- `aggregation` (optional): `avg`, `max`, `min`, `sum` (default: `avg`)

**Returns**:
```json
{
  "query": "avg:kubernetes.cpu.usage{kube_namespace:proteus-dev}",
  "from_ts": 1697470800,
  "to_ts": 1697474400,
  "series": [
    {
      "metric": "kubernetes.cpu.usage",
      "scope": "kube_namespace:proteus-dev",
      "pointlist": [[timestamp, value], ...],
      "unit": "core"
    }
  ],
  "summary": {
    "metric": "kubernetes.cpu.usage",
    "namespace": "proteus-dev",
    "data_points": 24,
    "series_count": 1
  }
}
```

### get_resource_usage_trends

**Purpose**: Get comprehensive CPU and memory trends for leak detection

**Parameters**:
- `namespace` (required): Kubernetes namespace
- `pod_name` (optional): Filter to specific pod
- `time_window_hours` (optional): Hours to look back (default: 24)

**Returns**:
```json
{
  "kubernetes.cpu.usage": { ... },
  "kubernetes.memory.rss": { ... },
  "kubernetes.memory.working_set": { ... },
  "analysis": {
    "namespace": "artemis-auth-dev",
    "time_window": "Last 24 hour(s)",
    "metrics_retrieved": ["kubernetes.cpu.usage", ...],
    "data_availability": "Metrics available for trend analysis"
  }
}
```

### check_network_traffic

**Purpose**: Analyze network traffic patterns and totals

**Parameters**:
- `namespace` (required): Kubernetes namespace
- `pod_name` (optional): Filter to specific pod
- `time_window_hours` (optional): Hours to look back (default: 1)

**Returns**:
```json
{
  "kubernetes.network.tx_bytes": { ... },
  "kubernetes.network.rx_bytes": { ... },
  "kubernetes.network.errors": { ... },
  "summary": {
    "namespace": "zeus-dev",
    "time_window": "Last 1 hour(s)",
    "totals": {
      "tx_gb": 12.5,
      "rx_gb": 3.2,
      "total_gb": 15.7
    }
  }
}
```

## Troubleshooting

### "datadog-api-client not installed"

**Cause**: Library not in virtual environment

**Fix**:
```bash
pip install -r requirements.txt
# Or directly:
pip install 'datadog-api-client>=2.28.0'
```

### "Datadog client not initialized" or "Check DATADOG_API_KEY"

**Cause**: Missing or invalid credentials

**Fix**:
1. Verify `.env` has `DATADOG_API_KEY` and `DATADOG_APP_KEY`
2. Check credentials are valid in Datadog UI
3. Ensure `.env` is loaded: `python-dotenv` installed

### "No data available for this query"

**Causes**:
1. Datadog agent not collecting from this namespace
2. Metric name incorrect
3. Time window too narrow or too far back

**Fix**:
```bash
# Verify Datadog agent is running in cluster
kubectl get pods -n datadog

# Check if metrics are being collected
# Visit Datadog UI → Metrics Explorer → Search for kubernetes.*

# Try broader time window
# Instead of 1 hour, try 24 hours
```

### High API costs or rate limiting

**Cause**: Too many Datadog API calls

**Mitigation**:
- Limit time windows (max 168 hours / 1 week)
- Use appropriate granularity (don't query minute-by-minute for week-long periods)
- Consider caching results for repeated queries
- Monitor Datadog API usage in organization settings

## Best Practices

### When to Use Datadog vs Kubernetes API

**Use Kubernetes API (list_pods, get_pod_logs) for**:
- ✅ Current state (pod status, restart counts)
- ✅ Real-time diagnostics
- ✅ Events and logs
- ✅ Immediate incident response

**Use Datadog for**:
- ✅ Historical trends (memory over days/weeks)
- ✅ Memory leak detection
- ✅ Performance before/after deployments
- ✅ Gradual degradation patterns
- ✅ Network traffic analysis over time

### Combining Both for Complete Analysis

**Scenario: Pod Restarting Frequently**

1. **K8s API**: Check current status
   ```
   list_pods(namespace="proteus-dev")
   # Shows: 5 restarts in last hour
   ```

2. **Datadog**: Check historical resource usage
   ```
   get_resource_usage_trends(namespace="proteus-dev", time_window_hours=24)
   # Shows: Memory steadily increasing before each restart
   ```

3. **K8s API**: Get error logs
   ```
   get_pod_logs(pod_name="proteus-xyz", namespace="proteus-dev")
   # Shows: OOMKilled errors
   ```

4. **Conclusion**: Memory leak confirmed - memory increases over time, hits limit, OOMKilled, restarts

## Integration with Existing Workflows

### NAT Gateway Analysis

Datadog network metrics complement CloudWatch NAT metrics:

```python
# CloudWatch (existing)
check_nat_gateway_metrics(time_window_hours=2)
# Shows: Total egress at NAT level

# Datadog (new)
check_network_traffic(namespace="zeus-dev", time_window_hours=2)
# Shows: Per-pod network traffic breakdown

# Combined: Identify which specific pods caused NAT spike
```

### Deployment Correlation

Combine GitHub deployments with Datadog metrics:

```python
# 1. Check recent deployments
search_recent_deployments(repo_name="artemishealth/proteus", hours_back=6)

# 2. Get resource usage before/after deployment
get_resource_usage_trends(namespace="proteus-dev", time_window_hours=6)

# 3. Correlate: Did CPU/memory change after deployment?
```

## Datadog Query Syntax Reference

Datadog uses a specific query syntax:

```
{aggregation}:{metric}{tags}[.rollup({rollup_method}[, {rollup_time}])]
```

### Examples:

**Basic query**:
```
avg:kubernetes.cpu.usage{kube_namespace:proteus-dev}
```

**With pod filter**:
```
avg:kubernetes.cpu.usage{kube_namespace:proteus-dev,pod_name:proteus-api-xyz}
```

**Max aggregation**:
```
max:kubernetes.memory.rss{kube_namespace:artemis-auth-dev}
```

**Sum with grouping**:
```
sum:kubernetes.network.tx_bytes{kube_namespace:zeus-dev}by{pod_name}
```

## Monitoring and Costs

### API Rate Limits

Datadog has API rate limits:
- **Metrics API**: 100 requests per minute per organization

### Cost Considerations

- Metrics queries are included in Datadog subscription
- No additional per-query costs (unlike some AWS APIs)
- Monitor usage in: Datadog → Organization Settings → API Keys → Usage

### Recommended Limits

Default configurations:
- Max time window: 168 hours (1 week)
- Default time window: 1 hour for point queries, 24 hours for trends
- Data resolution: Auto-selected by Datadog based on time range

## Next Steps

1. **Obtain Credentials**: Get DATADOG_API_KEY and DATADOG_APP_KEY from your Datadog admin
2. **Configure**: Add to `.env` file
3. **Test Locally**: Run unit tests to verify setup
4. **Import n8n Workflow**: Import updated `dev-eks-oncall-engineer-v2.json`
5. **Test in Teams**: Try example queries with `/oncall` prefix
6. **Monitor**: Watch for Datadog API usage and costs

## Support

For issues or questions:
- Check troubleshooting section above
- Review unit tests: `tests/tools/test_datadog_integrator.py`
- Consult Datadog API docs: https://docs.datadoghq.com/api/latest/metrics/
- Check implementation plan: `docs/datadog-integration-implementation-plan.md`
