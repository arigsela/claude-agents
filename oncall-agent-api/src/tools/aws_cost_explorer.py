"""
AWS Cost Explorer Integration
Provides cost anomaly detection and analysis for AWS resources

This module integrates with AWS Cost Explorer API to provide:
- Cost anomaly detection using AWS Cost Anomaly Detection service
- Daily/weekly/monthly cost trends and analysis
- Service-level cost breakdown
- Budget alerts and forecasting
- Cost optimization recommendations
"""

import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


class AWSCostExplorer:
    """
    AWS Cost Explorer integration for cost anomaly detection and analysis.

    This class provides methods for:
    - Detecting cost anomalies using AWS Cost Anomaly Detection
    - Analyzing cost trends over time
    - Breaking down costs by service, account, or other dimensions
    - Forecasting future costs
    - Identifying cost optimization opportunities

    Requires AWS credentials with the following IAM permissions:
    - ce:GetAnomalies
    - ce:GetCostAndUsage
    - ce:GetCostForecast
    - ce:GetDimensionValues
    """

    # Default AWS region (Cost Explorer is global but requires a region)
    DEFAULT_REGION = "us-east-1"

    # Cost Explorer API limits
    MAX_RESULTS = 100
    MAX_DAYS_BACK = 365

    def __init__(self, region: str | None = None):
        """
        Initialize AWS Cost Explorer client.

        Args:
            region: AWS region (defaults to AWS_REGION env var or us-east-1)
                   Note: Cost Explorer is a global service but requires region
        """
        self.region = region or os.getenv("AWS_REGION", self.DEFAULT_REGION)
        self._ce_client = None

        # Check if boto3 is available
        try:
            import boto3  # noqa: F401

            self.boto3_available = True
            logger.info(f"AWSCostExplorer initialized for region: {self.region} (boto3 available)")
        except ImportError:
            self.boto3_available = False
            logger.warning(
                "AWSCostExplorer initialized but boto3 not available - operations will fail gracefully"
            )

    @property
    def ce_client(self):
        """Lazy initialization of Cost Explorer client."""
        if not self.boto3_available:
            return None

        if self._ce_client is None:
            import boto3

            self._ce_client = boto3.client("ce", region_name=self.region)
            logger.debug("Cost Explorer client initialized")

        return self._ce_client

    def _decimal_to_float(self, obj: Any) -> Any:
        """
        Recursively convert Decimal objects to float for JSON serialization.

        Args:
            obj: Object that may contain Decimal values

        Returns:
            Object with Decimals converted to floats
        """
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._decimal_to_float(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._decimal_to_float(item) for item in obj]
        return obj

    async def get_cost_anomalies(
        self, days_back: int = 7, min_impact: float = 10.0, max_results: int = 50
    ) -> list[dict[str, Any]]:
        """
        Get cost anomalies detected by AWS Cost Anomaly Detection.

        This method retrieves anomalies from AWS Cost Anomaly Detection service,
        which uses machine learning to identify unusual spending patterns.

        Args:
            days_back: Number of days to look back (1-90)
            min_impact: Minimum dollar impact to include (USD)
            max_results: Maximum number of anomalies to return

        Returns:
            List of anomaly details with impact, service, and root cause

        Example:
            [
                {
                    "anomaly_id": "abc-123-def",
                    "service": "Amazon EC2",
                    "impact_amount": 125.50,
                    "impact_percentage": 45.2,
                    "start_date": "2025-01-15",
                    "end_date": "2025-01-16",
                    "root_cause": "Increased instance usage in us-east-1",
                    "dimension_value": "us-east-1"
                }
            ]
        """
        if not self.ce_client:
            logger.error("Cost Explorer client not available")
            return []

        try:
            # Calculate date range
            end_date = datetime.utcnow().date()
            start_date = end_date - timedelta(days=min(days_back, 90))

            logger.info(f"Fetching cost anomalies from {start_date} to {end_date}")

            # Call AWS Cost Anomaly Detection API
            response = self.ce_client.get_anomalies(
                DateInterval={
                    "StartDate": start_date.strftime("%Y-%m-%d"),
                    "EndDate": end_date.strftime("%Y-%m-%d"),
                },
                MaxResults=min(max_results, self.MAX_RESULTS),
            )

            anomalies = []

            for anomaly in response.get("Anomalies", []):
                # Extract impact information
                impact = anomaly.get("Impact", {})
                total_impact = float(impact.get("TotalImpact", 0))

                # Filter by minimum impact
                if total_impact < min_impact:
                    continue

                # Extract root causes
                root_causes = anomaly.get("RootCauses", [])
                root_cause_text = None
                dimension_value = None

                if root_causes:
                    first_cause = root_causes[0]
                    service = first_cause.get("Service", "Unknown")
                    dimension_value = first_cause.get("LinkedAccount") or first_cause.get("Region")
                    root_cause_text = f"Increased usage in {service}"
                    if dimension_value:
                        root_cause_text += f" ({dimension_value})"

                anomalies.append(
                    {
                        "anomaly_id": anomaly.get("AnomalyId", "unknown"),
                        "service": (
                            root_causes[0].get("Service", "Unknown") if root_causes else "Unknown"
                        ),
                        "impact_amount": total_impact,
                        "impact_percentage": float(impact.get("MaxImpact", 0)),
                        "start_date": anomaly.get("AnomalyStartDate", ""),
                        "end_date": anomaly.get("AnomalyEndDate", ""),
                        "root_cause": root_cause_text,
                        "dimension_value": dimension_value,
                        "feedback_status": anomaly.get("Feedback", "NONE"),
                    }
                )

            logger.info(
                f"Found {len(anomalies)} cost anomalies (filtered by min_impact=${min_impact})"
            )
            return anomalies

        except Exception as e:
            logger.error(f"Failed to get cost anomalies: {e}", exc_info=True)
            return []

    async def get_daily_costs(
        self, days_back: int = 30, group_by: str = "SERVICE", granularity: str = "DAILY"
    ) -> dict[str, Any]:
        """
        Get daily cost breakdown by service or other dimension.

        Args:
            days_back: Number of days to analyze (1-365)
            group_by: Dimension to group by (SERVICE, LINKED_ACCOUNT, REGION, etc.)
            granularity: Time granularity (DAILY, MONTHLY, HOURLY)

        Returns:
            Daily cost data with trends and breakdown

        Example:
            {
                "total_cost": 1250.75,
                "start_date": "2024-12-15",
                "end_date": "2025-01-15",
                "daily_breakdown": [
                    {
                        "date": "2025-01-15",
                        "total": 42.50,
                        "services": {
                            "Amazon EC2": 25.00,
                            "Amazon RDS": 17.50
                        }
                    }
                ],
                "top_services": [
                    {"service": "Amazon EC2", "cost": 750.00},
                    {"service": "Amazon RDS", "cost": 500.75}
                ]
            }
        """
        if not self.ce_client:
            logger.error("Cost Explorer client not available")
            return {}

        try:
            # Calculate date range
            end_date = datetime.utcnow().date()
            start_date = end_date - timedelta(days=min(days_back, self.MAX_DAYS_BACK))

            logger.info(
                f"Fetching daily costs from {start_date} to {end_date}, grouped by {group_by}"
            )

            # Call Cost Explorer API
            response = self.ce_client.get_cost_and_usage(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d"),
                },
                Granularity=granularity,
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": group_by}],
            )

            # Process results
            daily_breakdown = []
            service_totals = {}
            total_cost = 0.0

            for result in response.get("ResultsByTime", []):
                date = result.get("TimePeriod", {}).get("Start", "")
                daily_total = 0.0
                services = {}

                for group in result.get("Groups", []):
                    service_name = group.get("Keys", ["Unknown"])[0]
                    cost = float(group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0))

                    services[service_name] = cost
                    daily_total += cost

                    # Accumulate service totals
                    service_totals[service_name] = service_totals.get(service_name, 0.0) + cost

                daily_breakdown.append(
                    {
                        "date": date,
                        "total": round(daily_total, 2),
                        "services": {k: round(v, 2) for k, v in services.items()},
                    }
                )

                total_cost += daily_total

            # Sort services by total cost
            top_services = [
                {"service": service, "cost": round(cost, 2)}
                for service, cost in sorted(
                    service_totals.items(), key=lambda x: x[1], reverse=True
                )
            ]

            result = {
                "total_cost": round(total_cost, 2),
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "daily_breakdown": daily_breakdown,
                "top_services": top_services[:10],  # Top 10 services
                "granularity": granularity,
                "group_by": group_by,
            }

            logger.info(
                f"Retrieved {len(daily_breakdown)} days of cost data, total: ${total_cost:.2f}"
            )
            return result

        except Exception as e:
            logger.error(f"Failed to get daily costs: {e}", exc_info=True)
            return {}

    async def get_ec2_costs_by_tags(
        self,
        days_back: int = 7,
        tag_keys: list[str] | None = None,
        service_filter: str = "Amazon Elastic Compute Cloud - Compute",
        max_tag_values: int = 10,
    ) -> dict[str, Any]:
        """
        Get EC2 costs broken down by specific tags (e.g., node groups, Karpenter pools, Databricks workers).

        Args:
            days_back: Number of days to analyze (1-365, default: 7)
            tag_keys: List of tag keys to group by (default: ['karpenter.sh/nodepool', 'eks:nodegroup-name', 'Refresh-Id'])
                     - karpenter.sh/nodepool: Karpenter node pools
                     - eks:nodegroup-name: EKS managed node groups
                     - Refresh-Id: Databricks worker instances
            service_filter: AWS service to filter (default: EC2 compute)
            max_tag_values: Maximum number of tag values to return per tag (default: 10)

        Returns:
            EC2 cost data grouped by tags with breakdown

        Example:
            {
                "total_ec2_cost": 1250.75,
                "start_date": "2024-12-20",
                "end_date": "2025-01-05",
                "tag_breakdown": {
                    "karpenter.sh/nodepool": {
                        "default": 450.25,
                        "spot-pool": 320.50,
                        "on-demand-pool": 180.00
                    },
                    "eks:nodegroup-name": {
                        "ng-1": 200.00,
                        "ng-2": 100.00
                    },
                    "Refresh-Id": {
                        "job-12345": 150.00,
                        "job-67890": 100.00
                    }
                },
                "top_cost_sources": [
                    {"tag": "karpenter.sh/nodepool", "value": "default", "cost": 450.25},
                    {"tag": "karpenter.sh/nodepool", "value": "spot-pool", "cost": 320.50}
                ],
                "daily_breakdown": [...]
            }
        """
        if not self.ce_client:
            logger.error("Cost Explorer client not available")
            return {}

        # Default to infrastructure tags: Kubernetes + Databricks
        if tag_keys is None:
            tag_keys = ["karpenter.sh/nodepool", "eks:nodegroup-name", "Refresh-Id"]

        try:
            # Calculate date range
            end_date = datetime.utcnow().date()
            start_date = end_date - timedelta(days=min(days_back, self.MAX_DAYS_BACK))

            logger.info(f"Fetching EC2 costs by tags {tag_keys} from {start_date} to {end_date}")

            # We'll make separate calls for each tag key since Cost Explorer
            # doesn't support multiple tag groupings in a single call
            tag_breakdown = {}
            all_tag_costs = []
            total_ec2_cost = 0.0

            for tag_key in tag_keys:
                try:
                    logger.debug(f"Querying costs for tag: {tag_key}")

                    # Call Cost Explorer API with tag grouping
                    response = self.ce_client.get_cost_and_usage(
                        TimePeriod={
                            "Start": start_date.strftime("%Y-%m-%d"),
                            "End": end_date.strftime("%Y-%m-%d"),
                        },
                        Granularity="DAILY",
                        Metrics=["UnblendedCost"],
                        Filter={"Dimensions": {"Key": "SERVICE", "Values": [service_filter]}},
                        GroupBy=[{"Type": "TAG", "Key": tag_key}],
                    )

                    # Process results for this tag
                    tag_totals = {}
                    daily_data = []

                    for result in response.get("ResultsByTime", []):
                        date = result.get("TimePeriod", {}).get("Start", "")
                        daily_tag_costs = {}

                        for group in result.get("Groups", []):
                            # Tag value is in Keys[0], format: "tag_key$tag_value"
                            tag_full = group.get("Keys", [""])[0]

                            # Extract tag value (after the $ separator)
                            if "$" in tag_full:
                                tag_value = tag_full.split("$", 1)[1]
                            else:
                                tag_value = tag_full or "untagged"

                            cost = float(
                                group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0)
                            )

                            # Skip zero costs
                            if cost == 0:
                                continue

                            daily_tag_costs[tag_value] = cost
                            tag_totals[tag_value] = tag_totals.get(tag_value, 0.0) + cost

                        if daily_tag_costs:
                            daily_data.append(
                                {
                                    "date": date,
                                    "costs": {k: round(v, 2) for k, v in daily_tag_costs.items()},
                                }
                            )

                    # Store breakdown for this tag (limited to top N values)
                    if tag_totals:
                        sorted_tag_totals = sorted(
                            tag_totals.items(), key=lambda x: x[1], reverse=True
                        )
                        tag_breakdown[tag_key] = {
                            k: round(v, 2) for k, v in sorted_tag_totals[:max_tag_values]
                        }

                        # Add to all_tag_costs for top sources (limited)
                        for tag_value, cost in sorted_tag_totals[:max_tag_values]:
                            all_tag_costs.append(
                                {"tag": tag_key, "value": tag_value, "cost": round(cost, 2)}
                            )

                        # Skip daily breakdown to reduce response size
                        # daily_breakdown_by_tag[tag_key] = daily_data

                        # Add to total (note: this may double-count if resources have multiple tags)
                        tag_total = sum(tag_totals.values())
                        logger.info(
                            f"Tag {tag_key}: ${tag_total:.2f} across {len(tag_totals)} values"
                        )

                except Exception as tag_error:
                    logger.warning(f"Failed to get costs for tag {tag_key}: {tag_error}")
                    continue

            # Calculate total EC2 cost (without tag filtering to get accurate total)
            try:
                total_response = self.ce_client.get_cost_and_usage(
                    TimePeriod={
                        "Start": start_date.strftime("%Y-%m-%d"),
                        "End": end_date.strftime("%Y-%m-%d"),
                    },
                    Granularity="DAILY",
                    Metrics=["UnblendedCost"],
                    Filter={"Dimensions": {"Key": "SERVICE", "Values": [service_filter]}},
                )

                for result in total_response.get("ResultsByTime", []):
                    cost = float(result.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
                    total_ec2_cost += cost

            except Exception as total_error:
                logger.warning(f"Failed to get total EC2 cost: {total_error}")
                # Fallback: use sum of tag costs (may be inaccurate)
                total_ec2_cost = sum(item["cost"] for item in all_tag_costs)

            # Sort top cost sources (already limited per tag, take top overall)
            top_cost_sources = sorted(all_tag_costs, key=lambda x: x["cost"], reverse=True)[:15]

            result = {
                "total_ec2_cost": round(total_ec2_cost, 2),
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
                "tag_breakdown": tag_breakdown,
                "top_cost_sources": top_cost_sources,
                "service_filter": service_filter,
                "tag_keys_analyzed": tag_keys,
                "note": f"Showing top {max_tag_values} values per tag. Use days_back parameter to adjust date range.",
            }

            logger.info(
                f"Retrieved EC2 costs by tags: ${total_ec2_cost:.2f} total, {len(top_cost_sources)} tag values"
            )
            return result

        except Exception as e:
            logger.error(f"Failed to get EC2 costs by tags: {e}", exc_info=True)
            return {}
