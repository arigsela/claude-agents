"""
Kubernetes Event Watcher
Monitors K8s events and triggers agent analysis
"""

import asyncio
import logging
from typing import Any, Dict, List, Callable, Optional
from datetime import datetime, timedelta
import yaml
from pathlib import Path
import os

# Kubernetes API client
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


class KubernetesEventWatcher:
    """
    Watches Kubernetes events and triggers the on-call agent for analysis.

    This watcher:
    - Monitors specified namespaces for Warning events
    - Filters events based on config/k8s_monitoring.yaml rules
    - Triggers agent when alert thresholds are met
    - Maintains event state to avoid duplicate processing
    """

    def __init__(self, config_path: Optional[Path] = None, agent_callback: Optional[Callable[[Dict], Any]] = None, agent_client=None):
        """
        Initialize the K8s event watcher.

        Args:
            config_path: Path to configuration directory
            agent_callback: Async function to call when incident detected (takes Dict, returns Any)
            agent_client: Not used (kept for backwards compatibility)
        """
        self.config_path = config_path or Path(__file__).parent.parent.parent / "config"
        self.agent_callback = agent_callback
        self.monitoring_config = self._load_monitoring_config()
        self.processed_events = set()  # Track processed event UIDs
        self.processed_pod_alerts = {}  # Track pod health alerts: {pod_key: last_alert_time}
        self.active_incidents = {}  # Group related incidents: {service_namespace_key: incident_data}
        self.is_running = False

        # Initialize Kubernetes client
        self.k8s_client = None
        self._initialize_k8s_client()

        logger.info(f"KubernetesEventWatcher initialized (using direct K8s API)")

    def _initialize_k8s_client(self):
        """Initialize Kubernetes API client"""
        try:
            # Try in-cluster config first (for container deployment)
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes configuration")
            except config.ConfigException:
                # Fall back to kubeconfig file (for local development)
                config.load_kube_config()
                logger.info("Loaded Kubernetes configuration from kubeconfig")

            # Create CoreV1Api client
            self.k8s_client = client.CoreV1Api()
            logger.info("Kubernetes API client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            logger.warning("Event watcher will run in guidance mode only")

    def _load_monitoring_config(self) -> Dict:
        """Load K8s monitoring configuration"""
        config_file = self.config_path / "k8s_monitoring.yaml"
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.error(f"Monitoring config not found at {config_file}")
            return {}

    async def start(self):
        """
        Start watching Kubernetes events.

        This method runs in a loop, periodically checking for events
        and triggering the agent when issues are detected.

        Note: All clusters share the same poll interval from the first cluster's config.
        """
        logger.info("Starting K8s event watcher...")
        self.is_running = True

        monitoring = self.monitoring_config.get('monitoring', {})
        clusters = monitoring.get('clusters', [])

        if not clusters:
            logger.error("No clusters configured for monitoring")
            return

        # Get polling interval from first cluster's config (shared across all clusters)
        poll_interval = clusters[0].get('poll_interval_seconds', 30)
        logger.info(f"Poll interval: {poll_interval} seconds (shared across all clusters)")

        while self.is_running:
            try:
                for cluster_config in clusters:
                    await self._check_cluster_events(cluster_config)

                # Wait before next poll (same interval for all clusters)
                await asyncio.sleep(poll_interval)

            except KeyboardInterrupt:
                logger.info("Event watcher interrupted")
                self.stop()
                break
            except Exception as e:
                logger.error(f"Error in event watcher loop: {e}")
                await asyncio.sleep(poll_interval)

    def stop(self):
        """Stop the event watcher"""
        logger.info("Stopping K8s event watcher...")
        self.is_running = False

    async def _check_cluster_events(self, cluster_config: Dict):
        """
        Check events and pod health for a specific cluster using Kubernetes API directly.

        Args:
            cluster_config: Cluster configuration from monitoring.yaml
        """
        cluster_name = cluster_config.get('name')
        namespaces = cluster_config.get('namespaces', [])

        logger.debug(f"Checking events in cluster: {cluster_name}")

        # If no K8s client, can't check events
        if not self.k8s_client:
            logger.debug("No Kubernetes client available, skipping event check")
            return

        # Check proactive pod health first
        await self._check_pod_health(cluster_name, namespaces)

        # Then check events
        # Get event filters from config
        event_filters = self.monitoring_config.get('monitoring', {}).get('event_filters', [])

        for namespace in namespaces:
            try:
                logger.debug(f"Fetching Warning events from namespace: {namespace}")

                # Calculate time window (last 5 minutes to avoid processing old events)
                time_threshold = datetime.utcnow() - timedelta(minutes=5)

                # Call Kubernetes API directly to get events
                events_list = self.k8s_client.list_namespaced_event(
                    namespace=namespace,
                    field_selector="type=Warning",
                    limit=50
                )

                # Filter recent events
                recent_events = []
                for event in events_list.items:
                    # Get event timestamp (handle None gracefully)
                    event_time = None
                    if event.last_timestamp:
                        event_time = event.last_timestamp
                    elif event.first_timestamp:
                        event_time = event.first_timestamp

                    # Only filter if we have a valid timestamp
                    if event_time:
                        try:
                            if event_time.replace(tzinfo=None) >= time_threshold:
                                recent_events.append(event)
                        except (AttributeError, TypeError):
                            # If timestamp comparison fails, include the event
                            recent_events.append(event)
                    else:
                        # Include events without timestamps (rare but possible)
                        recent_events.append(event)

                if recent_events:
                    logger.info(f"Found {len(recent_events)} recent Warning events in {namespace}")

                    # Process each event
                    for event in recent_events:
                        try:
                            await self._process_event(event, cluster_name)
                        except Exception as event_error:
                            logger.error(f"Error processing event {event.metadata.name}: {event_error}")
                            continue
                else:
                    logger.debug(f"No recent events found in {namespace}")

            except ApiException as e:
                if e.status == 404:
                    logger.debug(f"Namespace {namespace} not found, skipping")
                else:
                    logger.error(f"K8s API error for {namespace}: {e.status} - {e.reason}")
            except Exception as e:
                logger.error(f"Error fetching events from {namespace}: {e}")
                continue

    async def _process_event(self, k8s_event, cluster_name: str):
        """
        Process a K8s event and trigger alerts if needed.

        Args:
            k8s_event: Kubernetes V1Event object from kubernetes library
            cluster_name: Name of the cluster
        """
        event_uid = k8s_event.metadata.uid

        # Skip if already processed
        if event_uid in self.processed_events:
            logger.debug(f"Event {event_uid} already processed, skipping")
            return

        # Convert K8s event object to dict for compatibility
        event_dict = {
            'type': k8s_event.type,
            'reason': k8s_event.reason,
            'message': k8s_event.message,
            'count': k8s_event.count or 1,
            'first_timestamp': k8s_event.first_timestamp.isoformat() if k8s_event.first_timestamp else None,
            'last_timestamp': k8s_event.last_timestamp.isoformat() if k8s_event.last_timestamp else None,
            'involvedObject': {
                'kind': k8s_event.involved_object.kind,
                'name': k8s_event.involved_object.name,
                'namespace': k8s_event.involved_object.namespace
            }
        }

        # Check if event should trigger alert
        if not self.should_trigger_alert(event_dict):
            logger.debug(f"Event {event_dict.get('reason')} does not match filters")
            return

        # Mark as processed
        self.processed_events.add(event_uid)

        logger.info(f"Event matches filter: {event_dict.get('reason')} in {event_dict['involvedObject']['namespace']}")

        # Get pod info if available
        pod_info = None
        if event_dict['involvedObject']['kind'] == 'Pod':
            pod_info = await self._get_pod_info(
                event_dict['involvedObject']['name'],
                event_dict['involvedObject']['namespace']
            )

        # Evaluate alert rules
        alert = self.evaluate_alert_rules(event_dict, pod_info)

        if alert:
            # Add cluster name
            alert['cluster'] = cluster_name

            # Trigger incident handling
            logger.info(f"Alert rule triggered: {alert.get('rule_name')}")
            await self.trigger_agent_analysis(alert)

    async def _check_pod_health(self, cluster_name: str, namespaces: List[str]):
        """
        Proactively check pod health across namespaces.

        Checks for:
        - Pods not in Running state
        - High restart counts
        - Pods stuck in Pending/Unknown

        Args:
            cluster_name: Name of the cluster
            namespaces: List of namespaces to check
        """
        if not self.k8s_client:
            return

        for namespace in namespaces:
            try:
                logger.debug(f"Checking pod health in namespace: {namespace}")

                # Get all pods in namespace
                pods = self.k8s_client.list_namespaced_pod(namespace=namespace)

                for pod in pods.items:
                    pod_name = pod.metadata.name
                    pod_phase = pod.status.phase if pod.status else "Unknown"

                    # Calculate restart count
                    restart_count = 0
                    if pod.status and pod.status.container_statuses:
                        restart_count = sum(
                            container.restart_count
                            for container in pod.status.container_statuses
                        )

                    # Check for problematic states
                    issue_detected = False
                    alert_reason = None
                    alert_severity = "medium"

                    # 1. Check if pod not in Running state
                    if pod_phase not in ["Running", "Succeeded"]:
                        issue_detected = True
                        alert_reason = f"PodNotRunning_{pod_phase}"
                        alert_severity = "high" if pod_phase in ["Pending", "Unknown"] else "medium"
                        logger.info(f"Pod health issue: {pod_name} in {namespace} is {pod_phase}")

                    # 2. Check for high restart counts
                    elif restart_count > 5:
                        issue_detected = True
                        alert_reason = "HighRestartCount"
                        alert_severity = "critical" if restart_count > 10 else "high"
                        logger.info(f"Pod health issue: {pod_name} in {namespace} has {restart_count} restarts")

                    # 3. Check for pods stuck in Pending/Unknown
                    if pod_phase in ["Pending", "Unknown"]:
                        # Check how long pod has been in this state
                        creation_time = pod.metadata.creation_timestamp
                        if creation_time:
                            try:
                                age_minutes = (datetime.utcnow().replace(tzinfo=None) - creation_time.replace(tzinfo=None)).total_seconds() / 60
                                if age_minutes > 5:  # Stuck for more than 5 minutes
                                    issue_detected = True
                                    alert_reason = f"PodStuck{pod_phase}"
                                    alert_severity = "critical"
                                    logger.warning(f"Pod stuck: {pod_name} in {namespace} stuck in {pod_phase} for {age_minutes:.1f} minutes")
                            except (TypeError, AttributeError) as e:
                                logger.debug(f"Could not calculate pod age: {e}")

                    # If issue detected, create synthetic alert (with deduplication)
                    if issue_detected:
                        pod_key = f"{namespace}/{pod_name}/{alert_reason}"

                        # Check if we've recently alerted on this pod issue
                        last_alert_time = self.processed_pod_alerts.get(pod_key)
                        now = datetime.utcnow()

                        # Only alert if:
                        # - Never alerted before, OR
                        # - Last alert was > 30 minutes ago (avoid spam)
                        should_alert = (
                            last_alert_time is None or
                            (now - last_alert_time).total_seconds() > 1800
                        )

                        if should_alert:
                            await self._create_pod_health_alert(
                                pod=pod,
                                cluster_name=cluster_name,
                                reason=alert_reason,
                                severity=alert_severity,
                                restart_count=restart_count
                            )
                            # Track that we alerted
                            self.processed_pod_alerts[pod_key] = now
                        else:
                            logger.debug(f"Skipping duplicate alert for {pod_key} (last alert {(now - last_alert_time).total_seconds() / 60:.1f} min ago)")

            except ApiException as e:
                if e.status != 404:
                    logger.error(f"Error checking pod health in {namespace}: {e.reason}")
            except Exception as e:
                logger.error(f"Error checking pod health in {namespace}: {e}")

    async def _create_pod_health_alert(self, pod, cluster_name: str, reason: str, severity: str, restart_count: int):
        """
        Create alert from proactive pod health check.

        Args:
            pod: Kubernetes pod object
            cluster_name: Cluster name
            reason: Alert reason
            severity: Alert severity
            restart_count: Pod restart count
        """
        pod_name = pod.metadata.name
        namespace = pod.metadata.namespace

        # Create synthetic event dict compatible with existing alert evaluation
        synthetic_event = {
            'type': 'Warning',
            'reason': reason,
            'message': f"Proactive health check detected: {pod_name} {pod.status.phase if pod.status else 'Unknown'}",
            'count': restart_count,
            'first_timestamp': pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None,
            'last_timestamp': datetime.utcnow().isoformat(),
            'involvedObject': {
                'kind': 'Pod',
                'name': pod_name,
                'namespace': namespace
            }
        }

        # Build pod info
        pod_info = {
            'name': pod_name,
            'namespace': namespace,
            'restart_count': restart_count,
            'phase': pod.status.phase if pod.status else 'Unknown'
        }

        # Create alert
        alert = {
            'rule_name': f'proactive-pod-health-{reason.lower()}',
            'severity': severity,
            'condition': f'Pod health check: {reason}',
            'event': synthetic_event,
            'pod_info': pod_info,
            'timestamp': datetime.now().isoformat(),
            'cluster': cluster_name
        }

        logger.info(f"Triggering proactive health alert: {alert['rule_name']} for {pod_name}")
        await self.trigger_agent_analysis(alert)

    async def _get_pod_info(self, pod_name: str, namespace: str) -> Optional[Dict]:
        """
        Get pod information including restart count.

        Args:
            pod_name: Name of the pod
            namespace: Namespace

        Returns:
            Pod info dict with restart count
        """
        if not self.k8s_client:
            return None

        try:
            pod = self.k8s_client.read_namespaced_pod(name=pod_name, namespace=namespace)

            # Calculate total restart count from all containers
            restart_count = 0
            if pod.status and pod.status.container_statuses:
                restart_count = sum(
                    container.restart_count
                    for container in pod.status.container_statuses
                )

            # Get replica info if deployment
            available_replicas = None
            desired_replicas = None

            # Try to find parent deployment
            owner_refs = pod.metadata.owner_references or []
            for owner in owner_refs:
                if owner.kind == "ReplicaSet":
                    # Could fetch replicaset and then deployment, but skip for now
                    pass

            return {
                'name': pod_name,
                'namespace': namespace,
                'restart_count': restart_count,
                'phase': pod.status.phase if pod.status else 'Unknown',
                'available_replicas': available_replicas,
                'desired_replicas': desired_replicas
            }

        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Could not get pod info for {pod_name}: {e.reason}")
            return {
                'name': pod_name,
                'namespace': namespace,
                'restart_count': 0
            }
        except Exception as e:
            logger.error(f"Error getting pod info: {e}")
            return None

    def should_trigger_alert(self, event: Dict) -> bool:
        """
        Determine if an event should trigger an agent alert.

        Args:
            event: Kubernetes event object

        Returns:
            True if event meets alert criteria
        """
        event_reason = event.get('reason', '')
        event_type = event.get('type', '')

        # Get event filters from config
        event_filters = self.monitoring_config.get('monitoring', {}).get('event_filters', [])

        # Check if event matches any filter
        for filter_config in event_filters:
            if event_type == filter_config.get('type'):
                filter_reasons = filter_config.get('reasons', [])
                if event_reason in filter_reasons:
                    logger.info(f"Event matches filter: {event_reason}")
                    return True

        return False

    def evaluate_alert_rules(self, event: Dict, pod_info: Optional[Dict] = None) -> Optional[Dict]:
        """
        Evaluate event against configured alert rules.

        Args:
            event: Kubernetes event
            pod_info: Optional pod information for context

        Returns:
            Alert object if rules triggered, None otherwise
        """
        alert_rules = self.monitoring_config.get('monitoring', {}).get('alert_rules', [])

        for rule in alert_rules:
            rule_name = rule.get('name')
            condition = rule.get('condition', '')
            severity = rule.get('severity', 'medium')

            # Evaluate condition (supports simple and compound conditions)
            if self._evaluate_condition(condition, event, pod_info):
                logger.info(f"Alert rule triggered: {rule_name}")

                return {
                    "rule_name": rule_name,
                    "severity": severity,
                    "condition": condition,
                    "event": event,
                    "pod_info": pod_info,
                    "timestamp": datetime.now().isoformat()
                }

        return None

    def _evaluate_condition(self, condition: str, event: Dict, pod_info: Optional[Dict]) -> bool:
        """
        Evaluate alert rule condition with support for compound expressions.

        Supports:
        - Simple comparisons: "restart_count > 5", "reason == 'OOMKilled'"
        - Compound conditions: "reason == 'CrashLoopBackOff' AND restart_count > 3"
        - Operators: >, <, ==, >=, <= (with or without spaces)

        Args:
            condition: Condition string from alert rule
            event: Event data
            pod_info: Pod data

        Returns:
            True if condition is met
        """
        # Handle compound conditions with AND
        if ' AND ' in condition:
            parts = condition.split(' AND ')
            return all(self._evaluate_simple_condition(part.strip(), event, pod_info) for part in parts)

        # Handle compound conditions with OR
        if ' OR ' in condition:
            parts = condition.split(' OR ')
            return any(self._evaluate_simple_condition(part.strip(), event, pod_info) for part in parts)

        # Simple condition
        return self._evaluate_simple_condition(condition, event, pod_info)

    def _evaluate_simple_condition(self, condition: str, event: Dict, pod_info: Optional[Dict]) -> bool:
        """
        Evaluate a simple (non-compound) condition.

        Args:
            condition: Simple condition string
            event: Event data
            pod_info: Pod data

        Returns:
            True if condition is met
        """
        condition = condition.strip()

        # Handle restart_count comparisons
        if "restart_count" in condition:
            actual = pod_info.get('restart_count', 0) if pod_info else 0

            if '>=' in condition:
                threshold = int(condition.split('>=')[1].strip())
                return actual >= threshold
            elif '>' in condition:
                threshold = int(condition.split('>')[1].strip())
                return actual > threshold
            elif '<=' in condition:
                threshold = int(condition.split('<=')[1].strip())
                return actual <= threshold
            elif '<' in condition:
                threshold = int(condition.split('<')[1].strip())
                return actual < threshold

        # Handle reason equality checks
        if "reason ==" in condition:
            expected_reason = condition.split('==')[1].strip().strip('"').strip("'")
            actual_reason = event.get('reason', '')
            return actual_reason == expected_reason

        # Handle replica comparisons
        if "available_replicas < desired_replicas" in condition:
            if pod_info:
                available = pod_info.get('available_replicas')
                desired = pod_info.get('desired_replicas')

                # Only compare if both values are present
                if available is not None and desired is not None:
                    return available < desired
                else:
                    # Can't evaluate without replica info
                    return False

        # Unknown condition format
        logger.warning(f"Unknown condition format: {condition}")
        return False

    async def trigger_agent_analysis(self, alert: Dict):
        """
        Trigger agent analysis for an alert with correlation/deduplication.

        Groups related incidents for the same service to avoid duplicate processing.

        Args:
            alert: Alert object with incident details
        """
        if not self.agent_callback:
            logger.warning("No agent callback configured, skipping analysis")
            return

        # Create correlation key: service + namespace
        service = alert.get('event', {}).get('involvedObject', {}).get('name', '')
        namespace = alert.get('event', {}).get('involvedObject', {}).get('namespace', 'default')

        # Extract service name from pod name if needed
        if '-' in service:
            service_name = '-'.join(service.split('-')[:-2])
        else:
            service_name = service

        correlation_key = f"{namespace}/{service_name}"

        # Check if we have an active incident for this service
        now = datetime.utcnow()
        active_incident = self.active_incidents.get(correlation_key)

        # If same service was analyzed in last 30 minutes, group incidents
        if active_incident:
            last_analysis_time = active_incident['last_analysis_time']
            time_since_last = (now - last_analysis_time).total_seconds()

            if time_since_last < 1800:  # 30 minutes
                # Add this issue to existing incident
                active_incident['related_issues'].append({
                    'rule_name': alert.get('rule_name'),
                    'reason': alert.get('event', {}).get('reason'),
                    'timestamp': alert.get('timestamp')
                })
                logger.info(f"Grouping with existing incident for {correlation_key} (analyzed {time_since_last / 60:.1f} min ago)")
                logger.info(f"  Total related issues: {len(active_incident['related_issues'])}")
                return  # Skip duplicate analysis

        # New incident or outside correlation window
        logger.info(f"Triggering agent analysis for alert: {alert.get('rule_name')}")

        # Track this as active incident
        self.active_incidents[correlation_key] = {
            'last_analysis_time': now,
            'related_issues': [{
                'rule_name': alert.get('rule_name'),
                'reason': alert.get('event', {}).get('reason'),
                'timestamp': alert.get('timestamp')
            }],
            'severity': alert.get('severity')
        }

        try:
            # Call agent callback
            await self.agent_callback(alert)
        except Exception as e:
            logger.error(f"Error triggering agent analysis: {e}")

    def get_service_criticality(self, service_name: str) -> str:
        """
        Get service criticality level from configuration.

        Args:
            service_name: Name of the service

        Returns:
            Criticality level (critical/high/medium/low)
        """
        criticality_map = self.monitoring_config.get('monitoring', {}).get('service_criticality', {})

        for level in ['critical', 'high', 'medium', 'low']:
            services = criticality_map.get(level, [])
            if service_name in services:
                return level

        return 'low'  # Default criticality


# Example usage
async def main():
    """
    Example of running the event watcher standalone.
    """

    async def alert_callback(alert: Dict):
        """Example callback for alerts"""
        print(f"\n🚨 Alert Triggered: {alert.get('rule_name')}")
        print(f"Severity: {alert.get('severity')}")
        print(f"Event: {alert.get('event', {}).get('reason')}")
        print(f"Timestamp: {alert.get('timestamp')}\n")

    watcher = KubernetesEventWatcher(agent_callback=alert_callback)
    await watcher.start()


if __name__ == "__main__":
    asyncio.run(main())
