"""
Zeus Refresh Job Correlator
Tools for discovering and analyzing Zeus refresh jobs that upload data to external vendors

These tools correlate NAT gateway traffic spikes with Zeus refresh operations by:
1. Finding jobs active during a time window
2. Analyzing pod logs for upload patterns
3. Identifying client names and destination vendors
"""

import re
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from kubernetes import client, config

logger = logging.getLogger(__name__)

# Default namespaces to search for Zeus jobs
# Zeus jobs run in environment-based namespaces, not "zeus-*" namespaces
DEFAULT_ZEUS_NAMESPACES = [
    "preprod", "qa", "prod",  # Main environments
    "devmatt", "devjeff",     # Dev user environments
    "merlindev1", "merlindev2", "merlindev3", "merlindev4", "merlindev5",  # Merlin dev
    "merlinqa"  # Merlin QA
]

# Label selector for Zeus refresh jobs
ZEUS_ORCHESTRATOR_LABEL = "app.kubernetes.io/instance=zeus-orchestrator"

# Log patterns for upload detection
UPLOAD_PATTERNS = [
    r"uploading file\s+(\S+)",
    r"sending\s+(post|get)\s+request.*to\s+(\S+)",
    r"jobId[\"']?\s*:\s*(\d+)",
    r"runId[\"']?\s*:\s*(\d+)",
    r"lifeCycleState[\"']?\s*:\s*[\"']?(\w+)",
    r"https?://[^\s]+"  # External URLs
]

# Timeout for log retrieval (prevent blocking API)
LOG_RETRIEVAL_TIMEOUT_SECONDS = 5


