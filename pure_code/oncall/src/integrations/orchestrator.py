"""
Integration Orchestrator
Coordinates between agent, K8s watcher, GitHub tracker, and Zeus memory
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional
from pathlib import Path
import yaml
from dotenv import load_dotenv

from integrations.k8s_event_watcher import KubernetesEventWatcher
from tools.github_integrator import GitHubDeploymentTracker
from notifications.teams_notifier import TeamsNotifier

logger = logging.getLogger(__name__)


class IntegrationOrchestrator:
    """
    Orchestrates integration between all components:
    - K8s event watcher monitors cluster
    - GitHub tracker correlates deployments
    - Agent processes incidents

    This is the main entry point for production deployment.
    """

    def __init__(self, agent, config_path: Optional[Path] = None):
        """
        Initialize the integration orchestrator.

        Args:
            agent: OnCallTroubleshootingAgent instance
            config_path: Path to configuration directory
        """
        # Load environment variables
        load_dotenv()

        self.agent = agent
        self.config_path = config_path or Path(__file__).parent.parent.parent / "config"

        # Load service mapping
        self.service_mapping = self._load_service_mapping()

        # Load monitoring config for cluster information
        self.monitoring_config = self._load_monitoring_config()

        # Initialize Teams notifier (if configured)
        self.teams_notifier = self._initialize_teams_notifier()

        # Initialize components
        self.k8s_watcher = KubernetesEventWatcher(
            config_path=self.config_path,
            agent_callback=self.handle_incident
        )
        self.github_tracker = GitHubDeploymentTracker(org="artemishealth")

        teams_status = "enabled" if self.teams_notifier else "disabled"
        logger.info(f"IntegrationOrchestrator initialized (Teams notifications: {teams_status})")

    def _load_service_mapping(self) -> Dict:
        """Load service-to-deployment mapping configuration"""
        config_file = self.config_path / "service_mapping.yaml"
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning(f"Service mapping not found at {config_file}")
            return {}

    def _load_monitoring_config(self) -> Dict:
        """Load K8s monitoring configuration for cluster information"""
        config_file = self.config_path / "k8s_monitoring.yaml"
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning(f"Monitoring config not found at {config_file}")
            return {}

    def _initialize_teams_notifier(self) -> Optional[TeamsNotifier]:
        """
        Initialize Teams notifier if configured.

        Checks:
        - TEAMS_WEBHOOK_URL environment variable
        - TEAMS_NOTIFICATIONS_ENABLED environment variable
        - config/notifications.yaml for additional settings

        Returns:
            TeamsNotifier instance if enabled, None otherwise
        """
        webhook_url = os.getenv('TEAMS_WEBHOOK_URL')
        enabled = os.getenv('TEAMS_NOTIFICATIONS_ENABLED', 'false').lower() == 'true'

        # Load notification config
        notifications_config = {}
        config_file = self.config_path / "notifications.yaml"
        try:
            with open(config_file, 'r') as f:
                config_data = yaml.safe_load(f)
                notifications_config = config_data.get('teams_notifications', {})
        except FileNotFoundError:
            logger.info(f"No notifications.yaml found, using defaults")

        # If disabled, enable dry-run mode (logs notifications without sending)
        if not enabled:
            logger.info("Teams notifications disabled (TEAMS_NOTIFICATIONS_ENABLED=false)")
            logger.info("Enabling dry-run mode - notifications will be logged but not sent")
            # Still create notifier with dry_run=True so we can see what would be sent
            webhook_url = webhook_url or "http://dry-run.local/webhook"
            return TeamsNotifier(webhook_url, config=notifications_config, dry_run=True)

        if not webhook_url:
            logger.warning("Teams notifications enabled but TEAMS_WEBHOOK_URL not set")
            return None

        logger.info(f"Teams notifications enabled")
        logger.info(f"Webhook: {webhook_url[:60]}...")
        return TeamsNotifier(webhook_url, config=notifications_config, dry_run=False)

    def _get_cluster_name(self) -> str:
        """
        Get cluster name from monitoring configuration.

        Returns:
            Cluster name from config, defaults to 'dev-eks'
        """
        clusters = self.monitoring_config.get('monitoring', {}).get('clusters', [])
        if clusters:
            return clusters[0].get('name', 'dev-eks')
        return 'dev-eks'

    async def start(self):
        """
        Start the integration orchestrator.

        This starts all components and begins monitoring.
        """
        logger.info("="*60)
        logger.info("Starting On-Call Troubleshooting Agent")
        logger.info("="*60)
        logger.info(f"Config path: {self.config_path}")
        logger.info(f"Service mappings loaded: {len(self.service_mapping.get('service_mappings', {}))}")
        logger.info(f"Cluster: {self._get_cluster_name()}")
        logger.info("")

        # Start K8s event watcher
        logger.info("Starting Kubernetes event watcher...")
        await self.k8s_watcher.start()

    async def handle_incident(self, alert: Dict):
        """
        Handle an incident triggered by the event watcher.

        Workflow:
        1. Enrich alert with service mapping
        2. Send immediate Teams notification (if critical)
        3. Trigger agent analysis (triage engine)
        4. Send diagnosis complete notification
        5. Alert for human action (GitOps)

        Args:
            alert: Alert from K8s event watcher
        """
        logger.info(f"Processing incident: {alert.get('rule_name')}")

        try:
            # Enrich alert with service mapping
            enriched_alert = self._enrich_alert(alert)

            # Use triage engine directly for structured incident handling with Teams notifications
            from agent.incident_triage import IncidentTriageEngine

            triage_engine = IncidentTriageEngine(
                agent_client=self.agent.client,
                teams_notifier=self.teams_notifier
            )

            logger.info("Running incident through triage engine...")
            triage_result = await triage_engine.triage_incident(enriched_alert)

            logger.info(f"Triage complete: {triage_result.get('status')}")
            logger.info(f"Actions taken: {len(triage_result.get('actions_taken', []))}")
            logger.info(f"Incident processing complete: {alert.get('rule_name')}")

        except Exception as e:
            logger.error(f"Error handling incident: {e}")

            # Send error notification to Teams if available
            if self.teams_notifier:
                try:
                    await self.teams_notifier.send_escalation_alert(
                        incident=alert,
                        reason=f"Error processing incident: {str(e)[:200]}"
                    )
                except Exception:
                    pass  # Don't fail on notification failure

    def _enrich_alert(self, alert: Dict) -> Dict:
        """
        Enrich alert with service mapping data.

        Extracts service name from pod name using format: service-name-hash-pod
        (e.g., proteus-service-5d7f8-abc123 → proteus-service)

        Args:
            alert: Raw alert from event watcher

        Returns:
            Enriched alert with service metadata
        """
        # Extract service name from event
        event = alert.get('event', {})
        involved_object = event.get('involvedObject', {})
        object_kind = involved_object.get('kind', '')
        object_name = involved_object.get('name', '')

        # Extract service name based on object type
        if object_kind == 'Pod':
            # Pod format: service-name-hash-pod
            service_name = '-'.join(object_name.split('-')[:-2]) if '-' in object_name else object_name
        elif object_kind in ['NodePool', 'Node']:
            # Infrastructure objects - use object name as service name
            service_name = object_name
        else:
            # Other objects - use name as-is
            service_name = object_name

        logger.debug(f"Extracting service from {object_kind}/{object_name} → {service_name}")

        # Get service mapping
        service_mappings = self.service_mapping.get('service_mappings', {})
        service_config = service_mappings.get(service_name, {})

        # Warn if service not in mapping
        if service_name and service_name not in service_mappings:
            logger.warning(f"Service '{service_name}' not found in service_mapping.yaml, using defaults")

        # Enrich alert
        enriched = alert.copy()
        enriched['service'] = service_name
        # Default to deployments repo since all services are deployed via it
        enriched['github_repo'] = service_config.get('github_repo', 'artemishealth/deployments')

        # Use actual event namespace (not service_mapping namespace)
        # This allows same service to be monitored across multiple namespaces
        event_namespace = event.get('involvedObject', {}).get('namespace', 'default')
        enriched['namespace'] = event_namespace

        enriched['criticality'] = service_config.get('criticality', 'medium')

        return enriched


async def main() -> None:
    """
    Example of running the orchestrator standalone.

    In production, this would be started as a daemon/service.
    """
    from agent.oncall_agent import OnCallTroubleshootingAgent

    # Initialize agent
    agent = OnCallTroubleshootingAgent()

    # Create orchestrator
    orchestrator = IntegrationOrchestrator(agent)

    # Start orchestration
    logger.info("Starting integration orchestrator...")
    try:
        await orchestrator.start()
    except KeyboardInterrupt:
        logger.info("\nShutting down orchestrator...")
    except Exception as e:
        logger.error(f"Orchestrator error: {e}")
        raise


if __name__ == "__main__":
    # Configure logging for standalone execution
    import os
    log_level = os.getenv('AGENT_LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    asyncio.run(main())
