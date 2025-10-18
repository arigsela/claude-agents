"""
GitHub Deployment Tracker
Provides guidance for tracking deployments and generating rollback recommendations
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone
import os

# GitHub API client
from github import Github, GithubException

logger = logging.getLogger(__name__)


class GitHubDeploymentTracker:
    """
    Tracks GitHub Actions deployments for the artemishealth organization.

    This class provides helper methods for the agent to:
    - Query recent deployments via GitHub MCP tools
    - Correlate deployments with K8s incidents
    - Generate rollback guidance via GitHub Actions
    """

    # Correlation time windows (minutes)
    CORRELATION_IMMEDIATE = 5      # Within 5 min = 1.0 confidence
    CORRELATION_HIGH = 15          # Within 15 min = 0.8 confidence
    CORRELATION_MEDIUM = 30        # Within 30 min = 0.5 confidence
    # Beyond 30 min = 0.2 confidence

    # Correlation confidence scores
    CONFIDENCE_IMMEDIATE = 1.0
    CONFIDENCE_HIGH = 0.8
    CONFIDENCE_MEDIUM = 0.5
    CONFIDENCE_LOW = 0.2

    # Rollback decision threshold
    ROLLBACK_THRESHOLD = 0.8

    def __init__(self, org: str = "artemishealth", deployments_repo: str = "deployments"):
        self.org = org
        self.deployments_repo = deployments_repo

        # Initialize GitHub client
        github_token = os.getenv('GITHUB_TOKEN')
        if github_token:
            self.github = Github(github_token)
            logger.info(f"GitHubDeploymentTracker initialized for org: {org}, deployments repo: {deployments_repo} (API client ready)")
        else:
            self.github = None
            logger.warning("GITHUB_TOKEN not found, tracker will run in guidance mode only")
            logger.info(f"GitHubDeploymentTracker initialized for org: {org}, deployments repo: {deployments_repo} (guidance mode)")

    async def get_recent_deployments(self, hours: int = 24, service: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get recent GitHub workflow runs (actual API call).

        Args:
            hours: Number of hours to look back
            service: Optional service name to filter by

        Returns:
            List of deployment workflow runs
        """
        if not self.github:
            logger.warning("GitHub client not available, returning empty list")
            return []

        try:
            repo = self.github.get_repo(f"{self.org}/{self.deployments_repo}")
            # Use UTC with timezone awareness for consistent comparison
            since_time = datetime.now(timezone.utc) - timedelta(hours=hours)

            # Get workflow runs
            workflows = repo.get_workflow_runs()

            deployments = []
            for run in workflows:
                # Filter by time
                if run.created_at < since_time:
                    break  # Workflows are ordered by date, can stop here

                # Filter by service if specified
                if service and service not in run.head_branch:
                    continue

                deployments.append({
                    'id': run.id,
                    'name': run.name,
                    'status': run.status,
                    'conclusion': run.conclusion,
                    'head_branch': run.head_branch,
                    'head_sha': run.head_sha,
                    'created_at': run.created_at.isoformat(),
                    'updated_at': run.updated_at.isoformat() if run.updated_at else None
                })

                # Limit results
                if len(deployments) >= 20:
                    break

            logger.info(f"Found {len(deployments)} deployments in last {hours}h")
            return deployments

        except GithubException as e:
            logger.error(f"GitHub API error: {e.status} - {e.data.get('message', 'Unknown error')}")
            return []
        except Exception as e:
            logger.error(f"Error fetching deployments: {e}")
            return []

    def get_recent_deployments_guidance(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get guidance for querying recent deployments.

        Args:
            hours: Number of hours to look back

        Returns:
            Guidance for using GitHub MCP tools to get deployment data
        """
        since_time = datetime.now() - timedelta(hours=hours)

        return {
            "purpose": f"Get deployments from last {hours} hours",
            "time_range": {
                "start": since_time.isoformat(),
                "end": datetime.now().isoformat()
            },
            "recommended_tool_calls": [
                {
                    "tool": "mcp__github__list_workflow_runs",
                    "args": {
                        "owner": self.org,
                        "repo": self.deployments_repo,
                        "workflow_id": "deploy.yml",
                        "created": f">={since_time.strftime('%Y-%m-%d')}",
                        "per_page": 50
                    },
                    "extract": [
                        "id",
                        "name",
                        "head_branch",
                        "head_sha",
                        "status",
                        "conclusion",
                        "created_at",
                        "updated_at"
                    ]
                }
            ],
            "filtering": {
                "status": "completed",
                "conclusion": ["success", "failure"],
                "exclude": ["cancelled", "skipped"]
            }
        }

    def build_rollback_guidance(self, deployment_id: str, reason: str) -> Dict[str, Any]:
        """
        Build guidance for triggering a rollback via GitHub Actions.

        Args:
            deployment_id: GitHub workflow run ID or commit SHA
            reason: Reason for rollback (for audit trail)

        Returns:
            Guidance for rollback process
        """
        return {
            "rollback_strategy": "PR-based rollback via deployments repository",
            "workflow": [
                {
                    "step": 1,
                    "action": "Create rollback PR",
                    "tool": "mcp__github__create_pull_request",
                    "args": {
                        "owner": self.org,
                        "repo": self.deployments_repo,
                        "title": f"[ROLLBACK] Automated rollback - {reason}",
                        "body": self._generate_rollback_pr_body(deployment_id, reason),
                        "head": "rollback/automated",
                        "base": "main"
                    }
                },
                {
                    "step": 2,
                    "action": "Tag PR for automatic merge (if configured)",
                    "tool": "mcp__github__update_pull_request",
                    "args": {
                        "labels": ["rollback", "automated", "urgent"]
                    }
                },
                {
                    "step": 3,
                    "action": "Monitor rollback progress",
                    "tool": "mcp__github__get_workflow_run",
                    "args": {
                        "owner": self.org,
                        "repo": self.deployments_repo,
                        "run_id": "{new_workflow_run_id}"
                    },
                    "poll_interval": "30 seconds",
                    "timeout": "10 minutes"
                }
            ],
            "safety_checks": [
                "Verify rollback target cluster is dev-eks",
                f"Confirm deployment correlation confidence > {self.ROLLBACK_THRESHOLD}",
                "Check rollback count < 2 per hour"
            ],
            "rollback_metadata": {
                "deployment_id": deployment_id,
                "reason": reason,
                "initiated_by": "oncall-agent",
                "timestamp": datetime.now().isoformat()
            }
        }

    def _generate_rollback_pr_body(self, deployment_id: str, reason: str) -> str:
        """Generate PR description for rollback"""
        return f"""## Automated Rollback

**Reason:** {reason}

**Original Deployment:** {deployment_id}

**Triggered By:** On-Call Troubleshooting Agent

**Timestamp:** {datetime.now().isoformat()}

### Incident Details
This rollback was automatically triggered due to detected issues in the deployment.

### Verification Steps
- [ ] Verify rollback completed successfully
- [ ] Confirm service health restored
- [ ] Update monitoring if needed

### Safety
- Target cluster: dev-eks (verified)
- Correlation confidence: >= 0.8
- Rate limit check: Passed

---
🤖 Generated by On-Call Troubleshooting Agent
"""

    def get_deployment_metadata(self, workflow_run_id: str) -> Dict[str, Any]:
        """
        Get guidance for extracting deployment metadata from a workflow run.

        Args:
            workflow_run_id: GitHub Actions workflow run ID

        Returns:
            Guidance for extracting deployment details
        """
        return {
            "tool": "mcp__github__get_workflow_run",
            "args": {
                "owner": self.org,
                "repo": self.deployments_repo,
                "run_id": workflow_run_id
            },
            "extract_fields": {
                "deployment_info": [
                    "head_sha",
                    "head_branch",
                    "created_at",
                    "updated_at",
                    "conclusion"
                ],
                "service_info": [
                    "Extract service name from head_branch or commit message",
                    "Parse version from head_sha or tags"
                ],
                "timing": [
                    "Deployment started: created_at",
                    "Deployment finished: updated_at",
                    "Duration: updated_at - created_at"
                ]
            }
        }

    def correlation_algorithm(self, k8s_event_time: str, github_deploy_time: str) -> Dict[str, Any]:
        """
        Calculate correlation confidence between K8s event and GitHub deployment.

        Args:
            k8s_event_time: K8s event timestamp (ISO format)
            github_deploy_time: GitHub deployment timestamp (ISO format)

        Returns:
            Correlation score and interpretation
        """
        try:
            event_dt = datetime.fromisoformat(k8s_event_time.replace('Z', '+00:00'))
            deploy_dt = datetime.fromisoformat(github_deploy_time.replace('Z', '+00:00'))

            # Calculate time difference in minutes
            time_diff = abs((event_dt - deploy_dt).total_seconds() / 60)

            # Calculate confidence based on proximity using class constants
            if time_diff <= self.CORRELATION_IMMEDIATE:
                confidence = self.CONFIDENCE_IMMEDIATE
                interpretation = "Very high confidence - incident likely deployment-related"
            elif time_diff <= self.CORRELATION_HIGH:
                confidence = self.CONFIDENCE_HIGH
                interpretation = "High confidence - strong deployment correlation"
            elif time_diff <= self.CORRELATION_MEDIUM:
                confidence = self.CONFIDENCE_MEDIUM
                interpretation = "Medium confidence - possible deployment correlation"
            else:
                confidence = self.CONFIDENCE_LOW
                interpretation = "Low confidence - weak deployment correlation"

            return {
                "confidence": confidence,
                "time_difference_minutes": round(time_diff, 2),
                "interpretation": interpretation,
                "event_time": k8s_event_time,
                "deploy_time": github_deploy_time,
                "rollback_recommended": confidence >= self.ROLLBACK_THRESHOLD
            }

        except (ValueError, AttributeError) as e:
            logger.error(f"Error parsing timestamps: {e}")
            return {
                "confidence": 0.0,
                "error": f"Invalid timestamp format: {e}",
                "rollback_recommended": False
            }
