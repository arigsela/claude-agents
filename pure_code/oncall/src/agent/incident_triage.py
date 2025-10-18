"""
Incident Triage Engine
Handles incident severity classification and routing
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional
import logging
import os
import json
from datetime import datetime

# Import helper modules
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.github_integrator import GitHubDeploymentTracker
from tools.aws_integrator import AWSIntegrator

# Anthropic API for LLM analysis in daemon mode
from anthropic import Anthropic

if TYPE_CHECKING:
    from notifications.teams_notifier import TeamsNotifier

logger = logging.getLogger(__name__)


class IncidentTriageEngine:
    """
    Triage engine for classifying and routing incidents based on severity.

    Severity Levels:
    - critical: Service outage, data loss risk, immediate action required
    - high: Service degradation, high restart rate, automated remediation
    - medium: Warning signs, monitoring required, queue for review
    - low: Informational, document and learn
    """

    # Severity determination thresholds
    CRITICAL_OOM_RESTART_THRESHOLD = 10
    CRITICAL_NAMESPACE_RESTART_THRESHOLD = 5
    HIGH_RESTART_THRESHOLD = 3
    MEDIUM_RESTART_THRESHOLD = 1
    HUMAN_INTERVENTION_RESTART_THRESHOLD = 15

    # Rollback decision thresholds
    ROLLBACK_CONFIDENCE_THRESHOLD = 0.8

    def __init__(self, agent_client, teams_notifier: Optional['TeamsNotifier'] = None):
        self.client = agent_client
        self.teams_notifier = teams_notifier
        self.triage_levels = {
            "critical": self.handle_critical,
            "high": self.handle_high,
            "medium": self.handle_medium,
            "low": self.handle_low
        }

        # Initialize helper managers
        self.github_tracker = GitHubDeploymentTracker(org="artemishealth")
        self.aws_integrator = AWSIntegrator()

        # Initialize Anthropic client for LLM analysis in daemon mode
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.anthropic_client = Anthropic(api_key=api_key) if api_key else None

        teams_status = "enabled" if teams_notifier else "disabled"
        llm_status = "enabled" if self.anthropic_client else "disabled (no API key)"
        aws_status = "enabled" if self.aws_integrator.boto3_available else "disabled (no boto3)"
        logger.info(f"IncidentTriageEngine initialized with GitHub and AWS integration (Teams: {teams_status}, LLM: {llm_status}, AWS: {aws_status})")

    async def triage_incident(self, alert: Dict) -> Dict:
        """
        Main triage entry point with LLM analysis.

        Args:
            alert: Incident alert payload with service, error, pod info

        Returns:
            Triage result with severity, diagnosis, and actions taken
        """
        # Use LLM to analyze if available, otherwise fall back to rules
        if self.anthropic_client:
            llm_analysis = await self._analyze_with_llm(alert)
            severity = llm_analysis.get('severity', 'medium')
            # Store LLM analysis in alert for later use
            alert['llm_analysis'] = llm_analysis
        else:
            severity = self.determine_severity(alert)

        # Get handler for severity level
        handler = self.triage_levels.get(severity)

        return await handler(alert)

    async def _analyze_with_llm(self, alert: Dict) -> Dict:
        """
        Use Claude LLM to analyze incident and determine severity, root cause, and remediation.

        Args:
            alert: Incident alert data

        Returns:
            LLM analysis with severity, root_cause, remediation_steps, teams_notification_needed
        """
        if not self.anthropic_client:
            return {"error": "No Anthropic API client available"}

        try:
            # Build context for Claude
            incident_context = {
                "service": alert.get('service', 'unknown'),
                "namespace": alert.get('namespace', 'unknown'),
                "error_type": alert.get('event', {}).get('reason', 'unknown'),
                "error_message": alert.get('event', {}).get('message', ''),
                "restart_count": alert.get('pod_info', {}).get('restart_count', 0),
                "pod_phase": alert.get('pod_info', {}).get('phase', 'unknown'),
                "service_criticality": alert.get('criticality', 'medium'),
                "cluster": alert.get('cluster', 'unknown'),
                "timestamp": alert.get('timestamp', datetime.now().isoformat())
            }

            prompt = f"""You are an expert Kubernetes on-call engineer analyzing an incident.

**Incident Details:**
- Service: {incident_context['service']}
- Namespace: {incident_context['namespace']}
- Error Type: {incident_context['error_type']}
- Error Message: {incident_context['error_message']}
- Pod Restart Count: {incident_context['restart_count']}
- Pod Phase: {incident_context['pod_phase']}
- Service Criticality: {incident_context['service_criticality']}
- Cluster: {incident_context['cluster']}