@dataclass
class ZeusRefreshJob:
    """Represents a Zeus refresh job with metadata"""
    job_name: str
    namespace: str
    pod_name: str
    client_name: Optional[str]
    refresh_type: Optional[str]
    user_email: Optional[str]
    start_time: str
    completion_time: Optional[str]
    status: str  # Running, Succeeded, Failed
    duration_minutes: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LogAnalysis:
    """Analysis results from pod logs"""
    pod_name: str
    namespace: str
    upload_events: List[Dict[str, Any]]
    databricks_jobs: List[Dict[str, Any]]
    external_destinations: List[str]
    estimated_volume_gb: Optional[float]
    log_lines_analyzed: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ZeusJobCorrelator:
    """
    Correlator for Zeus refresh jobs and NAT gateway traffic.

    Discovers Zeus refresh jobs in specified time windows and analyzes
    their logs to identify upload patterns and destinations.
    """

    def __init__(self, namespaces: Optional[List[str]] = None):
        """
        Initialize Zeus job correlator.

        Args:
            namespaces: List of namespaces to search (default: devmatt, devzeus, devjason)
        """
        self.namespaces = namespaces or DEFAULT_ZEUS_NAMESPACES

        # Initialize Kubernetes clients
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except Exception:
            try:
                config.load_kube_config()
                logger.info("Loaded kubeconfig from file")
            except Exception as e:
                logger.error(f"Failed to load Kubernetes config: {e}")
                raise

        self.batch_v1 = client.BatchV1Api()
        self.core_v1 = client.CoreV1Api()

        logger.info(f"Initialized ZeusJobCorrelator for namespaces: {self.namespaces}")

    def find_refresh_jobs(
        self,
        start_time: datetime,
        end_time: datetime,
        namespace: Optional[str] = None
    ) -> List[ZeusRefreshJob]:
        """
        Find Zeus refresh jobs active during a specific time window.

        Args:
            start_time: Start of time window
            end_time: End of time window
            namespace: Specific namespace (default: search all configured namespaces)

        Returns:
            List of ZeusRefreshJob objects for jobs active during the window
        """
        namespaces_to_search = [namespace] if namespace else self.namespaces

        logger.info(f"Searching for Zeus refresh jobs from {start_time} to {end_time}")
        logger.info(f"Namespaces: {namespaces_to_search}")

        all_jobs = []

        for ns in namespaces_to_search:
            try:
                # List jobs with zeus-orchestrator label
                jobs = self.batch_v1.list_namespaced_job(
                    namespace=ns,
                    label_selector=ZEUS_ORCHESTRATOR_LABEL
                )

                logger.info(f"Found {len(jobs.items)} zeus jobs in namespace {ns}")

                for job in jobs.items:
                    job_start_time = job.status.start_time
                    job_completion_time = job.status.completion_time

                    # Skip if job doesn't have start time
                    if not job_start_time:
                        continue

                    # Convert to timezone-aware datetime
                    if job_start_time.tzinfo is None:
                        job_start_time = job_start_time.replace(tzinfo=timezone.utc)
                    if job_completion_time and job_completion_time.tzinfo is None:
                        job_completion_time = job_completion_time.replace(tzinfo=timezone.utc)

                    # Check if job was active during the time window
                    # Job is active if: started before end_time AND (still running OR completed after start_time)
                    job_was_active = (
                        job_start_time <= end_time and
                        (job_completion_time is None or job_completion_time >= start_time)
                    )

                    if not job_was_active:
                        continue

                    # Get pod for this job to extract environment variables
                    pod_name, env_vars = self._get_job_pod_info(job.metadata.name, ns)

                    # Parse client name from REFRESH_S3_LOCATOR (format: uuid:timestamp:client)
                    client_name = None
                    if 'REFRESH_S3_LOCATOR' in env_vars:
                        parts = env_vars['REFRESH_S3_LOCATOR'].split(':')
                        if len(parts) >= 3:
                            client_name = parts[2]

                    # Calculate duration
                    duration_minutes = None
                    if job_completion_time:
                        duration = job_completion_time - job_start_time
                        duration_minutes = duration.total_seconds() / 60

                    # Determine status
                    if job.status.succeeded:
                        status = "Succeeded"
                    elif job.status.failed:
                        status = "Failed"
                    elif job.status.active:
                        status = "Running"
                    else:
                        status = "Unknown"

                    zeus_job = ZeusRefreshJob(
                        job_name=job.metadata.name,
                        namespace=ns,
                        pod_name=pod_name or "unknown",
                        client_name=client_name,
                        refresh_type=env_vars.get('REFRESH_TYPE'),
                        user_email=env_vars.get('EVENT_USER'),
                        start_time=job_start_time.isoformat(),
                        completion_time=job_completion_time.isoformat() if job_completion_time else None,
                        status=status,
                        duration_minutes=duration_minutes
                    )

                    all_jobs.append(zeus_job)

                    logger.info(f"Found active job: {job.metadata.name} (client: {client_name}, status: {status})")

            except client.exceptions.ApiException as e:
                if e.status == 404:
                    logger.warning(f"Namespace {ns} not found, skipping")
                else:
                    logger.error(f"K8s API error in namespace {ns}: {e}")
            except Exception as e:
                logger.error(f"Error searching namespace {ns}: {e}")

        logger.info(f"Total Zeus refresh jobs found: {len(all_jobs)}")
        return all_jobs

    def _get_job_pod_info(self, job_name: str, namespace: str) -> tuple[Optional[str], Dict[str, str]]:
        """
        Get pod name and environment variables for a job.

        Args:
            job_name: Kubernetes job name
            namespace: Namespace

        Returns:
            Tuple of (pod_name, env_vars_dict)
        """
        try:
            # Find pod for this job
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"job-name={job_name}"
            )

            if not pods.items:
                logger.warning(f"No pods found for job {job_name}")
                return None, {}

            pod = pods.items[0]  # Get first pod
            pod_name = pod.metadata.name

            # Extract environment variables from pod spec
            env_vars = {}
            if pod.spec.containers:
                container = pod.spec.containers[0]
                if container.env:
                    for env in container.env:
                        if env.value:  # Skip env vars from configmaps/secrets
                            env_vars[env.name] = env.value

            return pod_name, env_vars

        except Exception as e:
            logger.error(f"Error getting pod info for job {job_name}: {e}")
            return None, {}

    def analyze_job_logs(
        self,
        job_name: str,
        namespace: str,
        tail_lines: int = 1000
    ) -> LogAnalysis:
        """
        Analyze pod logs for a Zeus refresh job to identify upload patterns.

        Args:
            job_name: Kubernetes job name
            namespace: Namespace
            tail_lines: Number of recent log lines to analyze (default: 1000)

        Returns:
            LogAnalysis object with upload events, destinations, and volumes
        """
        logger.info(f"Analyzing logs for job {job_name} in namespace {namespace}")

        # Get pod for this job
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"job-name={job_name}"
            )

            if not pods.items:
                logger.warning(f"No pods found for job {job_name}")
                return LogAnalysis(
                    pod_name="unknown",
                    namespace=namespace,
                    upload_events=[],
                    databricks_jobs=[],
                    external_destinations=[],
                    estimated_volume_gb=None,
                    log_lines_analyzed=0
                )

            pod = pods.items[0]
            pod_name = pod.metadata.name

            # Fetch pod logs with timeout protection
            try:
                logs = self.core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=tail_lines,
                    _request_timeout=LOG_RETRIEVAL_TIMEOUT_SECONDS
                )
            except Exception as e:
                logger.error(f"Error fetching logs for {pod_name}: {e}")
                return LogAnalysis(
                    pod_name=pod_name,
                    namespace=namespace,
                    upload_events=[],
                    databricks_jobs=[],
                    external_destinations=[],
                    estimated_volume_gb=None,
                    log_lines_analyzed=0
                )

            # Parse logs
            log_lines = logs.split('\n')
            upload_events = []
            databricks_jobs = []
            external_urls = set()

            for line in log_lines:
                # Check for upload patterns
                if re.search(r'uploading file', line, re.IGNORECASE):
                    # Try to extract filename
                    match = re.search(r'uploading file\s+(\S+)', line, re.IGNORECASE)
                    if match:
                        upload_events.append({
                            'type': 'file_upload',
                            'filename': match.group(1),
                            'log_line': line.strip()
                        })

                # Check for Databricks job info
                job_id_match = re.search(r'jobId["\']?\s*:\s*(\d+)', line)
                run_id_match = re.search(r'runId["\']?\s*:\s*(\d+)', line)
                state_match = re.search(r'lifeCycleState["\']?\s*:\s*["\']?(\w+)', line)

                if job_id_match or run_id_match:
                    databricks_job = {
                        'job_id': job_id_match.group(1) if job_id_match else None,
                        'run_id': run_id_match.group(1) if run_id_match else None,
                        'state': state_match.group(1) if state_match else None,
                        'log_line': line.strip()
                    }
                    # Avoid duplicates
                    if databricks_job not in databricks_jobs:
                        databricks_jobs.append(databricks_job)

                # Extract external URLs (not k8s internal, not AWS)
                url_matches = re.findall(r'https?://[^\s]+', line)
                for url in url_matches:
                    # Filter out internal/AWS URLs
                    if not any(pattern in url.lower() for pattern in ['kubernetes', 'amazonaws.com', '172.', '10.', 'localhost']):
                        # Check if it's a known vendor
                        if 'databricks.com' in url.lower():
                            external_urls.add(url)
                        elif 'meg' in url.lower() or 'medicalevidencegaps' in url.lower():
                            external_urls.add(url)
                        # Add other external URLs
                        elif url.startswith('http'):
                            external_urls.add(url)

            logger.info(f"Log analysis complete: {len(upload_events)} upload events, "
                       f"{len(databricks_jobs)} Databricks jobs, {len(external_urls)} external destinations")

            return LogAnalysis(
                pod_name=pod_name,
                namespace=namespace,
                upload_events=upload_events,
                databricks_jobs=databricks_jobs,
                external_destinations=list(external_urls),
                estimated_volume_gb=None,  # Could be extracted from logs if available
                log_lines_analyzed=len(log_lines)
            )

        except Exception as e:
            logger.error(f"Error analyzing job logs: {e}")
            return LogAnalysis(
                pod_name="unknown",
                namespace=namespace,
                upload_events=[],
                databricks_jobs=[],
                external_destinations=[],
                estimated_volume_gb=None,
                log_lines_analyzed=0
            )

    def correlate_jobs_with_spike(
        self,
        spike_timestamp: datetime,
        jobs: List[ZeusRefreshJob],
        time_window_minutes: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Correlate jobs with a traffic spike based on timing overlap.

        Args:
            spike_timestamp: Timestamp of the traffic spike
            jobs: List of Zeus refresh jobs to correlate
            time_window_minutes: Correlation window in minutes (default: 30)

        Returns:
            List of jobs with confidence scores and timing analysis
        """
        correlated_jobs = []

        for job in jobs:
            job_start = datetime.fromisoformat(job.start_time.replace('Z', '+00:00'))
            job_end = datetime.fromisoformat(job.completion_time.replace('Z', '+00:00')) if job.completion_time else datetime.now(timezone.utc)

            # Calculate timing relationship
            if job_start <= spike_timestamp <= job_end:
                # Perfect overlap - job was running during spike
                confidence = 1.0
                timing = "job_running_during_spike"
            elif abs((spike_timestamp - job_start).total_seconds() / 60) <= time_window_minutes:
                # Job started near spike time
                confidence = 0.8
                timing = "job_started_near_spike"
            elif job.completion_time and abs((spike_timestamp - job_end).total_seconds() / 60) <= time_window_minutes:
                # Job ended near spike time
                confidence = 0.6
                timing = "job_ended_near_spike"
            else:
                # Job within broader window but not closely correlated
                confidence = 0.4
                timing = "job_in_time_window"

            minutes_before_spike = (spike_timestamp - job_start).total_seconds() / 60
            minutes_after_spike = (job_end - spike_timestamp).total_seconds() / 60 if job.completion_time else None

            correlated_jobs.append({
                'job': job.to_dict(),
                'confidence': confidence,
                'timing_relationship': timing,
                'minutes_before_spike': round(minutes_before_spike, 1),
                'minutes_after_spike': round(minutes_after_spike, 1) if minutes_after_spike else None,
                'overlap': timing in ['job_running_during_spike']
            })

        # Sort by confidence (highest first)
        correlated_jobs.sort(key=lambda x: x['confidence'], reverse=True)

        logger.info(f"Correlated {len(correlated_jobs)} jobs with spike, "
                   f"top confidence: {correlated_jobs[0]['confidence'] if correlated_jobs else 0}")

        return correlated_jobs

    def format_correlation_for_llm(
        self,
        spike_info: Dict[str, Any],
        correlated_jobs: List[Dict[str, Any]],
        log_analyses: Dict[str, LogAnalysis]
    ) -> str:
        """
        Format correlation data as human-readable string for LLM.

        Args:
            spike_info: NAT spike information
            correlated_jobs: List of correlated jobs with confidence scores
            log_analyses: Dictionary mapping job_name to LogAnalysis

        Returns:
            Formatted string for LLM consumption
        """
        output = f"""NAT Gateway Spike Correlation Analysis

Spike Details:
- Timestamp: {spike_info.get('timestamp', 'unknown')}
- Volume: {spike_info.get('bytes_gb', 0):.2f} GB
- Gateway: {spike_info.get('nat_gateway_id', 'unknown')}

"""

        if not correlated_jobs:
            output += "❌ No Zeus refresh jobs found during spike window.\n"
            output += "Traffic may be from other workloads or external sources.\n"
            return output

        output += f"✅ Found {len(correlated_jobs)} Zeus Refresh Jobs:\n\n"

        for idx, corr in enumerate(correlated_jobs, 1):
            job_data = corr['job']
            confidence = corr['confidence']
            timing = corr['timing_relationship']

            output += f"{idx}. Job: {job_data['job_name']}\n"
            output += f"   Client: {job_data['client_name'] or 'Unknown'}\n"
            output += f"   Type: {job_data['refresh_type'] or 'Unknown'}\n"
            output += f"   Status: {job_data['status']}\n"
            output += f"   Started: {job_data['start_time']}\n"
            if job_data['completion_time']:
                output += f"   Completed: {job_data['completion_time']}\n"
                output += f"   Duration: {job_data['duration_minutes']:.1f} minutes\n"
            output += f"   User: {job_data['user_email'] or 'Unknown'}\n"
            output += f"   Confidence: {confidence:.0%} ({timing.replace('_', ' ')})\n"

            # Add log analysis if available
            if job_data['job_name'] in log_analyses:
                log_analysis = log_analyses[job_data['job_name']]
                output += f"\n   Upload Activity:\n"
                output += f"   - Upload events detected: {len(log_analysis.upload_events)}\n"
                output += f"   - Databricks jobs: {len(log_analysis.databricks_jobs)}\n"

                if log_analysis.external_destinations:
                    output += f"   - Destinations:\n"
                    for dest in log_analysis.external_destinations[:3]:  # Limit to 3
                        # Shorten long URLs
                        short_dest = dest if len(dest) < 60 else dest[:57] + "..."
                        output += f"     • {short_dest}\n"

                if log_analysis.databricks_jobs:
                    db_job = log_analysis.databricks_jobs[0]
                    if db_job.get('job_id'):
                        output += f"   - Databricks Job ID: {db_job['job_id']}\n"
                    if db_job.get('run_id'):
                        output += f"   - Databricks Run ID: {db_job['run_id']}\n"

            output += "\n"

        return output


# Global instance (initialized lazily)
_correlator: Optional[ZeusJobCorrelator] = None


def get_correlator() -> ZeusJobCorrelator:
    """Get or create the global Zeus correlator instance"""
    global _correlator
    if _correlator is None:
        _correlator = ZeusJobCorrelator()
    return _correlator
