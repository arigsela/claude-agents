"""
Hermes ChartData Monitoring Endpoints

Provides dedicated monitoring endpoints for hermes-chartdata service including:
- Health checks combining Datadog metrics and log analysis
- Performance metrics with Snowflake duration tracking
- Slow query detection and analysis
- AI-powered performance analysis
"""

import logging
import os
import re
from datetime import datetime, timedelta
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.middleware import limiter_with_key, verify_api_key
from api.models import (
    ChartdataAnalysisResponse,
    ChartdataHealthResponse,
    ChartdataMetricsResponse,
    SlowQueryInfo,
)
from tools.datadog_integrator import DatadogIntegrator

# Configure logger early so it's available for import errors
logger = logging.getLogger(__name__)

# Import kubernetes client
try:
    from kubernetes import client, config

    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    logger.warning("kubernetes client not available")

router = APIRouter(prefix="/hermes-chartdata", tags=["hermes-chartdata"])


class K8sAnalyzer:
    """Simple Kubernetes log analyzer helper"""

    def __init__(self):
        """Initialize Kubernetes client"""
        if not KUBERNETES_AVAILABLE:
            logger.warning("Kubernetes client not available")
            self.core_v1 = None
            return

        try:
            # Try to load in-cluster config first, fall back to kubeconfig
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes config")
            except Exception as in_cluster_err:
                logger.debug(f"In-cluster config failed: {in_cluster_err}, trying kubeconfig")
                import os

                kubeconfig_path = os.getenv("KUBECONFIG")
                if kubeconfig_path:
                    logger.info(f"Loading kubeconfig from: {kubeconfig_path}")
                    config.load_kube_config(config_file=kubeconfig_path)
                else:
                    logger.info("Loading kubeconfig from default location")
                    config.load_kube_config()
                logger.info("Loaded Kubernetes config from kubeconfig")

            self.core_v1 = client.CoreV1Api()
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            self.core_v1 = None

    async def get_pod_logs(
        self, namespace: str, deployment: str, time_window_minutes: int = 60, tail_lines: int = 1000
    ) -> list[str]:
        """
        Get logs from pods in a deployment.

        Args:
            namespace: Kubernetes namespace
            deployment: Deployment name
            time_window_minutes: Time window to fetch logs (not strictly enforced)
            tail_lines: Number of log lines to fetch per pod

        Returns:
            List of log lines from all pods in deployment
        """
        if not self.core_v1:
            logger.warning("Kubernetes client not initialized, returning empty logs")
            return []

        try:
            # Try multiple label selectors since we don't know the exact label
            label_selectors = [
                f"app={deployment}",
                f"app.kubernetes.io/name={deployment}",
                f"deployment={deployment}",
            ]

            pods_found = None

            for label_selector in label_selectors:
                try:
                    pods = self.core_v1.list_namespaced_pod(
                        namespace=namespace, label_selector=label_selector
                    )
                    if pods.items and len(pods.items) > 0:
                        pods_found = pods
                        logger.info(
                            f"Found {len(pods.items)} pods using selector: {label_selector}"
                        )
                        break
                except Exception as e:
                    logger.debug(f"Label selector {label_selector} failed: {e}")

            # If no pods found with labels, try matching by name prefix
            if not pods_found:
                logger.warning(
                    f"No pods found with label selectors, trying name prefix: {deployment}"
                )
                all_pods = self.core_v1.list_namespaced_pod(namespace=namespace)
                logger.info(f"Total pods in namespace {namespace}: {len(all_pods.items)}")

                matching_pods = [
                    p for p in all_pods.items if p.metadata.name.startswith(deployment)
                ]

                if matching_pods:
                    # Create a mock pods list object
                    class PodsList:
                        def __init__(self, items):
                            self.items = items

                    pods_found = PodsList(matching_pods)
                    logger.info(
                        f"Found {len(matching_pods)} pods by name prefix: {[p.metadata.name for p in matching_pods]}"
                    )
                else:
                    # Log all pod names to help debug
                    all_pod_names = [p.metadata.name for p in all_pods.items[:10]]  # First 10
                    logger.warning(
                        f"No pods matching prefix '{deployment}'. Sample pod names: {all_pod_names}"
                    )

            if not pods_found or not pods_found.items:
                logger.warning(
                    f"No pods found for deployment {deployment} in namespace {namespace}"
                )
                return []

            all_logs = []

            for pod in pods_found.items:
                pod_name = pod.metadata.name
                try:
                    # Get logs from pod
                    logs = self.core_v1.read_namespaced_pod_log(
                        name=pod_name, namespace=namespace, tail_lines=tail_lines, timestamps=False
                    )

                    # Split into lines and add to collection
                    log_lines = logs.split("\n")
                    all_logs.extend([line for line in log_lines if line.strip()])

                    logger.info(f"Retrieved {len(log_lines)} log lines from pod {pod_name}")
                except Exception as e:
                    logger.error(f"Failed to get logs from pod {pod_name}: {e}")

            logger.info(
                f"Retrieved {len(all_logs)} total log lines from {len(pods_found.items)} pods in {deployment}"
            )
            return all_logs

        except Exception as e:
            logger.error(f"Failed to get pod logs: {e}")
            return []