Analyze this incident and provide:

1. **Severity** (critical/high/medium/low) - Consider:
   - Service criticality configuration
   - Error type impact
   - Restart count trends
   - Pod state

2. **Root Cause** - Most likely cause based on error type and context

3. **Remediation Steps** - Specific actionable steps (3-5 steps)

4. **Teams Notification** (yes/no) - Should on-call be immediately notified?

Respond in JSON format:
{{
  "severity": "critical|high|medium|low",
  "root_cause": "Brief explanation of likely cause",
  "remediation_steps": ["step 1", "step 2", "step 3"],
  "teams_notification_needed": true|false,
  "reasoning": "Why you assessed this severity"
}}"""

            logger.debug(f"Analyzing incident with Claude LLM: {incident_context['service']} - {incident_context['error_type']}")

            # Call Claude API
            message = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                temperature=0.3,  # Lower temperature for consistent analysis
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Parse response
            response_text = message.content[0].text

            # Extract JSON from response
            try:
                # Try to find JSON in response
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    analysis = json.loads(response_text[json_start:json_end])

                    # Log detailed analysis results
                    logger.info(f"LLM analysis complete: severity={analysis.get('severity')}, notification={analysis.get('teams_notification_needed')}")
                    logger.debug(f"LLM root cause: {analysis.get('root_cause')}")
                    logger.debug(f"LLM reasoning: {analysis.get('reasoning')}")

                    remediation = analysis.get('remediation_steps', [])
                    if remediation:
                        logger.debug(f"LLM remediation steps ({len(remediation)}):")
                        for i, step in enumerate(remediation, 1):
                            logger.debug(f"  {i}. {step}")

                    # Follow-up investigation: Execute Claude's suggested checks
                    logger.debug("Attempting follow-up investigation based on LLM suggestions...")
                    investigation_results = await self._execute_investigation_steps(alert, analysis)

                    # If we gathered additional data, ask Claude to refine analysis
                    if investigation_results.get('data_collected'):
                        logger.info("Follow-up data collected, asking Claude for refined analysis...")
                        refined_analysis = await self._refine_analysis_with_data(
                            alert, analysis, investigation_results
                        )
                        return refined_analysis

                    return analysis
                else:
                    raise ValueError("No JSON found in response")

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse LLM response as JSON: {e}")
                logger.debug(f"Raw response: {response_text}")
                # Fall back to rule-based severity
                return {
                    "severity": self.determine_severity(alert),
                    "root_cause": "LLM analysis failed - using rule-based classification",
                    "remediation_steps": self._get_basic_remediation(incident_context['error_type'].lower()),
                    "teams_notification_needed": self.determine_severity(alert) in ["critical", "high"],
                    "error": str(e)
                }

        except Exception as e:
            logger.error(f"LLM analysis error: {e}")
            # Fall back to rule-based
            return {
                "severity": self.determine_severity(alert),
                "root_cause": f"LLM analysis failed: {str(e)}",
                "remediation_steps": ["Manual investigation required"],
                "teams_notification_needed": False,
                "error": str(e)
            }

    async def _execute_investigation_steps(self, alert: Dict, initial_analysis: Dict) -> Dict:
        """
        Execute investigative actions suggested by Claude (like checking logs, resource usage).

        Args:
            alert: Incident alert
            initial_analysis: Claude's initial analysis

        Returns:
            Investigation results with collected data
        """
        results = {
            "data_collected": False,
            "pod_logs": None,
            "pod_description": None,
            "recent_events": None,
            "resource_usage": None
        }

        # Get K8s client from orchestrator (need to pass it in)
        # For now, we'll gather what we can from the alert
        pod_name = alert.get('event', {}).get('involvedObject', {}).get('name')
        namespace = alert.get('namespace')

        if not pod_name or not namespace:
            logger.debug("Insufficient info for follow-up investigation")
            return results

        logger.debug(f"Executing follow-up investigation for {pod_name} in {namespace}")

        # Import kubernetes client
        from kubernetes import client as k8s_client, config as k8s_config

        try:
            # Get K8s API client
            try:
                # Try in-cluster config first (for container deployment)
                try:
                    k8s_config.load_incluster_config()
                    logger.debug("Loaded in-cluster K8s config for investigation")
                except k8s_config.ConfigException:
                    # Fall back to kubeconfig file (for local development)
                    k8s_config.load_kube_config()
                    logger.debug("Loaded K8s config from kubeconfig for investigation")

                v1 = k8s_client.CoreV1Api()
            except Exception as e:
                logger.warning(f"Could not load K8s config for follow-up investigation: {e}")
                return results

            # 1. Get pod logs (last 50 lines from previous container if restarted)
            try:
                logs = v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    previous=True,  # Get logs from previous container
                    tail_lines=50
                )
                results["pod_logs"] = logs
                results["data_collected"] = True
                logger.debug(f"✓ Collected pod logs ({len(logs)} chars)")
            except Exception as e:
                logger.debug(f"Could not get pod logs: {e}")

            # 2. Get pod description (resource limits, status)
            try:
                pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)

                # Extract relevant info
                containers_info = []
                if pod.spec and pod.spec.containers:
                    for container in pod.spec.containers:
                        limits = container.resources.limits if container.resources and container.resources.limits else {}
                        requests = container.resources.requests if container.resources and container.resources.requests else {}

                        containers_info.append({
                            "name": container.name,
                            "image": container.image,
                            "memory_limit": limits.get('memory', 'not set'),
                            "memory_request": requests.get('memory', 'not set'),
                            "cpu_limit": limits.get('cpu', 'not set'),
                            "cpu_request": requests.get('cpu', 'not set')
                        })

                # Get pod status conditions for failure reasons
                pod_conditions = []
                if pod.status and pod.status.conditions:
                    for cond in pod.status.conditions:
                        pod_conditions.append({
                            "type": cond.type,
                            "status": cond.status,
                            "reason": cond.reason,
                            "message": cond.message
                        })

                # Get container state reasons (why containers failed)
                container_states = []
                if pod.status and pod.status.container_statuses:
                    for container_status in pod.status.container_statuses:
                        state_info = {}

                        if container_status.state:
                            if container_status.state.waiting:
                                state_info = {
                                    "state": "waiting",
                                    "reason": container_status.state.waiting.reason,
                                    "message": container_status.state.waiting.message
                                }
                            elif container_status.state.terminated:
                                state_info = {
                                    "state": "terminated",
                                    "reason": container_status.state.terminated.reason,
                                    "message": container_status.state.terminated.message,
                                    "exit_code": container_status.state.terminated.exit_code
                                }
                            elif container_status.state.running:
                                state_info = {"state": "running"}

                        container_states.append({
                            "name": container_status.name,
                            "ready": container_status.ready,
                            "restart_count": container_status.restart_count,
                            "state": state_info
                        })

                results["pod_description"] = {
                    "containers": containers_info,
                    "container_states": container_states,
                    "pod_conditions": pod_conditions,
                    "restart_policy": pod.spec.restart_policy if pod.spec else None,
                    "node_name": pod.spec.node_name if pod.spec else None,
                    "pod_phase": pod.status.phase if pod.status else "Unknown"
                }
                results["data_collected"] = True
                logger.debug(f"✓ Collected pod resource configuration with status details")
            except Exception as e:
                logger.debug(f"Could not get pod description: {e}")

            # 3. Get recent events for this pod
            try:
                events = v1.list_namespaced_event(
                    namespace=namespace,
                    field_selector=f"involvedObject.name={pod_name}",
                    limit=10
                )

                event_summary = []
                for event in events.items:
                    event_summary.append({
                        "reason": event.reason,
                        "message": event.message,
                        "count": event.count,
                        "last_seen": event.last_timestamp.isoformat() if event.last_timestamp else None
                    })

                results["recent_events"] = event_summary
                results["data_collected"] = True
                logger.debug(f"✓ Collected {len(event_summary)} recent events")

                # 4. If events mention missing secrets, check for ExternalSecret resources
                for event in event_summary:
                    if 'secret' in event['message'].lower() and 'not found' in event['message'].lower():
                        logger.debug("Missing secret detected in events, checking ExternalSecret resources...")
                        external_secrets = await self._check_external_secrets(namespace)
                        if external_secrets:
                            results["external_secrets"] = external_secrets
                            results["data_collected"] = True
                            logger.info(f"✓ Found {len(external_secrets)} FAILING ExternalSecret resources")

                            # Also check if secrets actually exist in AWS Secrets Manager
                            aws_secrets_status = await self.aws_integrator.verify_secrets_manager(external_secrets)
                            if aws_secrets_status:
                                results["aws_secrets_verification"] = aws_secrets_status
                                logger.info(f"✓ Verified AWS Secrets Manager status for {len(aws_secrets_status)} secrets")
                        break

                # 5. If events mention image pull errors, verify ECR images exist
                for event in event_summary:
                    if 'imagepull' in event['reason'].lower() or 'pull' in event['message'].lower():
                        logger.info("Image pull issue detected, verifying ECR images...")
                        # Get container images from pod description
                        if results.get('pod_description'):
                            containers = results['pod_description'].get('containers', [])
                            ecr_verification = await self.aws_integrator.verify_ecr_images(containers)
                            if ecr_verification:
                                results["ecr_verification"] = ecr_verification
                                results["data_collected"] = True
                                logger.info(f"✓ Verified ECR status for {len(ecr_verification)} images")
                        break

            except Exception as e:
                logger.debug(f"Could not get pod events: {e}")

        except Exception as e:
            logger.error(f"Error during follow-up investigation: {e}")

        return results

    async def _check_external_secrets(self, namespace: str) -> List[Dict]:
        """
        Check ExternalSecret resources in namespace (for secret sync status).

        Args:
            namespace: Namespace to check

        Returns:
            List of ExternalSecret resources with their sync status
        """
        external_secrets = []

        try:
            from kubernetes import client as k8s_client, config as k8s_config

            try:
                # Try in-cluster config first (for container deployment)
                try:
                    k8s_config.load_incluster_config()
                except k8s_config.ConfigException:
                    # Fall back to kubeconfig file (for local development)
                    k8s_config.load_kube_config()

                # Use CustomObjectsApi for CRDs
                custom_api = k8s_client.CustomObjectsApi()
            except Exception as e:
                logger.debug(f"Could not load K8s config for ExternalSecret check: {e}")
                return external_secrets

            # Query ExternalSecret CRD
            try:
                secrets_list = custom_api.list_namespaced_custom_object(
                    group="external-secrets.io",
                    version="v1beta1",
                    namespace=namespace,
                    plural="externalsecrets"
                )

                for item in secrets_list.get('items', []):
                    metadata = item.get('metadata', {})
                    status = item.get('status', {})
                    spec = item.get('spec', {})

                    # Check if ExternalSecret is actually failing
                    conditions = status.get('conditions', [])
                    is_failing = any(
                        cond.get('type') == 'Ready' and cond.get('status') == 'False'
                        for cond in conditions
                    )

                    # Only include failing ExternalSecrets
                    if is_failing:
                        # Get the actual AWS secret path from spec.data
                        data_spec = spec.get('data', [])
                        aws_secret_key = None
                        if data_spec and len(data_spec) > 0:
                            # Get the remote reference (actual AWS path)
                            remote_ref = data_spec[0].get('remoteRef', {})
                            aws_secret_key = remote_ref.get('key')

                        external_secrets.append({
                            "name": metadata.get('name'),
                            "namespace": namespace,
                            "sync_status": conditions,
                            "secret_store": spec.get('secretStoreRef', {}).get('name'),
                            "target_secret": spec.get('target', {}).get('name'),
                            "aws_secret_path": aws_secret_key,  # ← Actual AWS path!
                            "refresh_interval": spec.get('refreshInterval'),
                            "last_sync": status.get('refreshTime'),
                            "is_failing": True
                        })

                if external_secrets:
                    logger.info(f"Found {len(external_secrets)} FAILING ExternalSecret resources in {namespace}")
                else:
                    logger.debug(f"No failing ExternalSecrets in {namespace} (healthy secrets not investigated)")

            except Exception as e:
                logger.debug(f"Could not query ExternalSecrets (may not be installed): {e}")

        except Exception as e:
            logger.debug(f"Error checking external secrets: {e}")

        return external_secrets


    async def _refine_analysis_with_data(self, alert: Dict, initial_analysis: Dict, investigation_data: Dict) -> Dict:
        """
        Send investigation data back to Claude for refined analysis.

        Args:
            alert: Original alert
            initial_analysis: Claude's initial analysis
            investigation_data: Data collected from investigation

        Returns:
            Refined analysis with more specific recommendations
        """
        if not self.anthropic_client:
            return initial_analysis

        try:
            # Build follow-up prompt with investigation data
            prompt = f"""You previously analyzed this Kubernetes incident and suggested investigation steps.

