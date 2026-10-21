"""
Athena CUR Cost Analysis API Endpoints

Provides HTTP endpoints for AWS cost analysis and anomaly detection by querying
Cost and Usage Report (CUR) data via Athena.

Endpoints:
- GET  /athena-costs/health - Health check for Athena integration
- GET  /athena-costs/anomalies - Detect cost anomalies (24h vs 7-day baseline)
- GET  /athena-costs/compute - Get EC2 and Lambda costs
- GET  /athena-costs/eks - Get EKS/container costs (requires Split Cost Allocation)
- GET  /athena-costs/networking - Get NAT Gateway and data transfer costs
- GET  /athena-costs/summary - Comprehensive 24h cost summary with anomalies

This module leverages the CUR infrastructure deployed via:
- DEVOPS-7593 (Athena module)
- DEVOPS-7594 (CUR module)
- DEVOPS-7599 (QuickSight dashboards)
"""

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.middleware import limiter_with_key, verify_api_key
from api.models import (
    AthenaAnomalyResponse,
    AthenaComputeResponse,
    AthenaCostAnomaly,
    AthenaCostSummaryResponse,
    AthenaEKSResponse,
    AthenaNetworkingResponse,
    ComputeCostBreakdown,
    CostSummary,
    DataTransferCostRecord,
    EC2CostRecord,
    EKSCostBreakdown,
    EKSNamespaceCost,
    IdleNATGateway,
    LambdaCostRecord,
    NATGatewayCostRecord,
    NetworkingCostBreakdown,
)
from tools.aws_athena_querier import AWSAthenaQuerier

logger = logging.getLogger(__name__)

# Create router with prefix
router = APIRouter(prefix="/athena-costs", tags=["athena-costs"])

# Global Athena Querier instance (initialized on first use)
_athena_querier: AWSAthenaQuerier | None = None


def get_athena_querier() -> AWSAthenaQuerier:
    """
    Get or create the global AWSAthenaQuerier instance.

    Returns:
        AWSAthenaQuerier instance
    """
    global _athena_querier
    if _athena_querier is None:
        _athena_querier = AWSAthenaQuerier()
        logger.info("Initialized AWSAthenaQuerier instance")
    return _athena_querier