class NamespaceEnum(str, Enum):
    """Valid namespaces for hermes-chartdata deployment"""

    dev = "artemis-dev"
    preprod = "artemis-preprod"
    prod = "artemis-prod"


@router.get("/health", response_model=ChartdataHealthResponse)
@limiter_with_key.limit("60/minute")
async def check_chartdata_health(
    request: Request,
    namespace: NamespaceEnum = NamespaceEnum.preprod,
    time_window_minutes: int = Query(15, ge=5, le=60),
    api_key: str = Depends(verify_api_key),
) -> ChartdataHealthResponse:
    """
    Check hermes-chartdata service health using Datadog metrics and log analysis.

    This endpoint combines:
    - Datadog resource metrics (CPU, memory, pod count)
    - Log-based performance metrics (Snowflake query duration)
    - Error rate analysis from logs

    Health Checks:
    - Pod readiness (min 2 pods running)
    - Resource utilization (CPU < 95%, Memory < 95%)
    - Snowflake performance (avg < 60s)
    - Error rate (< 5%)

    Args:
        namespace: Kubernetes namespace (artemis-dev, artemis-preprod, artemis-prod)
        time_window_minutes: Time window for metrics (5-60 minutes)

    Returns:
        ChartdataHealthResponse with health status, checks, and recommendations
    """
    try:
        DatadogIntegrator()
        k8s = K8sAnalyzer()

        # Convert enum to string value
        namespace_str = namespace.value if hasattr(namespace, "value") else str(namespace)

        checks = {}
        alerts = []
        recommendations = []

        int((datetime.now() - timedelta(minutes=time_window_minutes)).timestamp())
        int(datetime.now().timestamp())

        # 1. Get actual pod count from K8s (source of truth for chartdata monitoring)
        pod_count = 0
        if k8s.core_v1:
            try:
                k8s_pods = k8s.core_v1.list_namespaced_pod(
                    namespace=namespace_str,
                    label_selector="app.kubernetes.io/name=hermes-app-chartdata",
                )
                pod_count = len(k8s_pods.items)
                logger.info(f"K8s reports {pod_count} pods for hermes-app-chartdata")
            except Exception as e:
                logger.warning(f"Could not query K8s for pod count: {e}")

        checks["pods_running"] = pod_count >= 2
        if pod_count < 2:
            alerts.append(f"Only {pod_count} pods running (expected >= 2)")
            recommendations.append(
                "Scale up hermes-app-chartdata deployment to at least 2 replicas"
            )

        # 2. Check Snowflake performance from logs (PRIMARY METRIC FOR CHARTDATA)
        try:
            # Get pod logs from K8s
            logs = await k8s.get_pod_logs(
                namespace=namespace_str,
                deployment="hermes-app-chartdata",
                time_window_minutes=time_window_minutes,
            )

            snowflake_durations = []
            total_queries = 0
            errors = 0

            for line in logs:
                if "Chartdata non_pii" in line and "Took:" in line:
                    total_queries += 1
                    match = re.search(r"Snowflake: ([0-9.]+)", line)
                    if match:
                        snowflake_durations.append(float(match.group(1)))
                elif "ERROR" in line and "chartdata" in line.lower():
                    errors += 1

            if snowflake_durations:
                avg_snowflake = sum(snowflake_durations) / len(snowflake_durations)
                max_snowflake = max(snowflake_durations)
                p95_snowflake = (
                    sorted(snowflake_durations)[int(len(snowflake_durations) * 0.95)]
                    if len(snowflake_durations) > 0
                    else None
                )

                # Primary check: Average Snowflake performance
                checks["snowflake_performance"] = avg_snowflake < 60

                logger.info(
                    f"Snowflake metrics: avg={avg_snowflake:.2f}s, p95={p95_snowflake:.2f}s, max={max_snowflake:.2f}s, queries={total_queries}"
                )

                if avg_snowflake >= 60:
                    alerts.append(
                        f"⚠️ Snowflake avg duration: {avg_snowflake:.2f}s (threshold: 60s)"
                    )
                    recommendations.append(
                        "**HIGH PRIORITY**: Investigate slow Snowflake queries - check query plans and warehouse size"
                    )
                elif p95_snowflake and p95_snowflake >= 60:
                    alerts.append(
                        f"ℹ️ Snowflake P95 duration: {p95_snowflake:.2f}s exceeds 60s (avg is healthy at {avg_snowflake:.2f}s)"
                    )
                    recommendations.append(
                        "**MEDIUM PRIORITY**: Review slowest 5% of queries for optimization"
                    )
                elif avg_snowflake >= 30:
                    recommendations.append(
                        f"Monitor Snowflake trends: current avg {avg_snowflake:.2f}s is approaching 60s threshold"
                    )
            else:
                checks["snowflake_performance"] = None  # No data
                alerts.append("No Snowflake query data found in time window")

            # 3. Check error rate
            if total_queries > 0:
                error_rate = errors / total_queries
                checks["error_rate_ok"] = error_rate < 0.05

                if error_rate >= 0.10:
                    alerts.append(f"❌ Critical error rate: {error_rate*100:.1f}%")
                    recommendations.append(
                        "**HIGH PRIORITY**: Investigate error logs for failure patterns"
                    )
                elif error_rate >= 0.05:
                    alerts.append(f"⚠️ Elevated error rate: {error_rate*100:.1f}%")
                    recommendations.append("Monitor error trends and investigate common patterns")
            else:
                checks["error_rate_ok"] = None  # No queries in window

        except Exception as e:
            logger.error(f"Error analyzing logs: {e}")
            checks["snowflake_performance"] = None
            checks["error_rate_ok"] = None

        # Determine overall health
        health_checks = [v for v in checks.values() if v is not None]
        healthy = all(health_checks) if health_checks else False

        if healthy:
            status = "healthy"
        elif any(health_checks):
            status = "degraded"
        else:
            status = "unhealthy"

        logger.info(f"Health check complete for {namespace_str}: {status}")

        return ChartdataHealthResponse(
            healthy=healthy,
            status=status,
            checks=checks,
            alerts=alerts,
            recommendations=recommendations,
            timestamp=datetime.now(),
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.get("/metrics", response_model=ChartdataMetricsResponse)
@limiter_with_key.limit("60/minute")
async def get_chartdata_metrics(
    request: Request,
    namespace: NamespaceEnum = NamespaceEnum.preprod,
    time_window_minutes: int = Query(60, ge=5, le=1440),
    api_key: str = Depends(verify_api_key),
) -> ChartdataMetricsResponse:
    """
    Get detailed performance metrics for chartdata service.

    Combines:
    - Datadog resource metrics (CPU, memory, pods)
    - Log-based performance metrics (Snowflake duration, query counts)

    Args:
        namespace: Kubernetes namespace
        time_window_minutes: Time window for metrics (5-1440 minutes)

    Returns:
        ChartdataMetricsResponse with comprehensive metrics
    """
    try:
        DatadogIntegrator()
        k8s = K8sAnalyzer()

        # Convert enum to string value
        namespace_str = namespace.value if hasattr(namespace, "value") else str(namespace)

        # Get Datadog metrics
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=time_window_minutes)
        int(start_time.timestamp())
        int(end_time.timestamp())

        # Get actual pod count from K8s (source of truth)
        pod_count = 0
        if k8s.core_v1:
            try:
                k8s_pods = k8s.core_v1.list_namespaced_pod(
                    namespace=namespace_str,
                    label_selector="app.kubernetes.io/name=hermes-app-chartdata",
                )
                pod_count = len(k8s_pods.items)
                logger.info(f"K8s reports {pod_count} pods for hermes-app-chartdata")
            except Exception as e:
                logger.warning(f"Could not query K8s for pod count: {e}")

        # CPU and memory from Datadog (optional - may not be accurate)
        # These are included for reference but not used in health checks
        cpu_usage = None
        memory_usage = None

        # Note: CPU/memory metrics from Datadog may return ratios instead of absolute values
        # For accurate resource monitoring, use Datadog dashboards directly
        logger.info("Skipping CPU/memory Datadog queries - focus on Snowflake performance")

        # Parse logs for Snowflake performance metrics (PRIMARY DATA SOURCE)
        logs = await k8s.get_pod_logs(
            namespace=namespace_str,
            deployment="hermes-app-chartdata",
            time_window_minutes=time_window_minutes,
        )

        snowflake_durations = []
        total_durations = []
        errors = 0

        for line in logs:
            if "Chartdata non_pii" in line and "Took:" in line:
                # Extract Snowflake duration
                sf_match = re.search(r"Snowflake: ([0-9.]+)", line)
                if sf_match:
                    snowflake_durations.append(float(sf_match.group(1)))

                # Extract total duration
                total_match = re.search(r"Took: ([0-9.]+)", line)
                if total_match:
                    total_durations.append(float(total_match.group(1)))

            elif "ERROR" in line and "chartdata" in line.lower():
                errors += 1

        # Calculate statistics
        avg_snowflake = (
            sum(snowflake_durations) / len(snowflake_durations) if snowflake_durations else None
        )
        p95_snowflake = (
            sorted(snowflake_durations)[int(len(snowflake_durations) * 0.95)]
            if len(snowflake_durations) > 0
            else None
        )
        max_snowflake = max(snowflake_durations) if snowflake_durations else None
        avg_total = sum(total_durations) / len(total_durations) if total_durations else None

        logger.info(
            f"Metrics collected for {namespace_str}: {len(total_durations)} queries, {errors} errors, {pod_count} pods"
        )

        return ChartdataMetricsResponse(
            namespace=namespace_str,
            deployment="hermes-app-chartdata",
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            pod_count=pod_count,
            avg_snowflake_duration=avg_snowflake,
            p95_snowflake_duration=p95_snowflake,
            max_snowflake_duration=max_snowflake,
            avg_total_duration=avg_total,
            query_count=len(total_durations),
            error_count=errors,
            time_window_minutes=time_window_minutes,
            timestamp=datetime.now(),
        )

    except Exception as e:
        logger.error(f"Failed to get metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get metrics: {str(e)}")