**Original Incident:**
- Service: {alert.get('service')}
- Namespace: {alert.get('namespace')}
- Error: {alert.get('event', {}).get('reason')}
- Restart Count: {alert.get('pod_info', {}).get('restart_count', 0)}

**Your Initial Assessment:**
- Severity: {initial_analysis.get('severity')}
- Root Cause: {initial_analysis.get('root_cause')}

**Investigation Data Collected:**

"""

            if investigation_data.get('pod_logs'):
                logs_preview = investigation_data['pod_logs'][-2000:]  # Last 2000 chars
                prompt += f"""
**Pod Logs (last 50 lines):**
```
{logs_preview}
```
"""

            if investigation_data.get('pod_description'):
                desc = investigation_data['pod_description']
                prompt += f"""
**Resource Configuration:**
{json.dumps(desc, indent=2)}
"""

            if investigation_data.get('recent_events'):
                prompt += f"""
**Recent K8s Events:**
{json.dumps(investigation_data['recent_events'], indent=2)}
"""

            if investigation_data.get('external_secrets'):
                prompt += f"""
**ExternalSecret Resources (for AWS Secrets Manager sync):**
{json.dumps(investigation_data['external_secrets'], indent=2)}
"""

            if investigation_data.get('aws_secrets_verification'):
                prompt += f"""
