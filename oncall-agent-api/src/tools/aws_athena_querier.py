"""
AWS Athena Querier for CUR Data Analysis

Provides cost anomaly detection and analysis by querying AWS Cost and Usage Report (CUR)
data stored in S3 via Athena. Focuses on three key areas:
- Compute (EC2/Lambda)
- EKS/Containers (with Split Cost Allocation)
- Networking (NAT Gateway/Data Transfer)

This module leverages the CUR infrastructure deployed via:
- DEVOPS-7593 (Athena module)
- DEVOPS-7594 (CUR module)
- DEVOPS-7599 (QuickSight dashboards)

Query patterns adapted from AWS Well-Architected Cost Optimization Labs:
https://www.wellarchitectedlabs.com/cost-optimization/cur_queries/
"""

import contextlib
import logging
import os
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class AWSAthenaQuerier:
    """
    Query CUR data via Athena for cost analysis and anomaly detection.

    This class provides methods for:
    - Detecting cost anomalies (24h vs 7-day baseline)
    - Analyzing compute costs (EC2, Lambda)
    - Analyzing EKS/container costs (with Split Cost Allocation data)
    - Analyzing networking costs (NAT Gateway, Data Transfer)
    - Identifying idle resources

    Requires AWS credentials with the following IAM permissions:
    - athena:StartQueryExecution
    - athena:GetQueryExecution
    - athena:GetQueryResults
    - s3:GetBucketLocation (on output bucket)
    - s3:GetObject (on output bucket)
    - s3:PutObject (on output bucket)
    - s3:ListBucket (on CUR data bucket)
    - s3:GetObject (on CUR data bucket)
    - glue:GetTable (for CUR catalog)
    - glue:GetPartitions (for CUR catalog)
    """

    # Default configuration
    DEFAULT_REGION = "us-east-1"
    DEFAULT_DATABASE = "athenacurcfn_c_u_r_athena"
    DEFAULT_TABLE = "c_u_r_athena"
    DEFAULT_WORKGROUP = "primary"

    # Query timeout settings
    MAX_QUERY_TIMEOUT_SECONDS = 120
    POLL_INTERVAL_SECONDS = 1

    # Anomaly detection thresholds
    DEFAULT_ANOMALY_THRESHOLD_PERCENT = 20.0
    MIN_BASELINE_COST_USD = 1.0  # Ignore services with < $1/day baseline

    def __init__(
        self,
        database: str | None = None,
        table: str | None = None,
        workgroup: str | None = None,
        output_location: str | None = None,
        region: str | None = None,
    ):
        """
        Initialize AWS Athena Querier.

        Args:
            database: Athena database name (defaults to ATHENA_DATABASE env var)
            table: CUR table name (defaults to ATHENA_TABLE env var)
            workgroup: Athena workgroup (defaults to ATHENA_WORKGROUP env var)
            output_location: S3 location for query results (defaults to ATHENA_OUTPUT_BUCKET env var)
            region: AWS region (defaults to AWS_REGION env var or us-east-1)
        """
        self.database = database or os.getenv("ATHENA_DATABASE", self.DEFAULT_DATABASE)
        self.table = table or os.getenv("ATHENA_TABLE", self.DEFAULT_TABLE)
        self.workgroup = workgroup or os.getenv("ATHENA_WORKGROUP", self.DEFAULT_WORKGROUP)
        self.output_location = output_location or os.getenv("ATHENA_OUTPUT_BUCKET")
        self.region = region or os.getenv("AWS_REGION", self.DEFAULT_REGION)

        self._athena_client = None

        # Check if boto3 is available
        try:
            import boto3  # noqa: F401

            self.boto3_available = True
            logger.info(
                f"AWSAthenaQuerier initialized: database={self.database}, "
                f"table={self.table}, workgroup={self.workgroup}, region={self.region}"
            )
        except ImportError:
            self.boto3_available = False
            logger.warning("AWSAthenaQuerier initialized but boto3 not available")

    @property
    def athena_client(self):
        """Lazy initialization of Athena client."""
        if not self.boto3_available:
            return None

        if self._athena_client is None:
            import boto3

            self._athena_client = boto3.client("athena", region_name=self.region)
            logger.debug("Athena client initialized")

        return self._athena_client

    def _build_query(self, template: str) -> str:
        """
        Build SQL query by substituting database and table placeholders.

        Args:
            template: SQL template with ${database} and ${table} placeholders

        Returns:
            SQL query string with placeholders replaced
        """
        return template.replace("${database}", self.database).replace("${table}", self.table)

    async def _start_query_execution(self, query: str) -> str:
        """
        Submit a query to Athena for execution.

        Args:
            query: SQL query string

        Returns:
            Query execution ID

        Raises:
            ValueError: If Athena client unavailable or output location not configured
        """
        if not self.athena_client:
            raise ValueError("Athena client not available - ensure boto3 is installed")

        if not self.output_location:
            raise ValueError("ATHENA_OUTPUT_BUCKET not configured")

        logger.debug(f"Starting Athena query: {query[:200]}...")

        execution_params = {
            "QueryString": query,
            "QueryExecutionContext": {"Database": self.database},
            "WorkGroup": self.workgroup,
        }

        # Only add ResultConfiguration if output location is specified
        # Some workgroups have default output locations configured
        if self.output_location:
            execution_params["ResultConfiguration"] = {"OutputLocation": self.output_location}

        response = self.athena_client.start_query_execution(**execution_params)

        query_execution_id = response["QueryExecutionId"]
        logger.info(f"Athena query started: {query_execution_id}")

        return query_execution_id

    async def _wait_for_query_completion(self, query_execution_id: str) -> dict[str, Any]:
        """
        Poll for query completion status.

        Args:
            query_execution_id: Athena query execution ID

        Returns:
            Query execution details

        Raises:
            TimeoutError: If query exceeds timeout
            RuntimeError: If query fails or is cancelled
        """
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.MAX_QUERY_TIMEOUT_SECONDS:
                # Try to cancel the query
                with contextlib.suppress(Exception):
                    self.athena_client.stop_query_execution(QueryExecutionId=query_execution_id)
                raise TimeoutError(
                    f"Athena query {query_execution_id} timed out after {elapsed:.1f}s"
                )

            response = self.athena_client.get_query_execution(QueryExecutionId=query_execution_id)

            status = response["QueryExecution"]["Status"]
            state = status["State"]

            if state == "SUCCEEDED":
                logger.info(f"Athena query {query_execution_id} succeeded in {elapsed:.1f}s")
                return response["QueryExecution"]

            elif state in ("FAILED", "CANCELLED"):
                error_message = status.get("StateChangeReason", "Unknown error")
                logger.error(f"Athena query {query_execution_id} {state}: {error_message}")
                raise RuntimeError(f"Athena query {state}: {error_message}")

            # Query still running, wait before polling again
            time.sleep(self.POLL_INTERVAL_SECONDS)

    async def _get_query_results(
        self, query_execution_id: str, max_results: int = 1000
    ) -> list[dict[str, Any]]:
        """
        Fetch and parse query results.

        Args:
            query_execution_id: Athena query execution ID
            max_results: Maximum number of results to return

        Returns:
            List of dictionaries, one per row
        """
        results = []
        next_token = None
        columns = []

        while True:
            params = {
                "QueryExecutionId": query_execution_id,
                "MaxResults": min(max_results - len(results), 1000),
            }
            if next_token:
                params["NextToken"] = next_token

            response = self.athena_client.get_query_results(**params)

            result_set = response.get("ResultSet", {})
            rows = result_set.get("Rows", [])

            # First row contains column headers
            if not columns and rows:
                column_info = result_set.get("ResultSetMetadata", {}).get("ColumnInfo", [])
                columns = [col["Name"] for col in column_info]
                rows = rows[1:]  # Skip header row

            # Parse data rows
            for row in rows:
                data = row.get("Data", [])
                row_dict = {}
                for i, col in enumerate(columns):
                    value = data[i].get("VarCharValue") if i < len(data) else None
                    # Try to convert to numeric if possible
                    if value is not None:
                        with contextlib.suppress(ValueError, TypeError):
                            value = float(value) if "." in value else int(value)
                    row_dict[col] = value
                results.append(row_dict)

            # Check for pagination
            next_token = response.get("NextToken")
            if not next_token or len(results) >= max_results:
                break

        logger.info(f"Retrieved {len(results)} rows from Athena query")
        return results

    async def execute_query(self, query: str, max_results: int = 1000) -> list[dict[str, Any]]:
        """
        Execute an Athena query and return results.

        This is the main method for running arbitrary CUR queries.

        Args:
            query: SQL query string
            max_results: Maximum number of results to return

        Returns:
            List of result dictionaries
        """
        try:
            query_execution_id = await self._start_query_execution(query)
            await self._wait_for_query_completion(query_execution_id)
            return await self._get_query_results(query_execution_id, max_results)
        except Exception as e:
            logger.error(f"Athena query execution failed: {e}", exc_info=True)
            raise

    # =========================================================================
    # Compute Cost Queries
    # =========================================================================

    async def get_ec2_costs_24h(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Get EC2 instance costs for the last 24 hours.

        Returns costs grouped by instance type and resource ID, sorted by cost.

        Args:
            limit: Maximum number of results

        Returns:
            List of EC2 cost records with instance_type, instance_id, cost, usage_hours
        """
        query = self._build_query(f"""
            SELECT
                DATE(line_item_usage_start_date) as usage_date,
                product_instance_type as instance_type,
                line_item_resource_id as instance_id,
                ROUND(SUM(line_item_unblended_cost), 4) as cost,
                ROUND(SUM(line_item_usage_amount), 2) as usage_hours
            FROM ${{database}}.${{table}}
            WHERE line_item_product_code = 'AmazonEC2'
                AND line_item_usage_start_date >= DATE_ADD('hour', -24, current_timestamp)
                AND line_item_line_item_type = 'Usage'
                AND line_item_unblended_cost > 0
            GROUP BY 1, 2, 3
            ORDER BY cost DESC
            LIMIT {limit}
        """)

        logger.info("Querying EC2 costs for last 24 hours")
        return await self.execute_query(query)

    async def get_lambda_costs_24h(self, limit: int = 30) -> list[dict[str, Any]]:
        """
        Get Lambda function costs for the last 24 hours.

        Returns costs grouped by function name with invocation and duration metrics.

        Args:
            limit: Maximum number of results

        Returns:
            List of Lambda cost records with function_name, cost, invocations, duration_gb_seconds
        """
        query = self._build_query(f"""
            SELECT
                REGEXP_EXTRACT(line_item_resource_id, ':function:([^:]+)', 1) as function_name,
                ROUND(SUM(line_item_unblended_cost), 4) as cost,
                SUM(CASE WHEN line_item_usage_type LIKE '%Request%'
                    THEN CAST(line_item_usage_amount AS BIGINT) END) as invocations,
                ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%Duration%'
                    THEN line_item_usage_amount END), 2) as duration_gb_seconds
            FROM ${{database}}.${{table}}
            WHERE line_item_product_code = 'AWSLambda'
                AND line_item_usage_start_date >= DATE_ADD('hour', -24, current_timestamp)
                AND line_item_line_item_type = 'Usage'
            GROUP BY 1
            HAVING SUM(line_item_unblended_cost) > 0.01
            ORDER BY cost DESC
            LIMIT {limit}
        """)

        logger.info("Querying Lambda costs for last 24 hours")
        return await self.execute_query(query)

    async def get_compute_costs_24h(self) -> dict[str, Any]:
        """
        Get combined compute costs (EC2 + Lambda) for the last 24 hours.

        Returns:
            Dictionary with ec2_costs, lambda_costs, and summary totals
        """
        ec2_costs = await self.get_ec2_costs_24h()
        lambda_costs = await self.get_lambda_costs_24h()

        ec2_total = sum(r.get("cost", 0) or 0 for r in ec2_costs)
        lambda_total = sum(r.get("cost", 0) or 0 for r in lambda_costs)

        return {
            "ec2_costs": ec2_costs,
            "lambda_costs": lambda_costs,
            "ec2_total": round(ec2_total, 2),
            "lambda_total": round(lambda_total, 2),
            "compute_total": round(ec2_total + lambda_total, 2),
            "ec2_instance_count": len(ec2_costs),
            "lambda_function_count": len(lambda_costs),
        }

    # =========================================================================
    # EKS/Container Cost Queries
    # =========================================================================

    async def get_eks_costs_24h(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Get EKS pod-level costs for the last 24 hours using Split Cost Allocation.

        This requires AWS Split Cost Allocation Data for EKS to be enabled.
        See: https://aws.amazon.com/blogs/aws-cloud-financial-management/improve-cost-visibility-of-amazon-eks-with-aws-split-cost-allocation-data/

        Args:
            limit: Maximum number of results

        Returns:
            List of EKS cost records with cluster, namespace, pod, actual_cost, unused_cost
        """
        query = self._build_query(f"""
            SELECT
                split_line_item_parent_resource_id as cluster_arn,
                resource_tags_kubernetes_io_namespace as namespace,
                resource_tags_kubernetes_io_name as pod_name,
                ROUND(SUM(COALESCE(split_line_item_actual_cost, 0)), 4) as actual_cost,
                ROUND(SUM(COALESCE(split_line_item_unused_cost, 0)), 4) as unused_cost,
                ROUND(SUM(COALESCE(split_line_item_actual_cost, 0) +
                      COALESCE(split_line_item_unused_cost, 0)), 4) as total_cost
            FROM ${{database}}.${{table}}
            WHERE line_item_product_code = 'AmazonEKS'
                AND line_item_usage_start_date >= DATE_ADD('hour', -24, current_timestamp)
                AND split_line_item_parent_resource_id IS NOT NULL
            GROUP BY 1, 2, 3
            HAVING SUM(COALESCE(split_line_item_actual_cost, 0) +
                   COALESCE(split_line_item_unused_cost, 0)) > 0.01
            ORDER BY total_cost DESC
            LIMIT {limit}
        """)

        logger.info("Querying EKS costs for last 24 hours (Split Cost Allocation)")
        return await self.execute_query(query)

    async def get_eks_costs_by_namespace(self, limit: int = 20) -> list[dict[str, Any]]:
        """
        Get EKS costs aggregated by namespace for the last 24 hours.

        Args:
            limit: Maximum number of namespaces

        Returns:
            List of namespace cost records
        """
        query = self._build_query(f"""
            SELECT
                resource_tags_kubernetes_io_namespace as namespace,
                COUNT(DISTINCT resource_tags_kubernetes_io_name) as pod_count,
                ROUND(SUM(COALESCE(split_line_item_actual_cost, 0)), 4) as actual_cost,
                ROUND(SUM(COALESCE(split_line_item_unused_cost, 0)), 4) as unused_cost,
                ROUND(SUM(COALESCE(split_line_item_actual_cost, 0) +
                      COALESCE(split_line_item_unused_cost, 0)), 4) as total_cost
            FROM ${{database}}.${{table}}
            WHERE line_item_product_code = 'AmazonEKS'
                AND line_item_usage_start_date >= DATE_ADD('hour', -24, current_timestamp)
                AND resource_tags_kubernetes_io_namespace IS NOT NULL
            GROUP BY 1
            HAVING SUM(COALESCE(split_line_item_actual_cost, 0) +
                   COALESCE(split_line_item_unused_cost, 0)) > 0.01
            ORDER BY total_cost DESC
            LIMIT {limit}
        """)

        logger.info("Querying EKS costs by namespace for last 24 hours")
        return await self.execute_query(query)

    # =========================================================================
    # Networking Cost Queries
    # =========================================================================

    async def get_nat_gateway_costs_24h(self, limit: int = 20) -> list[dict[str, Any]]:
        """
        Get NAT Gateway costs for the last 24 hours.

        Returns hourly charges plus data processing costs per NAT Gateway.

        Args:
            limit: Maximum number of results

        Returns:
            List of NAT Gateway cost records
        """
        query = self._build_query(f"""
            SELECT
                line_item_resource_id as nat_gateway_id,
                line_item_availability_zone as az,
                ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%NatGateway-Hours%'
                    THEN line_item_unblended_cost END), 4) as hourly_cost,
                ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%NatGateway-Bytes%'
                    THEN line_item_unblended_cost END), 4) as data_cost,
                ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%NatGateway-Bytes%'
                    THEN line_item_usage_amount END) / 1073741824, 4) as gb_processed,
                ROUND(SUM(line_item_unblended_cost), 4) as total_cost
            FROM ${{database}}.${{table}}
            WHERE line_item_product_code = 'AmazonVPC'
                AND line_item_usage_type LIKE '%NatGateway%'
                AND line_item_usage_start_date >= DATE_ADD('hour', -24, current_timestamp)
            GROUP BY 1, 2
            ORDER BY total_cost DESC
            LIMIT {limit}
        """)

        logger.info("Querying NAT Gateway costs for last 24 hours")
        return await self.execute_query(query)

    async def get_data_transfer_costs_24h(self, limit: int = 30) -> list[dict[str, Any]]:
        """
        Get data transfer costs for the last 24 hours.

        Includes inter-region, inter-AZ, and internet data transfer.

        Args:
            limit: Maximum number of results

        Returns:
            List of data transfer cost records
        """
        query = self._build_query(f"""
            SELECT
                line_item_product_code as service,
                line_item_usage_type as transfer_type,
                product_from_location as from_location,
                product_to_location as to_location,
                ROUND(SUM(line_item_unblended_cost), 4) as cost,
                ROUND(SUM(line_item_usage_amount) / 1073741824, 4) as gb_transferred
            FROM ${{database}}.${{table}}
            WHERE (line_item_usage_type LIKE '%DataTransfer%'
                OR line_item_usage_type LIKE '%Bytes%')
                AND line_item_usage_start_date >= DATE_ADD('hour', -24, current_timestamp)
                AND line_item_unblended_cost > 0
            GROUP BY 1, 2, 3, 4
            ORDER BY cost DESC
            LIMIT {limit}
        """)

        logger.info("Querying data transfer costs for last 24 hours")
        return await self.execute_query(query)

    async def get_networking_costs_24h(self) -> dict[str, Any]:
        """
        Get combined networking costs for the last 24 hours.

        Returns:
            Dictionary with nat_gateway_costs, data_transfer_costs, and totals
        """
        nat_costs = await self.get_nat_gateway_costs_24h()
        transfer_costs = await self.get_data_transfer_costs_24h()

        nat_total = sum(r.get("total_cost", 0) or 0 for r in nat_costs)
        transfer_total = sum(r.get("cost", 0) or 0 for r in transfer_costs)

        return {
            "nat_gateway_costs": nat_costs,
            "data_transfer_costs": transfer_costs,
            "nat_gateway_total": round(nat_total, 2),
            "data_transfer_total": round(transfer_total, 2),
            "networking_total": round(nat_total + transfer_total, 2),
            "nat_gateway_count": len(nat_costs),
        }

    # =========================================================================
    # Anomaly Detection
    # =========================================================================

    async def detect_anomalies(self, threshold_percent: float = None) -> list[dict[str, Any]]:
        """
        Detect cost anomalies by comparing 24h costs to 7-day baseline.

        An anomaly is detected when the 24h cost exceeds the 7-day daily average
        by more than the threshold percentage.

        Args:
            threshold_percent: Minimum percentage increase to flag as anomaly
                              (default: 20%)

        Returns:
            List of anomaly records sorted by change percentage
        """
        threshold = threshold_percent or self.DEFAULT_ANOMALY_THRESHOLD_PERCENT
        min_cost = self.MIN_BASELINE_COST_USD

        query = self._build_query(f"""
            WITH current_24h AS (
                SELECT
                    line_item_product_code as service,
                    ROUND(SUM(line_item_unblended_cost), 4) as cost
                FROM ${{database}}.${{table}}
                WHERE line_item_usage_start_date >= DATE_ADD('hour', -24, current_timestamp)
                    AND line_item_line_item_type = 'Usage'
                GROUP BY 1
            ),
            baseline_7d AS (
                SELECT
                    line_item_product_code as service,
                    ROUND(SUM(line_item_unblended_cost) / 7, 4) as avg_daily_cost
                FROM ${{database}}.${{table}}
                WHERE line_item_usage_start_date >= DATE_ADD('day', -7, current_timestamp)
                    AND line_item_usage_start_date < DATE_ADD('hour', -24, current_timestamp)
                    AND line_item_line_item_type = 'Usage'
                GROUP BY 1
            )
            SELECT
                c.service,
                ROUND(c.cost, 2) as current_24h_cost,
                ROUND(b.avg_daily_cost, 2) as baseline_daily_avg,
                ROUND((c.cost - b.avg_daily_cost) / b.avg_daily_cost * 100, 1) as change_percent,
                ROUND(c.cost - b.avg_daily_cost, 2) as cost_difference
            FROM current_24h c
            JOIN baseline_7d b ON c.service = b.service
            WHERE b.avg_daily_cost > {min_cost}
                AND ((c.cost - b.avg_daily_cost) / b.avg_daily_cost * 100) > {threshold}
            ORDER BY change_percent DESC
        """)

        logger.info(f"Detecting cost anomalies (threshold: {threshold}%)")
        results = await self.execute_query(query)

        # Add severity classification
        for r in results:
            change = r.get("change_percent", 0) or 0
            if change >= 100:
                r["severity"] = "high"
            elif change >= 50:
                r["severity"] = "medium"
            else:
                r["severity"] = "low"

        return results

    async def get_idle_nat_gateways(self) -> list[dict[str, Any]]:
        """
        Find NAT Gateways with hourly charges but minimal data transfer.

        Idle NAT Gateways cost ~$32/month even with no traffic.

        Returns:
            List of potentially idle NAT Gateway records
        """
        query = self._build_query("""
            SELECT
                line_item_resource_id as nat_gateway_id,
                line_item_availability_zone as az,
                ROUND(SUM(CASE WHEN line_item_usage_type LIKE '%NatGateway-Hours%'
                    THEN line_item_unblended_cost END), 4) as hourly_cost,
                SUM(CASE WHEN line_item_usage_type LIKE '%NatGateway-Bytes%'
                    THEN line_item_usage_amount END) as bytes_processed
            FROM ${database}.${table}
            WHERE line_item_product_code = 'AmazonVPC'
                AND line_item_usage_type LIKE '%NatGateway%'
                AND line_item_usage_start_date >= DATE_ADD('hour', -24, current_timestamp)
            GROUP BY 1, 2
            HAVING SUM(CASE WHEN line_item_usage_type LIKE '%NatGateway-Bytes%'
                       THEN line_item_usage_amount END) < 1048576
                AND SUM(CASE WHEN line_item_usage_type LIKE '%NatGateway-Hours%'
                       THEN line_item_unblended_cost END) > 0
            ORDER BY hourly_cost DESC
        """)

        logger.info("Checking for idle NAT Gateways")
        results = await self.execute_query(query)

        # Add recommendation
        for r in results:
            bytes_processed = r.get("bytes_processed", 0) or 0
            r["recommendation"] = (
                "Consider removing if not needed - "
                f"Only {bytes_processed / 1024:.1f} KB processed in 24h"
            )

        return results

    # =========================================================================
    # Summary Endpoint
    # =========================================================================

    async def get_daily_summary(self, anomaly_threshold: float = None) -> dict[str, Any]:
        """
        Get comprehensive 24h cost summary with anomalies.

        This is the main entry point for the cost analysis skill.

        Args:
            anomaly_threshold: Anomaly detection threshold percentage

        Returns:
            Dictionary with compute_costs, eks_costs, networking_costs, anomalies
        """
        logger.info("Generating daily cost summary")

        # Run queries (could be parallelized for better performance)
        anomalies = await self.detect_anomalies(anomaly_threshold)
        compute_costs = await self.get_compute_costs_24h()

        # EKS costs may fail if Split Cost Allocation is not enabled
        try:
            eks_costs = await self.get_eks_costs_by_namespace()
            eks_total = sum(r.get("total_cost", 0) or 0 for r in eks_costs)
        except Exception as e:
            logger.warning(f"EKS costs unavailable (Split Cost Allocation may not be enabled): {e}")
            eks_costs = []
            eks_total = 0

        networking_costs = await self.get_networking_costs_24h()
        idle_nats = await self.get_idle_nat_gateways()

        # Calculate grand total
        grand_total = (
            compute_costs.get("compute_total", 0)
            + eks_total
            + networking_costs.get("networking_total", 0)
        )

        return {
            "summary": {
                "total_24h_cost": round(grand_total, 2),
                "compute_total": compute_costs.get("compute_total", 0),
                "eks_total": round(eks_total, 2),
                "networking_total": networking_costs.get("networking_total", 0),
                "anomaly_count": len(anomalies),
                "idle_nat_count": len(idle_nats),
                "timestamp": datetime.utcnow().isoformat(),
            },
            "anomalies": anomalies,
            "compute": compute_costs,
            "eks": {"by_namespace": eks_costs, "total": round(eks_total, 2)},
            "networking": networking_costs,
            "idle_nat_gateways": idle_nats,
            "recommendations": self._generate_recommendations(
                anomalies, idle_nats, compute_costs, networking_costs
            ),
        }

    def _generate_recommendations(
        self,
        anomalies: list[dict],
        idle_nats: list[dict],
        compute_costs: dict,
        networking_costs: dict,
    ) -> list[str]:
        """Generate cost optimization recommendations based on analysis."""
        recommendations = []

        # Anomaly-based recommendations
        if anomalies:
            high_severity = [a for a in anomalies if a.get("severity") == "high"]
            if high_severity:
                services = ", ".join(a["service"] for a in high_severity[:3])
                recommendations.append(
                    f"🚨 High severity anomalies detected in: {services}. "
                    "Investigate immediate cause."
                )

        # Idle NAT recommendations
        if idle_nats:
            total_idle_cost = sum(n.get("hourly_cost", 0) or 0 for n in idle_nats) * 24 * 30
            recommendations.append(
                f"💰 {len(idle_nats)} idle NAT Gateway(s) found. "
                f"Potential monthly savings: ~${total_idle_cost:.2f}"
            )

        # Compute recommendations
        ec2_costs = compute_costs.get("ec2_costs", [])
        if ec2_costs and len(ec2_costs) > 10:
            top_instance = ec2_costs[0] if ec2_costs else {}
            if top_instance.get("cost", 0) > 10:
                recommendations.append(
                    f"📊 Top EC2 spender: {top_instance.get('instance_type', 'unknown')} "
                    f"(${top_instance.get('cost', 0):.2f}/24h). "
                    "Review for rightsizing or Reserved Instance opportunities."
                )

        # Networking recommendations
        nat_total = networking_costs.get("nat_gateway_total", 0)
        if nat_total > 50:
            recommendations.append(
                f"🌐 NAT Gateway spending ${nat_total:.2f}/24h. "
                "Consider VPC endpoints for high-traffic AWS services (S3, DynamoDB)."
            )

        if not recommendations:
            recommendations.append("✅ No significant cost optimization opportunities detected.")

        return recommendations