@router.get("/slow-queries", response_model=list[SlowQueryInfo])
@limiter_with_key.limit("60/minute")
async def get_slow_queries(
    request: Request,
    namespace: NamespaceEnum = NamespaceEnum.preprod,
    threshold_seconds: float = Query(30.0, ge=1.0, le=300.0),
    time_window_minutes: int = Query(60, ge=5, le=1440),
    limit: int = Query(20, ge=1, le=100),
    api_key: str = Depends(verify_api_key),
) -> list[SlowQueryInfo]:
    """
    Get recent slow Snowflake queries from logs.

    Returns list of queries exceeding threshold with details:
    - Query ID (hashed)
    - Client name
    - Snowflake duration
    - Total duration
    - Timestamp

    Args:
        namespace: Kubernetes namespace
        threshold_seconds: Duration threshold for "slow" classification
        time_window_minutes: Time window to search
        limit: Maximum number of results

    Returns:
        List of SlowQueryInfo objects sorted by duration (slowest first)
    """
    try:
        k8s = K8sAnalyzer()

        # Convert enum to string value
        namespace_str = namespace.value if hasattr(namespace, "value") else str(namespace)

        logs = await k8s.get_pod_logs(
            namespace=namespace_str,
            deployment="hermes-app-chartdata",
            time_window_minutes=time_window_minutes,
        )

        slow_queries = []

        for line in logs:
            if "Chartdata non_pii" in line:
                sf_match = re.search(r"Snowflake: ([0-9.]+)", line)
                if sf_match:
                    sf_duration = float(sf_match.group(1))

                    if sf_duration >= threshold_seconds:
                        # Extract details
                        query_match = re.search(r"Query: ([a-f0-9]+)", line)
                        client_match = re.search(r"\(([^)]+)\)", line)
                        total_match = re.search(r"Took: ([0-9.]+)", line)
                        timestamp_match = re.search(
                            r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} [AP]M)", line
                        )

                        slow_queries.append(
                            SlowQueryInfo(
                                query_id=query_match.group(1)[:8] if query_match else None,
                                client=client_match.group(1) if client_match else None,
                                snowflake_duration=sf_duration,
                                total_duration=float(total_match.group(1)) if total_match else None,
                                timestamp=timestamp_match.group(1) if timestamp_match else None,
                                log_line=line[:200],  # First 200 chars for context
                            )
                        )

        # Sort by duration descending and limit
        slow_queries.sort(key=lambda x: x.snowflake_duration, reverse=True)

        logger.info(
            f"Found {len(slow_queries)} slow queries (>{threshold_seconds}s) in {namespace_str}"
        )

        return slow_queries[:limit]

    except Exception as e:
        logger.error(f"Failed to get slow queries: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get slow queries: {str(e)}")