**AWS Secrets Manager Verification:**
{json.dumps(investigation_data['aws_secrets_verification'], indent=2)}

IMPORTANT: This shows whether secrets actually exist in AWS Secrets Manager.
- If "exists_in_aws": false → Secret needs to be created in AWS Secrets Manager
- If "exists_in_aws": true → ExternalSecret sync issue is due to IAM permissions or SecretStore config
- If "exists_in_aws": "unknown" → Access denied, check IAM permissions for container's service account
"""

            if investigation_data.get('ecr_verification'):
                prompt += f"""
**ECR Image Verification:**
{json.dumps(investigation_data['ecr_verification'], indent=2)}

IMPORTANT: This shows whether container images actually exist in ECR.
- If "exists_in_ecr": false → Image tag doesn't exist, check if build/push succeeded
- If "exists_in_ecr": true → Image exists, pull issue is IAM permissions or network connectivity
- If error_code "RepositoryNotFoundException" → ECR repository doesn't exist
"""

            prompt += """

Based on this additional investigation data, provide a REFINED analysis:

1. **Updated Root Cause** - Now that you see logs/events/resources, what's the actual cause?
2. **Specific Remediation** - Concrete steps with exact values (e.g., "increase memory limit from X to Y")
3. **Severity Reassessment** - Does the data change severity assessment?
4. **Immediate Action** - What's the single most important action to take RIGHT NOW?

