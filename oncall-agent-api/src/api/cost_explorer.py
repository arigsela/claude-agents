"""
AWS Cost Explorer API Endpoints

Provides dedicated HTTP endpoints for AWS cost analysis and anomaly detection.
This module is designed to be extensible for future cost-related features.

Endpoints:
- POST /cost-explorer/anomalies - Detect cost anomalies
- POST /cost-explorer/daily-costs - Get daily cost breakdown
- GET  /cost-explorer/health - Health check for Cost Explorer integration

Future endpoints can be added here for:
- Cost forecasting
- Budget alerts
- Reserved Instance recommendations
- Savings Plans analysis
- Cost allocation tag analysis
"""

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware import limiter_with_key, verify_api_key
from api.models import (
    CostAnomaly,
    CostAnomalyRequest,
    CostAnomalyResponse,
    DailyCostBreakdown,
    DailyCostsRequest,
    DailyCostsResponse,
    ServiceCost,
)
from tools.aws_cost_explorer import AWSCostExplorer

logger = logging.getLogger(__name__)

# Create router with prefix
router = APIRouter(prefix="/cost-explorer", tags=["cost-explorer"])

# Global Cost Explorer instance (initialized on first use)
_cost_explorer: AWSCostExplorer | None = None


def get_cost_explorer() -> AWSCostExplorer:
    """
    Get or create the global AWSCostExplorer instance.

    Returns:
        AWSCostExplorer instance
    """
    global _cost_explorer
    if _cost_explorer is None:
        _cost_explorer = AWSCostExplorer()
        logger.info("Initialized AWSCostExplorer instance")
    return _cost_explorer