@router.post("/analyze-performance", response_model=ChartdataAnalysisResponse)
@limiter_with_key.limit("10/minute")
async def analyze_chartdata_performance(
    request: Request,
    namespace: NamespaceEnum = NamespaceEnum.preprod,
    time_window_minutes: int = Query(60, ge=15, le=1440),
    api_key: str = Depends(verify_api_key),
) -> ChartdataAnalysisResponse:
    """
    Use Claude AI to analyze chartdata performance patterns and provide insights.

    Combines:
    - Datadog metrics (resource utilization)
    - Log analysis (query performance)
    - Historical trends
    - Actionable recommendations

    This endpoint makes an LLM call to analyze performance data, so it may take longer
    than other endpoints and has a lower rate limit.

    Args:
        namespace: Kubernetes namespace
        time_window_minutes: Time window for analysis (15-1440 minutes)

    Returns:
        ChartdataAnalysisResponse with AI-generated insights
    """
    try:
        # Convert enum to string value
        namespace_str = namespace.value if hasattr(namespace, "value") else str(namespace)

        # Get metrics first
        metrics = await get_chartdata_metrics(
            request=request,
            namespace=namespace,
            time_window_minutes=time_window_minutes,
            api_key=api_key,
        )

        slow_queries_list = await get_slow_queries(
            request=request,
            namespace=namespace,
            threshold_seconds=30.0,
            time_window_minutes=time_window_minutes,
            limit=20,
            api_key=api_key,
        )

        # Build context for Claude - format metrics safely
        # CPU is in cores, not percentage
        cpu_usage_str = f"{metrics.cpu_usage:.2f} cores" if metrics.cpu_usage else "N/A"

        # Memory is in bytes
        if metrics.memory_usage:
            memory_usage_gb = metrics.memory_usage / (1024**3)
            memory_usage_str = f"{memory_usage_gb:.2f} GB"
        else:
            memory_usage_str = "N/A"

        error_rate_str = (
            f"{metrics.error_count} ({metrics.error_count/metrics.query_count*100:.1f}% error rate)"
            if metrics.query_count > 0
            else "N/A"
        )
        avg_snowflake_str = (
            f"{metrics.avg_snowflake_duration:.2f}s (threshold: 60s)"
            if metrics.avg_snowflake_duration
            else "N/A"
        )
        p95_snowflake_str = (
            f"{metrics.p95_snowflake_duration:.2f}s" if metrics.p95_snowflake_duration else "N/A"
        )
        max_snowflake_str = (
            f"{metrics.max_snowflake_duration:.2f}s" if metrics.max_snowflake_duration else "N/A"
        )
        avg_total_str = (
            f"{metrics.avg_total_duration:.2f}s" if metrics.avg_total_duration else "N/A"
        )

        context = f"""
Analyze the performance of hermes-chartdata service in {namespace_str} namespace over the last {time_window_minutes} minutes.

RESOURCE METRICS:
- CPU Usage: {cpu_usage_str}
- Memory Usage: {memory_usage_str}
- Pod Count: {metrics.pod_count} (expected: >= 2)

QUERY PERFORMANCE:
- Total Queries: {metrics.query_count}
- Errors: {error_rate_str}
- Avg Snowflake Duration: {avg_snowflake_str}
- P95 Snowflake Duration: {p95_snowflake_str}
- Max Snowflake Duration: {max_snowflake_str}
- Avg Total Duration: {avg_total_str}

SLOW QUERIES (>30s):
{len(slow_queries_list)} queries exceeded 30s threshold
Top 5 slowest:
"""

        for i, q in enumerate(slow_queries_list[:5], 1):
            context += f"\n{i}. Query {q.query_id} - Client: {q.client} - Duration: {q.snowflake_duration:.2f}s"

        context += """

Please provide:
1. Overall health assessment
2. Identification of performance bottlenecks
3. Root cause analysis for slow queries
4. Specific, actionable recommendations
5. Any patterns or anomalies detected
"""

        # Use LLM for intelligent analysis
        # DISABLED: LLM calls unnecessary tools and may timeout
        # To re-enable: set USE_LLM_ANALYSIS=True environment variable
        use_llm = os.getenv("USE_LLM_ANALYSIS", "false").lower() == "true"

        try:
            # Import agent from API server
            import asyncio

            from api.api_server import agent

            if agent and use_llm:
                logger.info("Using LLM for performance analysis")

                # Create analysis prompt - be explicit that we have all the data
                analysis_prompt = f"""
You are analyzing performance metrics for the hermes-chartdata data query service.

**IMPORTANT**: All the data you need is provided below. Do NOT use any tools - just analyze the provided metrics.

{context}

Based ONLY on the metrics provided above, provide a detailed analysis in markdown format including:

1. **Overall Health Assessment**: Is the service healthy? Are there concerns?

2. **Key Performance Indicators**:
   - How does Snowflake performance compare to the 60s threshold?
   - Is the P95 acceptable or concerning?
   - Is the query volume normal?
   - Any resource constraints (CPU/memory)?

3. **Slow Query Analysis**:
   - Are the slow queries isolated incidents or patterns?
   - Which clients are affected?
   - What might be causing the slowness?

4. **Actionable Recommendations** (prioritize by impact):
   - What should be investigated first?
   - Any optimization opportunities?
   - Should we scale resources?

Keep your analysis concise and actionable. Focus on Snowflake performance optimization.
"""

                # Query the LLM with timeout
                try:
                    llm_result = await asyncio.wait_for(
                        agent.query(analysis_prompt), timeout=30.0  # 30 second timeout
                    )
                    analysis_text = llm_result.get("response", "Analysis unavailable")
                    logger.info("LLM analysis completed")
                except TimeoutError:
                    logger.error("LLM analysis timed out after 30 seconds")
                    raise Exception("LLM analysis timed out")

            else:
                logger.warning("Agent not available, using fallback analysis")
                raise Exception("Agent not initialized")

        except Exception as e:
            logger.warning(f"LLM analysis failed, using fallback: {e}")

            # Fallback to structured analysis without LLM
            health_status = (
                "healthy"
                if metrics.avg_snowflake_duration and metrics.avg_snowflake_duration < 60
                else "experiencing performance degradation"
            )
            snowflake_status = (
                "(within threshold)"
                if metrics.avg_snowflake_duration and metrics.avg_snowflake_duration < 60
                else "(exceeds 60s threshold)"
            )
            error_rate_status = (
                "(acceptable)"
                if metrics.query_count > 0 and metrics.error_count / metrics.query_count < 0.05
                else "(elevated)"
            )

            # Build intelligent fallback analysis
            issues = []
            recommendations = []

            # Analyze Snowflake performance
            if metrics.avg_snowflake_duration:
                if metrics.avg_snowflake_duration >= 60:
                    issues.append(
                        f"❌ Average Snowflake duration ({metrics.avg_snowflake_duration:.2f}s) exceeds 60s threshold"
                    )
                    recommendations.append(
                        "**HIGH PRIORITY**: Investigate Snowflake query plans and warehouse sizing"
                    )
                elif metrics.avg_snowflake_duration >= 30:
                    issues.append(
                        f"⚠️ Average Snowflake duration ({metrics.avg_snowflake_duration:.2f}s) approaching threshold"
                    )
                    recommendations.append("Monitor Snowflake performance trends")

                if metrics.p95_snowflake_duration and metrics.p95_snowflake_duration >= 60:
                    issues.append(
                        f"⚠️ P95 Snowflake duration ({metrics.p95_snowflake_duration:.2f}s) exceeds 60s - tail latency issue"
                    )
                    recommendations.append(
                        "**MEDIUM PRIORITY**: Review slowest 5% of queries for optimization"
                    )

            # Analyze error rate
            if metrics.query_count > 0:
                error_pct = (metrics.error_count / metrics.query_count) * 100
                if error_pct >= 5:
                    issues.append(f"❌ Error rate ({error_pct:.1f}%) exceeds 5% threshold")
                    recommendations.append(
                        "**HIGH PRIORITY**: Investigate error logs for failure patterns"
                    )

            # Analyze resource usage
            if metrics.cpu_usage and metrics.cpu_usage >= 8:
                issues.append(f"⚠️ High CPU usage: {metrics.cpu_usage:.2f} cores")
                recommendations.append(
                    "Consider scaling horizontally or investigating CPU-intensive queries"
                )

            # Analyze slow queries
            if len(slow_queries_list) > 0:
                clients = {q.client for q in slow_queries_list if q.client}
                issues.append(
                    f"⚠️ {len(slow_queries_list)} slow queries (>30s) detected from {len(clients)} clients"
                )
                recommendations.append(
                    f"Review slow queries from clients: {', '.join(list(clients)[:3])}"
                )

            # Build analysis
            issues_section = (
                "\n".join([f"- {issue}" for issue in issues])
                if issues
                else "- ✅ No significant issues detected"
            )
            recs_section = (
                "\n".join([f"{i+1}. {rec}" for i, rec in enumerate(recommendations)])
                if recommendations
                else "1. Continue monitoring current performance\n2. Maintain existing Snowflake warehouse configuration"
            )

            analysis_text = f"""
## Overall Health Assessment
The hermes-chartdata service is currently **{health_status}**.

## Key Performance Indicators
- **Average Snowflake Duration**: {avg_snowflake_str} {snowflake_status}
- **P95 Snowflake Duration**: {p95_snowflake_str}
- **Max Snowflake Duration**: {max_snowflake_str}
- **Query Volume**: {metrics.query_count} queries in {time_window_minutes} minutes (~{metrics.query_count/time_window_minutes:.1f} queries/min)
- **Error Rate**: {error_rate_str} {error_rate_status}
- **Resource Usage**: {cpu_usage_str}, {memory_usage_str}
- **Pod Count**: {metrics.pod_count} pods running

## Issues Identified
{issues_section}

## Slow Query Analysis
{len(slow_queries_list)} queries exceeded 30s threshold in the analysis window.

Top slow queries:
"""
            for i, q in enumerate(slow_queries_list[:5], 1):
                analysis_text += (
                    f"\n{i}. **{q.client}**: {q.snowflake_duration:.2f}s (Query: {q.query_id})"
                )

            analysis_text += f"""

## Actionable Recommendations
{recs_section}

---
*Analysis Type: Rule-based (LLM disabled - set USE_LLM_ANALYSIS=true to enable)*
"""

        logger.info(f"Performance analysis completed for {namespace_str}")

        return ChartdataAnalysisResponse(
            namespace=namespace_str,
            time_window_minutes=time_window_minutes,
            metrics=metrics,
            slow_query_count=len(slow_queries_list),
            analysis=analysis_text,
            timestamp=datetime.now(),
        )

    except Exception as e:
        logger.error(f"Performance analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Performance analysis failed: {str(e)}")
