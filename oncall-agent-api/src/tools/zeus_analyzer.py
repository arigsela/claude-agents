"""
Zeus Refresh Job Analyzer
Comprehensive analysis of Zeus refresh jobs using Kubernetes API, Datadog logs, and metrics

This analyzer combines:
1. Kubernetes API - Find Zeus jobs by label selector
2. Datadog Logs API - Get orchestrator and web logs
3. Datadog Metrics API - Get CPU, memory, network metrics
4. Log parsing - Extract refresh details, client names, errors
"""

import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from kubernetes import client, config

from .datadog_integrator import get_datadog_integrator

logger = logging.getLogger(__name__)

# Default namespaces to search for Zeus jobs - configurable via environment variable
# For dev-eks: dev namespaces (qa, preprod, devmatt, etc.)
# For prod-eks: Set ZEUS_NAMESPACES environment variable (comma-separated)
_DEFAULT_DEV_NAMESPACES = [
    "qa",
    "preprod",  # Main environments
    "devmatt",
    "devjeff",
    "devbryan",
    "devgreg",
    "devawilson",
    "devbrenda",  # Dev user environments
    "merlindev1",
    "merlindev2",
    "merlindev3",
    "merlindev4",
    "merlindev5",  # Merlin dev
    "merlinqa",
    "merlinpreprod",  # Merlin QA/preprod
]

# Production namespaces (used when K8S_CONTEXT is prod-eks)
_DEFAULT_PROD_NAMESPACES = [
    "prod",  # Main Zeus production namespace
]

def _get_default_zeus_namespaces() -> list[str]:
    """Get default Zeus namespaces based on environment configuration."""
    # First check for explicit ZEUS_NAMESPACES env var
    env_namespaces = os.getenv("ZEUS_NAMESPACES")
    if env_namespaces:
        return [ns.strip() for ns in env_namespaces.split(",") if ns.strip()]

    # Fall back to cluster-based defaults
    cluster = os.getenv("K8S_CONTEXT", "default")
    if cluster == "prod-eks":
        return _DEFAULT_PROD_NAMESPACES
    return _DEFAULT_DEV_NAMESPACES

DEFAULT_ZEUS_NAMESPACES = _get_default_zeus_namespaces()

# Label selector for Zeus refresh jobs
ZEUS_ORCHESTRATOR_LABEL = "app.kubernetes.io/instance=zeus-orchestrator"

# Log patterns for extracting refresh information
LOG_PATTERNS = {
    "client_name": r'(?:client|customer)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_-]+)',
    "refresh_type": r'(?:refresh_?type|type)["\']?\s*[:=]\s*["\']?(\w+)',
    "databricks_job_id": r'(?:jobId|job_id)["\']?\s*[:=]\s*["\']?(\d+)',
    "databricks_run_id": r'(?:runId|run_id)["\']?\s*[:=]\s*["\']?(\d+)',
    "lifecycle_state": r'(?:lifeCycleState|lifecycle_state)["\']?\s*[:=]\s*["\']?(\w+)',
    "error": r"(?:ERROR|Exception|Failed|Error):\s*(.+)",
    "upload_file": r"uploading\s+file\s+(\S+)",
    "external_url": r"https?://[^\s]+",
}