@router.get("/health")
async def cost_explorer_health():
    """
    Health check for AWS Cost Explorer integration.

    Verifies that:
    - boto3 is available
    - AWS credentials are configured
    - Cost Explorer client can be initialized

    Returns:
        Health status and configuration info
    """
    try:
        cost_explorer = get_cost_explorer()

        health_status = {
            "status": "healthy" if cost_explorer.boto3_available else "degraded",
            "boto3_available": cost_explorer.boto3_available,
            "region": cost_explorer.region,
            "client_initialized": cost_explorer.ce_client is not None,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if not cost_explorer.boto3_available:
            health_status["message"] = "boto3 not available - install with: pip install boto3"
        elif cost_explorer.ce_client is None:
            health_status["message"] = (
                "Cost Explorer client failed to initialize - check AWS credentials"
            )
        else:
            health_status["message"] = "Cost Explorer integration is healthy"

        return health_status

    except Exception as e:
        logger.error(f"Cost Explorer health check failed: {e}", exc_info=True)
        return {"status": "unhealthy", "error": str(e), "timestamp": datetime.utcnow().isoformat()}


@router.post("/anomalies", response_model=CostAnomalyResponse)
@limiter_with_key.limit("30/minute")
async def detect_cost_anomalies(
    request: Request, cost_request: CostAnomalyRequest, api_key: str = Depends(verify_api_key)
) -> CostAnomalyResponse:
    """
    Detect AWS cost anomalies using Cost Explorer API.

    This endpoint analyzes AWS spending patterns using AWS Cost Anomaly Detection
    service, which uses machine learning to identify unusual spending patterns.

    **Capabilities**:
    - Detect unexpected cost spikes
    - Identify service-level anomalies
    - Analyze root causes
    - Filter by minimum impact threshold
    - Filter by specific AWS services

    **Requires**:
    - AWS credentials with `ce:GetAnomalies` permission
    - AWS Cost Anomaly Detection enabled in your account

    **Rate Limit**: 30 requests/minute

    Args:
        cost_request: CostAnomalyRequest with analysis parameters

    Returns:
        CostAnomalyResponse with detected anomalies and analysis

    Raises:
        HTTPException: If Cost Explorer is unavailable or request fails
    """
    start_time = time.time()

    try:
        logger.info(
            f"Cost anomaly detection request: days_back={cost_request.days_back}, "
            f"min_impact=${cost_request.min_impact}, service_filter={cost_request.service_filter}"
        )

        # Get Cost Explorer instance
        cost_explorer = get_cost_explorer()

        if not cost_explorer.boto3_available:
            raise HTTPException(
                status_code=503, detail="AWS Cost Explorer not available - boto3 not installed"
            )

        # Get anomalies from AWS
        anomalies_data = await cost_explorer.get_cost_anomalies(
            days_back=cost_request.days_back,
            min_impact=cost_request.min_impact,
            max_results=cost_request.max_results,
        )

        # Filter by service if requested
        if cost_request.service_filter:
            anomalies_data = [
                a
                for a in anomalies_data
                if cost_request.service_filter.lower() in a.get("service", "").lower()
            ]
            logger.info(
                f"Filtered to {len(anomalies_data)} anomalies matching service: {cost_request.service_filter}"
            )

        # Calculate total impact
        total_impact = sum(a.get("impact_amount", 0) for a in anomalies_data)

        # Convert to Pydantic models
        anomalies = [
            CostAnomaly(
                anomaly_id=a.get("anomaly_id", "unknown"),
                service=a.get("service", "Unknown"),
                impact_amount=a.get("impact_amount", 0.0),
                impact_percentage=a.get("impact_percentage", 0.0),
                start_date=a.get("start_date", ""),
                end_date=a.get("end_date", ""),
                root_cause=a.get("root_cause"),
                dimension_value=a.get("dimension_value"),
                feedback_status=a.get("feedback_status", "NONE"),
            )
            for a in anomalies_data
        ]

        # Generate basic recommendations
        recommendations = []
        if anomalies:
            recommendations.append("Review cost allocation tags for affected services")
            recommendations.append("Enable AWS Budget alerts for proactive monitoring")

            # Service-specific recommendations
            services = {a.service for a in anomalies}
            if "Amazon EC2" in services:
                recommendations.append("Consider Reserved Instances or Savings Plans for EC2")
            if "Amazon RDS" in services:
                recommendations.append("Review RDS instance sizing and utilization")

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Cost anomaly detection completed in {duration_ms:.2f}ms: "
            f"{len(anomalies)} anomalies found, total impact: ${total_impact:.2f}"
        )

        return CostAnomalyResponse(
            status="success",
            anomalies=anomalies,
            total_impact=round(total_impact, 2),
            anomaly_count=len(anomalies),
            analysis=None,  # Can be enhanced with Claude AI analysis
            recommendations=recommendations,
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cost anomaly detection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Cost anomaly detection failed: {str(e)}")


@router.post("/daily-costs", response_model=DailyCostsResponse)
@limiter_with_key.limit("30/minute")
async def get_daily_costs(
    request: Request, cost_request: DailyCostsRequest, api_key: str = Depends(verify_api_key)
) -> DailyCostsResponse:
    """
    Get daily cost breakdown by service or other dimension.

    This endpoint retrieves historical cost data from AWS Cost Explorer,
    broken down by the specified dimension (service, account, region, etc.).

    **Capabilities**:
    - Daily or monthly cost trends
    - Service-level cost breakdown
    - Top cost contributors identification
    - Custom time ranges (up to 365 days)

    **Requires**:
    - AWS credentials with `ce:GetCostAndUsage` permission

    **Rate Limit**: 30 requests/minute

    Args:
        cost_request: DailyCostsRequest with analysis parameters

    Returns:
        DailyCostsResponse with daily cost breakdown and top services

    Raises:
        HTTPException: If Cost Explorer is unavailable or request fails
    """
    start_time = time.time()

    try:
        logger.info(
            f"Daily costs request: days_back={cost_request.days_back}, "
            f"group_by={cost_request.group_by}, granularity={cost_request.granularity}"
        )

        # Get Cost Explorer instance
        cost_explorer = get_cost_explorer()

        if not cost_explorer.boto3_available:
            raise HTTPException(
                status_code=503, detail="AWS Cost Explorer not available - boto3 not installed"
            )

        # Get daily costs from AWS
        costs_data = await cost_explorer.get_daily_costs(
            days_back=cost_request.days_back,
            group_by=cost_request.group_by,
            granularity=cost_request.granularity,
        )

        if not costs_data:
            raise HTTPException(status_code=500, detail="Failed to retrieve cost data from AWS")

        # Convert to Pydantic models
        daily_breakdown = [
            DailyCostBreakdown(date=day["date"], total=day["total"], services=day["services"])
            for day in costs_data.get("daily_breakdown", [])
        ]

        top_services = [
            ServiceCost(service=svc["service"], cost=svc["cost"])
            for svc in costs_data.get("top_services", [])
        ]

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Daily costs retrieved in {duration_ms:.2f}ms: "
            f"${costs_data.get('total_cost', 0):.2f} total, "
            f"{len(daily_breakdown)} days, {len(top_services)} services"
        )

        return DailyCostsResponse(
            status="success",
            total_cost=costs_data.get("total_cost", 0.0),
            start_date=costs_data.get("start_date", ""),
            end_date=costs_data.get("end_date", ""),
            daily_breakdown=daily_breakdown,
            top_services=top_services,
            granularity=costs_data.get("granularity", "DAILY"),
            group_by=costs_data.get("group_by", "SERVICE"),
            timestamp=datetime.utcnow(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Daily costs retrieval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Daily costs retrieval failed: {str(e)}")