Respond in JSON format:
{
  "severity": "critical|high|medium|low",
  "root_cause_refined": "Specific cause based on logs/events",
  "remediation_steps": ["Specific step 1", "Specific step 2", ...],
  "immediate_action": "Single most critical action",
  "confidence": "How confident are you in this assessment (high/medium/low)",
  "teams_notification_needed": true|false
}"""

            logger.debug("Sending follow-up analysis request to Claude with investigation data...")

            # Call Claude API for refined analysis
            message = self.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                temperature=0.3,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # Parse response
            response_text = message.content[0].text

            # Extract JSON
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                refined = json.loads(response_text[json_start:json_end])

                # Log refined analysis
                logger.info(f"🔄 LLM refined analysis: severity={refined.get('severity')}, confidence={refined.get('confidence')}")
                logger.debug(f"🔍 Refined root cause: {refined.get('root_cause_refined')}")
                logger.debug(f"🚨 Immediate action: {refined.get('immediate_action')}")

                remediation = refined.get('remediation_steps', [])
                if remediation:
                    logger.debug(f"📋 Refined remediation steps ({len(remediation)}):")
                    for i, step in enumerate(remediation, 1):
                        logger.debug(f"  {i}. {step}")

                # Mark as refined for Teams notification
                refined['analysis_type'] = 'refined_with_investigation'
                refined['investigation_data_used'] = list(investigation_data.keys())

                return refined
            else:
                logger.warning("Could not parse refined analysis, using initial")
                return initial_analysis

        except Exception as e:
            logger.error(f"Error during refined analysis: {e}")
            return initial_analysis

    def determine_severity(self, alert: Dict) -> str:
        """
        Determine incident severity based on alert characteristics.

        Factors:
        - Pre-set severity from proactive checks (highest priority)
        - Error type (OOMKilled, CrashLoopBackOff, etc.)
        - Restart count
        - Service criticality (from config)
        - Impact scope (single pod vs multiple pods)
        """
        # If alert already has severity set (from proactive health check), use it
        if "severity" in alert and alert["severity"] in ["critical", "high", "medium", "low"]:
            logger.debug(f"Using pre-set severity from alert: {alert['severity']}")
            return alert["severity"]

        error_type = alert.get("error", "").lower()
        restart_count = alert.get("restart_count", 0)
        service_criticality = alert.get("criticality", "medium").lower()

        # Critical indicators - prioritize service criticality from config
        if service_criticality == "critical" and restart_count > self.CRITICAL_NAMESPACE_RESTART_THRESHOLD:
            return "critical"

        if "oomkilled" in error_type and restart_count > self.CRITICAL_OOM_RESTART_THRESHOLD:
            return "critical"

        # High severity indicators
        if "crashloop" in error_type or restart_count > self.HIGH_RESTART_THRESHOLD:
            return "high"

        # Medium severity
        if restart_count > self.MEDIUM_RESTART_THRESHOLD:
            return "medium"

        # Low severity
        return "low"

    async def handle_critical(self, alert: Dict) -> Dict:
        """
        Handle critical incidents with immediate Teams notification and analysis.

        GitOps Workflow:
        1. Send immediate Teams alert (quick awareness)
        2. Run full diagnosis
        3. Send diagnosis complete with recommendations
        4. Alert for human action (GitOps - no automated rollbacks)

        Args:
            alert: Incident alert data

        Returns:
            Triage result with diagnosis and notification status
        """
        steps = []

        # 1. Send Teams notification IMMEDIATELY (before diagnosis)
        if self.teams_notifier:
            try:
                logger.info("Sending immediate Teams alert for critical incident...")
                await self.teams_notifier.send_incident_alert(
                    incident=alert,
                    severity="critical",
                    diagnosis=None  # Quick alert before full diagnosis
                )
                steps.append("✅ Teams notification sent: Incident detected")
                logger.info("Teams alert sent successfully")
            except Exception as e:
                logger.error(f"Failed to send Teams alert: {e}")
                steps.append(f"⚠️ Teams notification failed: {e}")

        # 2. Run comprehensive diagnosis
        steps.append("Running diagnosis...")
        logger.info("Starting diagnosis for critical incident...")
        diagnosis = await self.run_diagnosis(alert)
        steps.append("Diagnosis complete")

        # 3. Send diagnosis complete notification with full recommendations
        if self.teams_notifier:
            try:
                logger.info("Sending diagnosis complete to Teams...")
                remediation = diagnosis.get('remediation_guidance', {})

                await self.teams_notifier.send_diagnosis_complete(
                    incident=alert,
                    diagnosis=diagnosis,
                    recommendations=remediation
                )
                steps.append("✅ Teams notification sent: Diagnosis complete with recommendations")
            except Exception as e:
                logger.error(f"Failed to send diagnosis notification: {e}")
                steps.append(f"⚠️ Diagnosis notification failed: {e}")

        # 4. Check if deployment action needed (GitOps)
        needs_deployment_action = self.needs_rollback(diagnosis)

        if needs_deployment_action or diagnosis.get("requires_human"):
            reason = "Deployment rollback recommended - GitOps action required" if needs_deployment_action else "Manual investigation required"

            steps.append(f"Action required: {reason}")

            # Send escalation alert
            if self.teams_notifier:
                try:
                    logger.info(f"Sending escalation alert: {reason}")
                    await self.teams_notifier.send_escalation_alert(
                        incident=alert,
                        reason=reason,
                        diagnosis=diagnosis
                    )
                    steps.append(f"✅ Teams notification sent: {reason}")
                except Exception as e:
                    logger.error(f"Failed to send escalation alert: {e}")
                    steps.append(f"⚠️ Escalation notification failed: {e}")

        return {
            "severity": "critical",
            "diagnosis": diagnosis,
            "actions_taken": steps,
            "status": "handled",
            "notifications_sent": self.teams_notifier is not None,
            "requires_human_action": True  # Always true for GitOps
        }

    async def handle_high(self, alert: Dict) -> Dict:
        """
        Handle high severity incidents with automated diagnosis and Teams notifications.

        Workflow (similar to critical but for high severity):
        1. Send immediate Teams alert (quick awareness)
        2. Run full diagnosis (with LLM investigation)
        3. Send diagnosis complete with recommendations
        """
        steps = []

        # Check if LLM recommends Teams notification
        llm_analysis = alert.get('llm_analysis', {})
        teams_needed = llm_analysis.get('teams_notification_needed', False)

        # 1. Send immediate Teams notification if LLM recommends
        if self.teams_notifier and teams_needed:
            try:
                logger.info("Sending immediate Teams alert for high severity incident...")
                await self.teams_notifier.send_incident_alert(
                    incident=alert,
                    severity="high",
                    diagnosis=None  # Quick alert before full diagnosis
                )
                steps.append("✅ Teams notification sent: Incident detected")
            except Exception as e:
                logger.error(f"Failed to send Teams alert: {e}")
                steps.append(f"⚠️ Teams notification failed: {e}")

        # 2. Run comprehensive diagnosis (includes LLM refined analysis)
        logger.info("Starting diagnosis for high severity incident...")
        diagnosis = await self.run_diagnosis(alert)
        steps.append("Diagnosis complete")

        # 3. Send diagnosis complete notification with full recommendations
        if self.teams_notifier and teams_needed:
            try:
                logger.info("Sending diagnosis complete to Teams...")
                remediation = diagnosis.get('remediation_guidance', {})

                await self.teams_notifier.send_diagnosis_complete(
                    incident=alert,
                    diagnosis=diagnosis,
                    recommendations=remediation
                )
                steps.append("✅ Teams notification sent: Diagnosis complete with recommendations")
            except Exception as e:
                logger.error(f"Failed to send diagnosis notification: {e}")
                steps.append(f"⚠️ Diagnosis notification failed: {e}")

        return {
            "severity": "high",
            "diagnosis": diagnosis,
            "actions_taken": steps,
            "status": "monitored" if not teams_needed else "handled"
        }

    async def handle_medium(self, alert: Dict) -> Dict:
        """
        Handle medium severity incidents with diagnosis and conditional Teams notification.

        Runs diagnosis which may escalate severity via refined LLM analysis.
        Sends Teams notification if refined analysis recommends it.
        """
        steps = []

        # Run diagnosis (includes LLM refined analysis that may escalate)
        diagnosis = await self.run_diagnosis(alert)
        steps.append("Diagnosis complete")

        # Check if refined LLM analysis escalated or recommends notification
        llm_analysis = alert.get('llm_analysis', {})
        refined_severity = llm_analysis.get('severity', 'medium')
        teams_needed = llm_analysis.get('teams_notification_needed', False)

        # If escalated to high/critical OR LLM recommends notification, send Teams alert
        if self.teams_notifier and (refined_severity in ['high', 'critical'] or teams_needed):
            try:
                logger.info(f"Sending Teams notification (refined: {refined_severity}, LLM recommended: {teams_needed})")
                await self.teams_notifier.send_incident_alert(
                    incident=alert,
                    severity=refined_severity,
                    diagnosis=diagnosis
                )
                steps.append(f"✅ Teams notification sent (escalated to {refined_severity})")
            except Exception as e:
                logger.error(f"Failed to send Teams notification: {e}")
                steps.append(f"⚠️ Teams notification failed: {e}")

        return {
            "severity": refined_severity,  # Use refined severity
            "diagnosis": diagnosis,
            "actions_taken": steps,
            "status": "monitored" if refined_severity == 'medium' else "escalated"
        }

    async def handle_low(self, alert: Dict) -> Dict:
        """
        Handle low severity incidents with documentation only.

        Note: No diagnosis run, no Teams notifications.
        Incidents are archived for learning and pattern analysis.
        Used for informational events and normal operational variations.
        """
        return {
            "severity": "low",
            "actions_taken": ["Documented for learning"],
            "status": "archived"
        }

    async def run_diagnosis(self, alert: Dict) -> Dict:
        """
        Run comprehensive diagnosis on incident.

        Checks:
        - Pod logs and events (via K8s MCP tools)
        - Deployment history (via GitHub MCP tools)
        - Remediation playbooks and recommendations

        Args:
            alert: Incident alert with service, error, namespace info

        Returns:
            Diagnostic report with findings and correlation data
        """
        service = alert.get('service', 'unknown')
        namespace = alert.get('namespace', 'default')
        error_type = alert.get('error', 'unknown')

        logger.info(f"Running diagnosis for {service} ({error_type})")

        diagnosis = {
            "service": service,
            "namespace": namespace,
            "error_type": error_type,
            "timestamp": datetime.now().isoformat()
        }

        # 1. K8s analysis (basic info for now - SDK tools not callable in daemon mode)
        diagnosis["k8s_analysis"] = {
            "deployment": service,
            "namespace": namespace,
            "note": "Direct K8s API calls available - pod info already in alert"
        }

        # 2. Get deployment correlation using GitHub API
        try:
            # Get recent deployments from GitHub
            deployments = await self.github_tracker.get_recent_deployments(hours=1, service=service)

            if deployments:
                logger.info(f"Found {len(deployments)} recent deployments for correlation")

                # Correlate with incident time
                incident_time = alert.get('timestamp', datetime.now().isoformat())
                best_correlation = None
                best_confidence = 0.0

                for deployment in deployments:
                    correlation = self.github_tracker.correlation_algorithm(
                        k8s_event_time=incident_time,
                        github_deploy_time=deployment['created_at']
                    )

                    if correlation['confidence'] > best_confidence:
                        best_confidence = correlation['confidence']
                        best_correlation = {
                            **correlation,
                            'deployment_id': deployment['id'],
                            'deployment_sha': deployment['head_sha'],
                            'deployment_branch': deployment['head_branch']
                        }

                diagnosis["deployment_correlation"] = best_correlation or {
                    "confidence": 0.0,
                    "message": "No high-confidence correlation found"
                }
            else:
                diagnosis["deployment_correlation"] = {
                    "confidence": 0.0,
                    "message": "No recent deployments found"
                }

        except Exception as e:
            logger.error(f"Event correlation failed: {e}")
            diagnosis["deployment_correlation"] = {"error": str(e), "status": "failed"}

        # 3. Get remediation suggestions (basic playbook reference)
        incident_type = error_type.lower().replace(' ', '_')
        diagnosis["remediation_guidance"] = {
            "incident_type": incident_type,
            "severity": self.determine_severity(alert),
            "note": "Remediation playbooks available in k8s_analyzer.py",
            "recommended_actions": self._get_basic_remediation(incident_type)
        }

        # 5. Determine if human intervention needed
        restart_count = alert.get('restart_count', 0)
        severity = self.determine_severity(alert)

        diagnosis["requires_human"] = (
            severity == "critical" and restart_count > self.HUMAN_INTERVENTION_RESTART_THRESHOLD
        ) or (
            error_type.lower() not in ['oomkilled', 'crashloopbackoff', 'imagepullbackoff']
        )

        return diagnosis

    def _get_basic_remediation(self, incident_type: str) -> List[str]:
        """
        Get basic remediation steps for common incident types.

        Args:
            incident_type: Type of incident

        Returns:
            List of remediation step strings
        """
        playbooks = {
            "oomkilled": [
                "Check memory limits in deployment",
                "Review memory usage trends",
                "Consider increasing memory limits",
                "Check for memory leaks in recent code changes"
            ],
            "crashloopbackoff": [
                "Check pod logs for errors",
                "Verify environment variables and secrets",
                "Check liveness/readiness probe configuration",
                "Review recent deployment changes"
            ],
            "imagepullbackoff": [
                "Verify image tag exists in ECR",
                "Check image pull secrets",
                "Verify ECR registry connectivity"
            ],
            "nocompatibleinstancetypes": [
                "Review NodePool instance type requirements",
                "Check node taints and tolerations",
                "Verify instance type availability in region"
            ],
            "podstuckpending": [
                "Check node resources and capacity",
                "Review pod resource requests",
                "Check for scheduling constraints",
                "Verify PodDisruptionBudgets"
            ],
            "unhealthy": [
                "Check health check endpoint responses",
                "Review pod logs for startup errors",
                "Verify readiness probe configuration"
            ]
        }

        return playbooks.get(incident_type, ["Manual investigation required"])

    def needs_rollback(self, diagnosis: Dict) -> bool:
        """
        Determine if rollback is needed based on diagnosis.

        Uses the multi-factor rollback scoring from suggest_fix tool guidance.

        Criteria:
        - Issue started after recent deployment
        - High confidence deployment correlation (>= 0.8)
        - Severity is critical or high
        - Rollback score >= 0.8 threshold

        Args:
            diagnosis: Diagnostic report from run_diagnosis()

        Returns:
            True if rollback is recommended
        """
        # Extract remediation guidance
        remediation = diagnosis.get("remediation_guidance", {})
        if not remediation:
            logger.warning("No remediation guidance in diagnosis")
            return False

        # Get rollback requirement calculation
        remediation_content = remediation.get("content", [{}])[0]
        remediation_data = {}

        try:
            import json
            text = remediation_content.get("text", "{}")
            remediation_data = json.loads(text)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse remediation data: {e}")
            return False

        rollback_info = remediation_data.get("requires_rollback", {})

        if isinstance(rollback_info, dict):
            recommendation = rollback_info.get("recommendation", "MONITOR")
            confidence = rollback_info.get("confidence", 0.0)

            logger.info(f"Rollback recommendation: {recommendation} (confidence: {confidence})")

            return recommendation == "ROLLBACK" and confidence >= self.ROLLBACK_CONFIDENCE_THRESHOLD
        else:
            # Legacy boolean format
            return rollback_info if isinstance(rollback_info, bool) else False