@dataclass
class ZeusRefreshJob:
    """Represents a Zeus refresh job with comprehensive metadata"""

    job_name: str
    namespace: str
    pod_name: str
    client_name: str | None
    refresh_type: str | None
    user_email: str | None
    start_time: str
    completion_time: str | None
    status: str  # Running, Succeeded, Failed
    duration_minutes: float | None

    # Datadog log analysis
    log_count: int = 0
    errors: list[str] = None
    databricks_jobs: list[dict[str, Any]] = None
    upload_files: list[str] = None

    # Metrics summary
    avg_cpu_cores: float | None = None
    max_cpu_cores: float | None = None
    avg_memory_mb: float | None = None
    max_memory_mb: float | None = None
    total_network_tx_mb: float | None = None
    total_network_rx_mb: float | None = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.databricks_jobs is None:
            self.databricks_jobs = []
        if self.upload_files is None:
            self.upload_files = []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ZeusAnalyzer:
    """
    Comprehensive Zeus refresh job analyzer.

    Combines Kubernetes job discovery with Datadog logs and metrics
    to provide complete visibility into Zeus refresh operations.
    """

    def __init__(self, namespaces: list[str] | None = None, cluster_name: str | None = None):
        """
        Initialize Zeus analyzer.

        Args:
            namespaces: List of namespaces to search (default: from ZEUS_NAMESPACES or cluster-based)
            cluster_name: Kubernetes cluster name for Datadog queries (default: from K8S_CONTEXT env var)
        """
        self.namespaces = namespaces or DEFAULT_ZEUS_NAMESPACES
        self.cluster_name = cluster_name or os.getenv("K8S_CONTEXT", "default")

        # Initialize Kubernetes clients
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except Exception:
            try:
                config.load_kube_config()
                logger.info("Loaded kubeconfig from ~/.kube/config")
            except Exception as e:
                logger.warning(f"Could not load Kubernetes config: {e}")

        self.batch_v1 = client.BatchV1Api()
        self.core_v1 = client.CoreV1Api()

        # Initialize Datadog integrator
        self.datadog = get_datadog_integrator()

    def find_zeus_jobs(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        client_name: str | None = None,
        status: str | None = None,
    ) -> list[ZeusRefreshJob]:
        """
        Find Zeus refresh jobs in specified time window.

        Args:
            start_time: Start of time window (default: 1 hour ago)
            end_time: End of time window (default: now)
            client_name: Filter by client name (optional)
            status: Filter by status - Running, Succeeded, Failed (optional)

        Returns:
            List of ZeusRefreshJob objects with metadata
        """
        if start_time is None:
            start_time = datetime.now(UTC) - timedelta(hours=1)
        if end_time is None:
            end_time = datetime.now(UTC)

        logger.info(
            f"Finding Zeus jobs from {start_time} to {end_time} in namespaces: {self.namespaces}"
        )

        jobs = []

        for namespace in self.namespaces:
            try:
                # Query Kubernetes Jobs API with label selector
                job_list = self.batch_v1.list_namespaced_job(
                    namespace=namespace, label_selector=ZEUS_ORCHESTRATOR_LABEL
                )

                for job in job_list.items:
                    job_start = job.status.start_time
                    if job_start is None:
                        continue

                    # Filter by time window
                    if job_start < start_time or job_start > end_time:
                        continue

                    # Determine job status
                    job_status = "Running"
                    completion_time = None
                    duration = None

                    if job.status.succeeded:
                        job_status = "Succeeded"
                        completion_time = job.status.completion_time
                    elif job.status.failed:
                        job_status = "Failed"
                        completion_time = job.status.completion_time

                    if completion_time:
                        duration = (completion_time - job_start).total_seconds() / 60

                    # Filter by status if specified
                    if status and job_status != status:
                        continue

                    # Get pod name
                    pod_name = None
                    if job.status.active:
                        # Job is running - find active pod
                        pods = self.core_v1.list_namespaced_pod(
                            namespace=namespace, label_selector=f"job-name={job.metadata.name}"
                        )
                        if pods.items:
                            pod_name = pods.items[0].metadata.name
                    else:
                        # Job completed - get from labels
                        pod_name = f"{job.metadata.name}-"  # Prefix for log queries

                    # Extract client name and user from job labels/annotations
                    labels = job.metadata.labels or {}
                    annotations = job.metadata.annotations or {}

                    extracted_client = labels.get("client") or annotations.get("client")
                    user_email = annotations.get("user") or annotations.get("email")

                    # Filter by client if specified
                    if client_name and extracted_client != client_name:
                        continue

                    zeus_job = ZeusRefreshJob(
                        job_name=job.metadata.name,
                        namespace=namespace,
                        pod_name=pod_name or job.metadata.name,
                        client_name=extracted_client,
                        refresh_type=labels.get("refresh_type"),
                        user_email=user_email,
                        start_time=job_start.isoformat(),
                        completion_time=completion_time.isoformat() if completion_time else None,
                        status=job_status,
                        duration_minutes=duration,
                    )

                    jobs.append(zeus_job)

            except Exception as e:
                logger.warning(f"Error querying namespace {namespace}: {e}")
                continue

        logger.info(f"✓ Found {len(jobs)} Zeus jobs")
        return jobs

    def enrich_with_logs(self, jobs: list[ZeusRefreshJob]) -> list[ZeusRefreshJob]:
        """
        Enrich Zeus jobs with Datadog log analysis.

        Queries Datadog logs for each job and extracts:
        - Client names
        - Refresh types
        - Databricks job/run IDs
        - Errors and exceptions
        - Upload file names

        Args:
            jobs: List of ZeusRefreshJob objects

        Returns:
            Same list with log data populated
        """
        logger.info(f"Enriching {len(jobs)} jobs with Datadog logs")

        for job in jobs:
            try:
                # Build Datadog log query
                query = f"service:zeus-orchestrator kube_namespace:{job.namespace} @pod_name:{job.pod_name}*"

                # Parse timestamps
                start_dt = datetime.fromisoformat(job.start_time.replace("Z", "+00:00"))
                if job.completion_time:
                    end_dt = datetime.fromisoformat(job.completion_time.replace("Z", "+00:00"))
                else:
                    end_dt = datetime.now(UTC)

                # Query Datadog logs
                log_result = self.datadog.query_logs(
                    query=query, start=start_dt, end=end_dt, limit=1000
                )

                if "error" in log_result:
                    logger.warning(f"Error querying logs for {job.job_name}: {log_result['error']}")
                    continue

                logs = log_result.get("logs", [])
                job.log_count = len(logs)

                # Parse logs for patterns
                for log_entry in logs:
                    message = log_entry.get("message", "")

                    # Extract client name
                    if not job.client_name:
                        match = re.search(LOG_PATTERNS["client_name"], message, re.IGNORECASE)
                        if match:
                            job.client_name = match.group(1)

                    # Extract refresh type
                    if not job.refresh_type:
                        match = re.search(LOG_PATTERNS["refresh_type"], message, re.IGNORECASE)
                        if match:
                            job.refresh_type = match.group(1)

                    # Extract Databricks job info
                    job_id_match = re.search(LOG_PATTERNS["databricks_job_id"], message)
                    run_id_match = re.search(LOG_PATTERNS["databricks_run_id"], message)
                    state_match = re.search(LOG_PATTERNS["lifecycle_state"], message)

                    if job_id_match or run_id_match:
                        databricks_job = {
                            "job_id": job_id_match.group(1) if job_id_match else None,
                            "run_id": run_id_match.group(1) if run_id_match else None,
                            "state": state_match.group(1) if state_match else None,
                        }
                        if databricks_job not in job.databricks_jobs:
                            job.databricks_jobs.append(databricks_job)

                    # Extract errors
                    error_match = re.search(LOG_PATTERNS["error"], message)
                    if error_match:
                        error_msg = error_match.group(1).strip()
                        if error_msg not in job.errors:
                            job.errors.append(error_msg)

                    # Extract upload files
                    upload_match = re.search(LOG_PATTERNS["upload_file"], message)
                    if upload_match:
                        file_name = upload_match.group(1)
                        if file_name not in job.upload_files:
                            job.upload_files.append(file_name)

                logger.info(f"✓ Enriched {job.job_name} with {job.log_count} log entries")

            except Exception as e:
                logger.error(f"Error enriching job {job.job_name} with logs: {e}")
                continue

        return jobs

    async def enrich_with_metrics(self, jobs: list[ZeusRefreshJob]) -> list[ZeusRefreshJob]:
        """
        Enrich Zeus jobs with Datadog metrics.

        Queries Datadog metrics for each job and calculates:
        - Average and max CPU usage (cores)
        - Average and max memory usage (MB)
        - Total network traffic (TX/RX in MB)

        Args:
            jobs: List of ZeusRefreshJob objects

        Returns:
            Same list with metrics data populated
        """
        logger.info(f"Enriching {len(jobs)} jobs with Datadog metrics")

        for job in jobs:
            try:
                # Parse timestamps
                start_dt = datetime.fromisoformat(job.start_time.replace("Z", "+00:00"))
                if job.completion_time:
                    end_dt = datetime.fromisoformat(job.completion_time.replace("Z", "+00:00"))
                else:
                    end_dt = datetime.now(UTC)

                # Calculate hours for query
                duration_hours = max(1, int((end_dt - start_dt).total_seconds() / 3600) + 1)

                # Query CPU metrics
                cpu_result = await self.datadog.query_pod_metrics(
                    metric="kubernetes.cpu.usage.total",
                    namespace=job.namespace,
                    pod_name=job.pod_name,
                    hours_back=duration_hours,
                    aggregation="avg",
                )

                if cpu_result and "series" in cpu_result and cpu_result["series"]:
                    pointlist = cpu_result["series"][0].get("pointlist", [])
                    if pointlist:
                        # Ensure numeric conversion (values may be strings after JSON serialization)
                        cpu_values = []
                        for point in pointlist:
                            if point[1] is not None:
                                try:
                                    cpu_values.append(float(point[1]))
                                except (ValueError, TypeError):
                                    continue
                        if cpu_values:
                            job.avg_cpu_cores = sum(cpu_values) / len(cpu_values)
                            job.max_cpu_cores = max(cpu_values)

                # Query memory metrics
                memory_result = await self.datadog.query_pod_metrics(
                    metric="kubernetes.memory.rss",
                    namespace=job.namespace,
                    pod_name=job.pod_name,
                    hours_back=duration_hours,
                    aggregation="avg",
                )

                if memory_result and "series" in memory_result and memory_result["series"]:
                    pointlist = memory_result["series"][0].get("pointlist", [])
                    if pointlist:
                        # Ensure numeric conversion (values may be strings after JSON serialization)
                        memory_values = []
                        for point in pointlist:
                            if point[1] is not None:
                                try:
                                    memory_values.append(
                                        float(point[1]) / (1024 * 1024)
                                    )  # Convert to MB
                                except (ValueError, TypeError):
                                    continue
                        if memory_values:
                            job.avg_memory_mb = sum(memory_values) / len(memory_values)
                            job.max_memory_mb = max(memory_values)

                # Query network metrics
                network_result = await self.datadog.query_network_metrics(
                    namespace=job.namespace, pod_name=job.pod_name, hours_back=duration_hours
                )

                if network_result:
                    # TX bytes
                    tx_data = network_result.get("kubernetes.network.tx_bytes", {})
                    if tx_data and "series" in tx_data and tx_data["series"]:
                        tx_pointlist = tx_data["series"][0].get("pointlist", [])
                        if tx_pointlist:
                            # Ensure numeric conversion (values may be strings after JSON serialization)
                            tx_values = []
                            for point in tx_pointlist:
                                if point[1] is not None:
                                    try:
                                        tx_values.append(float(point[1]))
                                    except (ValueError, TypeError):
                                        continue
                            if tx_values:
                                job.total_network_tx_mb = sum(tx_values) / (
                                    1024 * 1024
                                )  # Convert to MB

                    # RX bytes
                    rx_data = network_result.get("kubernetes.network.rx_bytes", {})
                    if rx_data and "series" in rx_data and rx_data["series"]:
                        rx_pointlist = rx_data["series"][0].get("pointlist", [])
                        if rx_pointlist:
                            # Ensure numeric conversion (values may be strings after JSON serialization)
                            rx_values = []
                            for point in rx_pointlist:
                                if point[1] is not None:
                                    try:
                                        rx_values.append(float(point[1]))
                                    except (ValueError, TypeError):
                                        continue
                            if rx_values:
                                job.total_network_rx_mb = sum(rx_values) / (
                                    1024 * 1024
                                )  # Convert to MB

                logger.info(
                    f"✓ Enriched {job.job_name} with metrics (CPU: {job.avg_cpu_cores:.2f} cores, Mem: {job.avg_memory_mb:.0f} MB, Net TX: {job.total_network_tx_mb:.0f} MB)"
                )

            except Exception as e:
                logger.error(f"Error enriching job {job.job_name} with metrics: {e}")
                continue

        return jobs

    async def analyze_zeus_refreshes(
        self,
        hours_back: int = 1,
        client_name: str | None = None,
        status: str | None = None,
        include_logs: bool = True,
        include_metrics: bool = True,
    ) -> dict[str, Any]:
        """
        Comprehensive analysis of Zeus refresh jobs.

        This is the main entry point that combines all analysis:
        1. Find Zeus jobs via Kubernetes API
        2. Enrich with Datadog logs
        3. Enrich with Datadog metrics

        Args:
            hours_back: Hours to look back (default: 1)
            client_name: Filter by client name (optional)
            status: Filter by status - Running, Succeeded, Failed (optional)
            include_logs: Whether to enrich with log analysis (default: True)
            include_metrics: Whether to enrich with metrics (default: True)

        Returns:
            Dictionary with analysis results:
            {
                "summary": {
                    "total_jobs": 5,
                    "running": 1,
                    "succeeded": 3,
                    "failed": 1,
                    "time_range": "2024-01-15T09:00:00Z to 2024-01-15T10:00:00Z"
                },
                "jobs": [
                    {
                        "job_name": "zeus-refresh-abc-12345",
                        "namespace": "qa",
                        "client_name": "ABC Corp",
                        "status": "Succeeded",
                        "duration_minutes": 15.5,
                        "avg_cpu_cores": 2.3,
                        "max_memory_mb": 4096,
                        "errors": [],
                        ...
                    },
                    ...
                ]
            }
        """
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours_back)

        logger.info(f"Starting comprehensive Zeus analysis for last {hours_back} hours")

        # Step 1: Find jobs via Kubernetes
        jobs = self.find_zeus_jobs(
            start_time=start_time, end_time=end_time, client_name=client_name, status=status
        )

        # Step 2: Enrich with logs
        if include_logs and jobs:
            jobs = self.enrich_with_logs(jobs)

        # Step 3: Enrich with metrics
        if include_metrics and jobs:
            jobs = await self.enrich_with_metrics(jobs)

        # Build summary
        summary = {
            "total_jobs": len(jobs),
            "running": sum(1 for j in jobs if j.status == "Running"),
            "succeeded": sum(1 for j in jobs if j.status == "Succeeded"),
            "failed": sum(1 for j in jobs if j.status == "Failed"),
            "time_range": f"{start_time.isoformat()} to {end_time.isoformat()}",
            "namespaces_searched": self.namespaces,
            "cluster": self.cluster_name,
        }

        result = {"summary": summary, "jobs": [job.to_dict() for job in jobs]}

        logger.info(f"✓ Analysis complete: {summary['total_jobs']} jobs found")
        return result


# Global singleton instance
_zeus_analyzer = None


def get_zeus_analyzer() -> ZeusAnalyzer:
    """Get or create the global ZeusAnalyzer instance."""
    global _zeus_analyzer
    if _zeus_analyzer is None:
        _zeus_analyzer = ZeusAnalyzer()
    return _zeus_analyzer