@router.get("/health")
async def athena_costs_health():
    """
    Health check for AWS Athena CUR integration.

    Verifies that:
    - boto3 is available
    - AWS credentials are configured
    - Athena configuration is valid

    Returns:
        Health status and configuration info
    """
    try:
        querier = get_athena_querier()

        health_status = {
            "status": "healthy" if querier.boto3_available else "degraded",
            "boto3_available": querier.boto3_available,
            "database": querier.database,
            "table": querier.table,
            "workgroup": querier.workgroup,
            "region": querier.region,
            "output_location_configured": querier.output_location is not None,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if not querier.boto3_available:
            health_status["message"] = "boto3 not available - install with: pip install boto3"
            health_status["status"] = "unhealthy"
        elif not querier.output_location:
            health_status["message"] = "ATHENA_OUTPUT_BUCKET not configured"
            health_status["status"] = "degraded"
        else:
            health_status["message"] = "Athena CUR integration is healthy"

        return health_status

    except Exception as e:
        logger.error(f"Athena costs health check failed: {e}", exc_info=True)
        return {"status": "unhealthy", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@router.get("/anomalies", response_model=AthenaAnomalyResponse)
@limiter_with_key.limit("30/minute")
async def detect_athena_cost_anomalies(
    request: Request,
    threshold_pct: float = Query(
        default=20.0, ge=5.0, le=100.0, description="Anomaly threshold percentage"
    ),
    api_key: str = Depends(verify_api_key),
) -> AthenaAnomalyResponse:
    """
    Detect cost anomalies by comparing 24h costs to 7-day baseline.

    This endpoint queries CUR data via Athena to identify services where
    the last 24 hours of spending exceeds the 7-day daily average by more
    than the specified threshold.

    **Anomaly Severity Classification**:
    - Low: 20-50% increase
    - Medium: 50-100% increase
    - High: >100% increase

    **Requires**:
    - AWS credentials with Athena and S3 permissions
    - CUR data in Athena (deployed via DEVOPS-7593/7594)

    **Rate Limit**: 30 requests/minute

    Args:
        threshold_pct: Minimum percentage increase to flag as anomaly (default: 20%)

    Returns:
        AthenaAnomalyResponse with detected anomalies and severity classification
    """
    start_time = time.time()

    try:
        logger.info(f"Athena anomaly detection request: threshold={threshold_pct}%")

        querier = get_athena_querier()

        if not querier.boto3_available:
            raise HTTPException(
                status_code=503, detail="AWS Athena not available - boto3 not installed"
            )

        if not querier.output_location:
            raise HTTPException(status_code=503, detail="ATHENA_OUTPUT_BUCKET not configured")

        # Execute anomaly detection query
        anomalies_data = await querier.detect_anomalies(threshold_percent=threshold_pct)

        # Convert to Pydantic models
        anomalies = [
            AthenaCostAnomaly(
                service=a.get("service", "Unknown"),
                current_24h_cost=a.get("current_24h_cost", 0.0),
                baseline_daily_avg=a.get("baseline_daily_avg", 0.0),
                change_percent=a.get("change_percent", 0.0),
                cost_difference=a.get("cost_difference", 0.0),
                severity=a.get("severity", "low"),
            )
            for a in anomalies_data
        ]

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Athena anomaly detection completed in {duration_ms:.2f}ms: "
            f"{len(anomalies)} anomalies found"
        )

        return AthenaAnomalyResponse(
            status="success",
            anomalies=anomalies,
            anomaly_count=len(anomalies),
            threshold_percent=threshold_pct,
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Athena anomaly detection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Athena anomaly detection failed: {str(e)}")


@router.get("/compute", response_model=AthenaComputeResponse)
@limiter_with_key.limit("30/minute")
async def get_athena_compute_costs(
    request: Request, api_key: str = Depends(verify_api_key)
) -> AthenaComputeResponse:
    """
    Get EC2 and Lambda costs for the last 24 hours.

    Returns detailed breakdowns of:
    - EC2 instance costs by instance type and ID
    - Lambda function costs with invocation counts and duration

    **Requires**:
    - AWS credentials with Athena and S3 permissions
    - CUR data in Athena

    **Rate Limit**: 30 requests/minute

    Returns:
        AthenaComputeResponse with EC2 and Lambda cost breakdowns
    """
    start_time = time.time()

    try:
        logger.info("Athena compute costs request")

        querier = get_athena_querier()

        if not querier.boto3_available:
            raise HTTPException(
                status_code=503, detail="AWS Athena not available - boto3 not installed"
            )

        # Get compute costs
        costs_data = await querier.get_compute_costs_24h()

        # Convert to Pydantic models
        ec2_costs = [
            EC2CostRecord(
                usage_date=c.get("usage_date"),
                instance_type=c.get("instance_type"),
                instance_id=c.get("instance_id"),
                cost=c.get("cost", 0.0),
                usage_hours=c.get("usage_hours"),
            )
            for c in costs_data.get("ec2_costs", [])
        ]

        lambda_costs = [
            LambdaCostRecord(
                function_name=c.get("function_name"),
                cost=c.get("cost", 0.0),
                invocations=c.get("invocations"),
                duration_gb_seconds=c.get("duration_gb_seconds"),
            )
            for c in costs_data.get("lambda_costs", [])
        ]

        compute = ComputeCostBreakdown(
            ec2_costs=ec2_costs,
            lambda_costs=lambda_costs,
            ec2_total=costs_data.get("ec2_total", 0.0),
            lambda_total=costs_data.get("lambda_total", 0.0),
            compute_total=costs_data.get("compute_total", 0.0),
            ec2_instance_count=costs_data.get("ec2_instance_count", 0),
            lambda_function_count=costs_data.get("lambda_function_count", 0),
        )

        duration_ms = (time.time() - start_time) * 1000
        logger.info(f"Athena compute costs completed in {duration_ms:.2f}ms")

        return AthenaComputeResponse(status="success", compute=compute, timestamp=datetime.utcnow())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Athena compute costs failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Athena compute costs failed: {str(e)}")


@router.get("/eks", response_model=AthenaEKSResponse)
@limiter_with_key.limit("30/minute")
async def get_athena_eks_costs(
    request: Request, api_key: str = Depends(verify_api_key)
) -> AthenaEKSResponse:
    """
    Get EKS/container costs for the last 24 hours.

    Returns costs aggregated by Kubernetes namespace using AWS Split Cost
    Allocation Data for EKS.

    **Note**: Requires AWS Split Cost Allocation Data for EKS to be enabled.
    See: https://aws.amazon.com/blogs/aws-cloud-financial-management/improve-cost-visibility-of-amazon-eks-with-aws-split-cost-allocation-data/

    **Requires**:
    - AWS credentials with Athena and S3 permissions
    - CUR data with EKS Split Cost Allocation enabled

    **Rate Limit**: 30 requests/minute

    Returns:
        AthenaEKSResponse with EKS cost breakdown by namespace
    """
    start_time = time.time()

    try:
        logger.info("Athena EKS costs request")

        querier = get_athena_querier()

        if not querier.boto3_available:
            raise HTTPException(
                status_code=503, detail="AWS Athena not available - boto3 not installed"
            )

        # Get EKS costs by namespace
        try:
            eks_data = await querier.get_eks_costs_by_namespace()
        except Exception as eks_error:
            logger.warning(
                f"EKS costs query failed (Split Cost Allocation may not be enabled): {eks_error}"
            )
            eks_data = []

        # Convert to Pydantic models
        namespace_costs = [
            EKSNamespaceCost(
                namespace=c.get("namespace"),
                pod_count=c.get("pod_count"),
                actual_cost=c.get("actual_cost", 0.0),
                unused_cost=c.get("unused_cost", 0.0),
                total_cost=c.get("total_cost", 0.0),
            )
            for c in eks_data
        ]

        eks_total = sum(c.total_cost for c in namespace_costs)

        eks = EKSCostBreakdown(by_namespace=namespace_costs, total=round(eks_total, 2))

        duration_ms = (time.time() - start_time) * 1000
        logger.info(f"Athena EKS costs completed in {duration_ms:.2f}ms")

        return AthenaEKSResponse(status="success", eks=eks, timestamp=datetime.utcnow())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Athena EKS costs failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Athena EKS costs failed: {str(e)}")


@router.get("/networking", response_model=AthenaNetworkingResponse)
@limiter_with_key.limit("30/minute")
async def get_athena_networking_costs(
    request: Request, api_key: str = Depends(verify_api_key)
) -> AthenaNetworkingResponse:
    """
    Get NAT Gateway and data transfer costs for the last 24 hours.

    Returns:
    - NAT Gateway costs (hourly + data processing)
    - Data transfer costs (inter-region, inter-AZ, internet)
    - Idle NAT Gateway detection (high cost, low traffic)

    **Requires**:
    - AWS credentials with Athena and S3 permissions
    - CUR data in Athena

    **Rate Limit**: 30 requests/minute

    Returns:
        AthenaNetworkingResponse with networking cost breakdown and idle NAT alerts
    """
    start_time = time.time()

    try:
        logger.info("Athena networking costs request")

        querier = get_athena_querier()

        if not querier.boto3_available:
            raise HTTPException(
                status_code=503, detail="AWS Athena not available - boto3 not installed"
            )

        # Get networking costs
        costs_data = await querier.get_networking_costs_24h()
        idle_nats_data = await querier.get_idle_nat_gateways()

        # Convert NAT Gateway costs
        nat_costs = [
            NATGatewayCostRecord(
                nat_gateway_id=c.get("nat_gateway_id"),
                az=c.get("az"),
                hourly_cost=c.get("hourly_cost"),
                data_cost=c.get("data_cost"),
                gb_processed=c.get("gb_processed"),
                total_cost=c.get("total_cost", 0.0),
            )
            for c in costs_data.get("nat_gateway_costs", [])
        ]

        # Convert data transfer costs
        transfer_costs = [
            DataTransferCostRecord(
                service=c.get("service"),
                transfer_type=c.get("transfer_type"),
                from_location=c.get("from_location"),
                to_location=c.get("to_location"),
                cost=c.get("cost", 0.0),
                gb_transferred=c.get("gb_transferred"),
            )
            for c in costs_data.get("data_transfer_costs", [])
        ]

        networking = NetworkingCostBreakdown(
            nat_gateway_costs=nat_costs,
            data_transfer_costs=transfer_costs,
            nat_gateway_total=costs_data.get("nat_gateway_total", 0.0),
            data_transfer_total=costs_data.get("data_transfer_total", 0.0),
            networking_total=costs_data.get("networking_total", 0.0),
            nat_gateway_count=costs_data.get("nat_gateway_count", 0),
        )

        # Convert idle NAT Gateways
        idle_nats = [
            IdleNATGateway(
                nat_gateway_id=n.get("nat_gateway_id"),
                az=n.get("az"),
                hourly_cost=n.get("hourly_cost", 0.0),
                bytes_processed=n.get("bytes_processed"),
                recommendation=n.get("recommendation"),
            )
            for n in idle_nats_data
        ]

        duration_ms = (time.time() - start_time) * 1000
        logger.info(f"Athena networking costs completed in {duration_ms:.2f}ms")

        return AthenaNetworkingResponse(
            status="success",
            networking=networking,
            idle_nat_gateways=idle_nats,
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Athena networking costs failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Athena networking costs failed: {str(e)}")


@router.get("/summary", response_model=AthenaCostSummaryResponse)
@limiter_with_key.limit("20/minute")
async def get_athena_cost_summary(
    request: Request,
    threshold_pct: float = Query(
        default=20.0, ge=5.0, le=100.0, description="Anomaly threshold percentage"
    ),
    api_key: str = Depends(verify_api_key),
) -> AthenaCostSummaryResponse:
    """
    Get comprehensive 24-hour cost summary with anomalies and recommendations.

    This is the main endpoint for the cost analysis skill, providing:
    - Total costs across compute, EKS, and networking
    - Anomaly detection with severity classification
    - Idle resource identification
    - Cost optimization recommendations

    **Rate Limit**: 20 requests/minute (lower due to multiple queries)

    Args:
        threshold_pct: Anomaly detection threshold (default: 20%)

    Returns:
        AthenaCostSummaryResponse with full cost analysis and recommendations
    """
    start_time = time.time()

    try:
        logger.info(f"Athena cost summary request: threshold={threshold_pct}%")

        querier = get_athena_querier()

        if not querier.boto3_available:
            raise HTTPException(
                status_code=503, detail="AWS Athena not available - boto3 not installed"
            )

        if not querier.output_location:
            raise HTTPException(status_code=503, detail="ATHENA_OUTPUT_BUCKET not configured")

        # Get comprehensive summary
        summary_data = await querier.get_daily_summary(anomaly_threshold=threshold_pct)

        # Convert anomalies
        anomalies = [
            AthenaCostAnomaly(
                service=a.get("service", "Unknown"),
                current_24h_cost=a.get("current_24h_cost", 0.0),
                baseline_daily_avg=a.get("baseline_daily_avg", 0.0),
                change_percent=a.get("change_percent", 0.0),
                cost_difference=a.get("cost_difference", 0.0),
                severity=a.get("severity", "low"),
            )
            for a in summary_data.get("anomalies", [])
        ]

        # Convert compute costs
        compute_data = summary_data.get("compute", {})
        ec2_costs = [
            EC2CostRecord(
                usage_date=c.get("usage_date"),
                instance_type=c.get("instance_type"),
                instance_id=c.get("instance_id"),
                cost=c.get("cost", 0.0),
                usage_hours=c.get("usage_hours"),
            )
            for c in compute_data.get("ec2_costs", [])
        ]
        lambda_costs = [
            LambdaCostRecord(
                function_name=c.get("function_name"),
                cost=c.get("cost", 0.0),
                invocations=c.get("invocations"),
                duration_gb_seconds=c.get("duration_gb_seconds"),
            )
            for c in compute_data.get("lambda_costs", [])
        ]
        compute = ComputeCostBreakdown(
            ec2_costs=ec2_costs,
            lambda_costs=lambda_costs,
            ec2_total=compute_data.get("ec2_total", 0.0),
            lambda_total=compute_data.get("lambda_total", 0.0),
            compute_total=compute_data.get("compute_total", 0.0),
            ec2_instance_count=compute_data.get("ec2_instance_count", 0),
            lambda_function_count=compute_data.get("lambda_function_count", 0),
        )

        # Convert EKS costs
        eks_data = summary_data.get("eks", {})
        namespace_costs = [
            EKSNamespaceCost(
                namespace=c.get("namespace"),
                pod_count=c.get("pod_count"),
                actual_cost=c.get("actual_cost", 0.0),
                unused_cost=c.get("unused_cost", 0.0),
                total_cost=c.get("total_cost", 0.0),
            )
            for c in eks_data.get("by_namespace", [])
        ]
        eks = EKSCostBreakdown(by_namespace=namespace_costs, total=eks_data.get("total", 0.0))

        # Convert networking costs
        networking_data = summary_data.get("networking", {})
        nat_costs = [
            NATGatewayCostRecord(
                nat_gateway_id=c.get("nat_gateway_id"),
                az=c.get("az"),
                hourly_cost=c.get("hourly_cost"),
                data_cost=c.get("data_cost"),
                gb_processed=c.get("gb_processed"),
                total_cost=c.get("total_cost", 0.0),
            )
            for c in networking_data.get("nat_gateway_costs", [])
        ]
        transfer_costs = [
            DataTransferCostRecord(
                service=c.get("service"),
                transfer_type=c.get("transfer_type"),
                from_location=c.get("from_location"),
                to_location=c.get("to_location"),
                cost=c.get("cost", 0.0),
                gb_transferred=c.get("gb_transferred"),
            )
            for c in networking_data.get("data_transfer_costs", [])
        ]
        networking = NetworkingCostBreakdown(
            nat_gateway_costs=nat_costs,
            data_transfer_costs=transfer_costs,
            nat_gateway_total=networking_data.get("nat_gateway_total", 0.0),
            data_transfer_total=networking_data.get("data_transfer_total", 0.0),
            networking_total=networking_data.get("networking_total", 0.0),
            nat_gateway_count=networking_data.get("nat_gateway_count", 0),
        )

        # Convert idle NATs
        idle_nats = [
            IdleNATGateway(
                nat_gateway_id=n.get("nat_gateway_id"),
                az=n.get("az"),
                hourly_cost=n.get("hourly_cost", 0.0),
                bytes_processed=n.get("bytes_processed"),
                recommendation=n.get("recommendation"),
            )
            for n in summary_data.get("idle_nat_gateways", [])
        ]

        # Build summary
        summary_info = summary_data.get("summary", {})
        summary = CostSummary(
            total_24h_cost=summary_info.get("total_24h_cost", 0.0),
            compute_total=summary_info.get("compute_total", 0.0),
            eks_total=summary_info.get("eks_total", 0.0),
            networking_total=summary_info.get("networking_total", 0.0),
            anomaly_count=summary_info.get("anomaly_count", 0),
            idle_nat_count=summary_info.get("idle_nat_count", 0),
            timestamp=summary_info.get("timestamp", datetime.utcnow().isoformat()),
        )

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Athena cost summary completed in {duration_ms:.2f}ms: "
            f"total=${summary.total_24h_cost:.2f}, anomalies={len(anomalies)}"
        )

        return AthenaCostSummaryResponse(
            status="success",
            summary=summary,
            anomalies=anomalies,
            compute=compute,
            eks=eks,
            networking=networking,
            idle_nat_gateways=idle_nats,
            recommendations=summary_data.get("recommendations", []),
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Athena cost summary failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Athena cost summary failed: {str(e)}")
