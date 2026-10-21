"""
Pydantic models for API request/response validation.

Uses Pydantic v2 syntax (ConfigDict, field_validator).
Includes RFC 1123 validation for Kubernetes resource names.
"""

import os
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .validation import validate_k8s_namespace, validate_k8s_pod_name


class QueryRequest(BaseModel):
    """Request model for /query endpoint"""

    prompt: str = Field(
        ..., min_length=1, max_length=10000, description="Query or instruction for the agent"
    )
    namespace: str | None = Field(
        default="default", max_length=253, description="Kubernetes namespace context"
    )
    context: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional context for the query"
    )
    session_id: str | None = Field(
        default=None, description="Session ID for multi-turn conversations"
    )
    system_prompt: str | None = Field(
        default=None,
        max_length=10000,
        description="Optional system prompt to prepend to the agent's built-in prompt",
    )

    @field_validator("namespace")
    @classmethod
    def validate_namespace_format(cls, v: str | None) -> str | None:
        """Validate namespace follows RFC 1123 DNS label format."""
        if v is not None:
            return validate_k8s_namespace(v)
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "prompt": "What services are currently experiencing issues?",
                "namespace": "chores-tracker-backend",
                "context": {"user": "ari", "source": "n8n-chat"},
                "system_prompt": "Focus on memory-related issues and provide metrics.",
            }
        }
    )


class IncidentRequest(BaseModel):
    """Request model for /incident endpoint"""

    service: str = Field(..., min_length=1, max_length=255, description="Service name")
    namespace: str = Field(default="default", max_length=253, description="Kubernetes namespace")
    error: str = Field(
        ..., min_length=1, max_length=5000, description="Error message or description"
    )
    pod: str | None = Field(default=None, max_length=253, description="Pod name")
    restart_count: int = Field(default=0, ge=0, description="Number of pod restarts")
    cluster: str = Field(
        default_factory=lambda: os.getenv("K8S_CONTEXT", "default"),
        description="Kubernetes cluster name",
    )

    @field_validator("namespace")
    @classmethod
    def validate_namespace_format(cls, v: str) -> str:
        """Validate namespace follows RFC 1123 DNS label format."""
        return validate_k8s_namespace(v)

    @field_validator("pod")
    @classmethod
    def validate_pod_format(cls, v: str | None) -> str | None:
        """Validate pod name follows RFC 1123 DNS label format."""
        if v is not None:
            return validate_k8s_pod_name(v)
        return v

    @field_validator("cluster")
    @classmethod
    def validate_cluster(cls, v: str) -> str:
        """Validate cluster against ALLOWED_CLUSTERS environment variable."""
        allowed_env = os.getenv("ALLOWED_CLUSTERS", "default")
        allowed_clusters = [c.strip() for c in allowed_env.split(",")]
        if v not in allowed_clusters:
            raise ValueError(f"Only {allowed_clusters} cluster(s) allowed. Got: {v}")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "service": "chores-tracker-backend",
                "namespace": "chores-tracker-backend",
                "error": "CrashLoopBackOff",
                "pod": "chores-tracker-backend-7b9c8d6f4-xyz12",
                "restart_count": 5,
                "cluster": "default",
            }
        }
    )


class SessionRequest(BaseModel):
    """Request model for session management."""

    user_id: str = Field(..., min_length=1, max_length=255, description="User identifier")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Optional metadata for the session"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "ari",
                "metadata": {"source": "n8n-chat", "team": "homelab"},
            }
        }
    )


class ResponseMessage(BaseModel):
    """Individual response message"""

    type: str = Field(..., description="Message type (text, tool_use, etc.)")
    content: str = Field(..., description="Message content")


class QueryResponse(BaseModel):
    """Response model for /query endpoint."""

    status: str = Field(..., description="Request status")
    session_id: str | None = Field(None, description="Session ID if applicable")
    responses: list[ResponseMessage] = Field(..., description="Agent response messages")
    query: str = Field(..., description="Original query")
    duration_ms: float | None = Field(None, description="Query processing duration in milliseconds")
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "responses": [
                    {
                        "type": "text",
                        "content": "Currently monitoring 5 services in chores-tracker-backend namespace...",
                    }
                ],
                "query": "What services are you monitoring?",
                "duration_ms": 1234.56,
                "timestamp": "2025-06-19T10:30:00Z",
            }
        }
    )


class IncidentResponse(BaseModel):
    """Response model for /incident endpoint."""

    status: str = Field(..., description="Incident processing status")
    alert: dict[str, Any] = Field(..., description="Original alert data")
    analysis: list[ResponseMessage] = Field(..., description="Agent's incident analysis")
    severity: str | None = Field(
        None, description="Incident severity (critical, high, medium, low)"
    )
    duration_ms: float | None = Field(None, description="Analysis duration in milliseconds")
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "analyzed",
                "alert": {
                    "service": "chores-tracker-backend",
                    "namespace": "chores-tracker-backend",
                    "error": "CrashLoopBackOff",
                },
                "analysis": [
                    {"type": "text", "content": "Detected CrashLoopBackOff in chores-tracker-backend..."}
                ],
                "severity": "high",
                "duration_ms": 3456.78,
                "timestamp": "2025-06-19T10:30:00Z",
            }
        }
    )


class ErrorResponse(BaseModel):
    """Error response model."""

    status: str = Field(default="error", description="Status indicator")
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: str | None = Field(None, description="Additional error details")
    timestamp: datetime = Field(default_factory=datetime.now, description="Error timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "error",
                "error": "ValidationError",
                "message": "Invalid cluster specified",
                "detail": "Cluster not in ALLOWED_CLUSTERS",
                "timestamp": "2025-06-19T10:30:00Z",
            }
        }
    )


class SessionResponse(BaseModel):
    """Response model for session operations."""

    status: str = Field(..., description="Operation status")
    session_id: str = Field(..., description="Session identifier")
    user_id: str = Field(..., description="User identifier")
    created_at: datetime = Field(..., description="Session creation time")
    last_accessed: datetime | None = Field(None, description="Last access time")
    conversation_history: list[dict[str, Any]] | None = Field(
        default_factory=list, description="Conversation history for the session"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "ari",
                "created_at": "2025-06-19T10:00:00Z",
                "last_accessed": "2025-06-19T10:30:00Z",
                "conversation_history": [],
            }
        }
    )


# Hermes ChartData Models


class ChartdataMetricsResponse(BaseModel):
    """Response model for Hermes chartdata metrics."""

    namespace: str = Field(..., description="Kubernetes namespace")
    deployment: str = Field(default="hermes-app-chartdata", description="Deployment name")

    # Resource metrics
    cpu_usage: float | None = Field(
        None, description="CPU usage in cores (absolute value, not percentage)"
    )
    memory_usage: float | None = Field(
        None, description="Memory usage in bytes (absolute value, not percentage)"
    )
    pod_count: int = Field(..., description="Number of running pods")

    # Performance metrics (from logs)
    avg_snowflake_duration: float | None = Field(
        None, description="Average Snowflake query duration in seconds"
    )
    p95_snowflake_duration: float | None = Field(
        None, description="P95 Snowflake query duration in seconds"
    )
    max_snowflake_duration: float | None = Field(
        None, description="Max Snowflake query duration in seconds"
    )
    avg_total_duration: float | None = Field(
        None, description="Average total query duration in seconds"
    )

    # Query counts
    query_count: int = Field(..., description="Total queries in time window")
    error_count: int = Field(default=0, description="Total errors in time window")

    time_window_minutes: int = Field(..., description="Time window for metrics")
    timestamp: datetime = Field(default_factory=datetime.now, description="Metrics timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "namespace": "chores-tracker-backend",
                "deployment": "chores-tracker-backend",
                "cpu_usage": 0.45,
                "memory_usage": 2147483648,
                "pod_count": 3,
                "avg_snowflake_duration": 1.25,
                "p95_snowflake_duration": 2.18,
                "max_snowflake_duration": 3.45,
                "avg_total_duration": 1.85,
                "query_count": 142,
                "error_count": 2,
                "time_window_minutes": 60,
                "timestamp": "2025-10-21T12:00:00Z",
            }
        }
    )


class ChartdataHealthResponse(BaseModel):
    """Response model for Hermes chartdata health check."""

    healthy: bool = Field(..., description="Overall health status")
    status: str = Field(..., description="Health status: healthy, degraded, unhealthy")
    checks: dict[str, bool | None] = Field(..., description="Individual health check results")
    alerts: list[str] = Field(default_factory=list, description="Active alerts")
    recommendations: list[str] = Field(
        default_factory=list, description="Recommendations for improvements"
    )
    timestamp: datetime = Field(default_factory=datetime.now, description="Health check timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "healthy": True,
                "status": "healthy",
                "checks": {
                    "pods_running": True,
                    "cpu_healthy": True,
                    "memory_healthy": True,
                    "snowflake_performance": True,
                    "error_rate_ok": True,
                },
                "alerts": [],
                "recommendations": [],
                "timestamp": "2025-10-21T12:00:00Z",
            }
        }
    )


class SlowQueryInfo(BaseModel):
    """Model for slow query information."""

    query_id: str | None = Field(None, description="Query identifier hash")
    client: str | None = Field(None, description="Client name")
    snowflake_duration: float = Field(..., description="Snowflake query duration in seconds")
    total_duration: float | None = Field(None, description="Total query duration in seconds")
    timestamp: str | None = Field(None, description="Query timestamp")
    log_line: str | None = Field(None, description="Original log line excerpt")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query_id": "2ea4a5a7",
                "client": "mma_carvana",
                "snowflake_duration": 45.8,
                "total_duration": 48.2,
                "timestamp": "10/21/2025 03:33:43 PM",
                "log_line": "Chartdata non_pii PID 10 QueryEngine v1.6.3...",
            }
        }
    )


class ChartdataAnalysisResponse(BaseModel):
    """Response model for Hermes chartdata performance analysis."""

    namespace: str = Field(..., description="Kubernetes namespace analyzed")
    time_window_minutes: int = Field(..., description="Time window analyzed")
    metrics: ChartdataMetricsResponse = Field(..., description="Current metrics")
    slow_query_count: int = Field(..., description="Number of slow queries detected")
    analysis: str = Field(..., description="AI-generated performance analysis")
    timestamp: datetime = Field(default_factory=datetime.now, description="Analysis timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "namespace": "chores-tracker-backend",
                "time_window_minutes": 60,
                "metrics": {"namespace": "chores-tracker-backend", "pod_count": 2, "query_count": 142},
                "slow_query_count": 5,
                "analysis": "Performance analysis indicates normal operation with occasional slow queries...",
                "timestamp": "2025-10-21T12:00:00Z",
            }
        }
    )


# ============================================================================
# AWS Cost Explorer Models
# ============================================================================


class CostAnomalyRequest(BaseModel):
    """Request model for /cost-explorer/anomalies endpoint."""

    days_back: int = Field(
        default=7, ge=1, le=90, description="Number of days to look back for anomalies"
    )
    min_impact: float = Field(
        default=10.0, ge=0.0, description="Minimum dollar impact to include (USD)"
    )
    service_filter: str | None = Field(
        default=None, description="Filter by AWS service (e.g., 'Amazon EC2', 'Amazon RDS')"
    )
    max_results: int = Field(
        default=50, ge=1, le=100, description="Maximum number of anomalies to return"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "days_back": 7,
                "min_impact": 10.0,
                "service_filter": "Amazon EC2",
                "max_results": 50,
            }
        }
    )


class CostAnomaly(BaseModel):
    """Individual cost anomaly detected by AWS"""

    anomaly_id: str = Field(..., description="Unique anomaly identifier")
    service: str = Field(..., description="AWS service name")
    impact_amount: float = Field(..., description="Dollar impact (USD)")
    impact_percentage: float = Field(..., description="Percentage increase")
    start_date: str = Field(..., description="Anomaly start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="Anomaly end date (YYYY-MM-DD)")
    root_cause: str | None = Field(None, description="Root cause description")
    dimension_value: str | None = Field(None, description="Dimension value (region, account, etc.)")
    feedback_status: str | None = Field(None, description="Feedback status (NONE, YES, NO)")


class CostAnomalyResponse(BaseModel):
    """Response model for cost anomaly detection."""

    status: str = Field(default="success", description="Response status")
    anomalies: list[CostAnomaly] = Field(
        default_factory=list, description="List of detected anomalies"
    )
    total_impact: float = Field(default=0.0, description="Total dollar impact across all anomalies")
    anomaly_count: int = Field(default=0, description="Number of anomalies detected")
    analysis: str | None = Field(None, description="AI-generated analysis of anomalies")
    recommendations: list[str] = Field(
        default_factory=list, description="Cost optimization recommendations"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "anomalies": [
                    {
                        "anomaly_id": "abc-123-def",
                        "service": "Amazon EC2",
                        "impact_amount": 125.50,
                        "impact_percentage": 45.2,
                        "start_date": "2025-01-15",
                        "end_date": "2025-01-16",
                        "root_cause": "Increased instance usage in us-east-1",
                        "dimension_value": "us-east-1",
                        "feedback_status": "NONE",
                    }
                ],
                "total_impact": 125.50,
                "anomaly_count": 1,
                "analysis": "Detected EC2 cost spike due to increased instance usage...",
                "recommendations": [
                    "Review instance scaling policies",
                    "Consider Reserved Instances for steady-state workloads",
                ],
                "timestamp": "2025-01-16T10:00:00Z",
            }
        }
    )


class DailyCostsRequest(BaseModel):
    """Request model for /cost-explorer/daily-costs endpoint."""

    days_back: int = Field(default=30, ge=1, le=365, description="Number of days to analyze")
    group_by: str = Field(
        default="SERVICE",
        description="Dimension to group by (SERVICE, LINKED_ACCOUNT, REGION, etc.)",
    )
    granularity: str = Field(default="DAILY", description="Time granularity (DAILY, MONTHLY)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"days_back": 30, "group_by": "SERVICE", "granularity": "DAILY"}
        }
    )


class ServiceCost(BaseModel):
    """Cost breakdown for a single service"""

    service: str = Field(..., description="AWS service name")
    cost: float = Field(..., description="Total cost (USD)")


class DailyCostBreakdown(BaseModel):
    """Cost breakdown for a single day"""

    date: str = Field(..., description="Date (YYYY-MM-DD)")
    total: float = Field(..., description="Total cost for the day (USD)")
    services: dict[str, float] = Field(default_factory=dict, description="Cost by service")


class DailyCostsResponse(BaseModel):
    """Response model for daily cost analysis."""

    status: str = Field(default="success", description="Response status")
    total_cost: float = Field(default=0.0, description="Total cost across all days")
    start_date: str = Field(..., description="Analysis start date")
    end_date: str = Field(..., description="Analysis end date")
    daily_breakdown: list[DailyCostBreakdown] = Field(
        default_factory=list, description="Daily cost breakdown"
    )
    top_services: list[ServiceCost] = Field(
        default_factory=list, description="Top services by cost"
    )
    granularity: str = Field(..., description="Time granularity used")
    group_by: str = Field(..., description="Grouping dimension used")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "total_cost": 1250.75,
                "start_date": "2024-12-15",
                "end_date": "2025-01-15",
                "daily_breakdown": [
                    {
                        "date": "2025-01-15",
                        "total": 42.50,
                        "services": {"Amazon EC2": 25.00, "Amazon RDS": 17.50},
                    }
                ],
                "top_services": [
                    {"service": "Amazon EC2", "cost": 750.00},
                    {"service": "Amazon RDS", "cost": 500.75},
                ],
                "granularity": "DAILY",
                "group_by": "SERVICE",
                "timestamp": "2025-01-16T10:00:00Z",
            }
        }
    )


# ============================================================================
# Image Tags Models (DEVOPS-7737)
# ============================================================================


class ImageTagResponse(BaseModel):
    """Response model for /images/tags endpoint.

    Returns the currently deployed image information for a service's
    primary container in Kubernetes.
    """

    service_name: str = Field(
        ..., description="Service name from the request (matches service_mapping.yaml)"
    )
    deployment_name: str = Field(..., description="Kubernetes deployment name")
    namespace: str = Field(..., description="Kubernetes namespace where the deployment runs")
    container_name: str = Field(
        ..., description="Name of the primary container (first container in spec)"
    )
    current_image_url: str = Field(
        ...,
        description="Full image URL including registry and tag (e.g., YOUR_AWS_ACCOUNT.dkr.ecr.us-east-2.amazonaws.com/chores-tracker-backend:v1.2.3)",
    )
    pod_count: int = Field(..., ge=0, description="Number of ready pods for this deployment")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp when the image info was retrieved"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "service_name": "chores-tracker-backend",
                "deployment_name": "chores-tracker-backend",
                "namespace": "chores-tracker-backend",
                "container_name": "app",
                "current_image_url": "YOUR_AWS_ACCOUNT.dkr.ecr.us-east-2.amazonaws.com/chores-tracker-backend:v1.2.3",
                "pod_count": 3,
                "timestamp": "2025-11-14T10:30:00Z",
            }
        }
    )


# ============================================================================
# Athena CUR Cost Analysis Models
# ============================================================================


class AthenaQueryRequest(BaseModel):
    """Request model for Athena-based cost analysis."""

    threshold_pct: float = Field(
        default=20.0, ge=5.0, le=100.0, description="Anomaly threshold percentage (default: 20%)"
    )
    include_details: bool = Field(
        default=True, description="Include resource-level details in response"
    )

    model_config = ConfigDict(
        json_schema_extra={"example": {"threshold_pct": 20.0, "include_details": True}}
    )


class AthenaCostAnomaly(BaseModel):
    """Individual cost anomaly detected via CUR analysis."""

    service: str = Field(..., description="AWS service name")
    current_24h_cost: float = Field(..., description="Cost in last 24 hours (USD)")
    baseline_daily_avg: float = Field(..., description="7-day daily average cost (USD)")
    change_percent: float = Field(..., description="Percentage change from baseline")
    cost_difference: float = Field(..., description="Absolute cost difference (USD)")
    severity: str = Field(..., description="Anomaly severity: low, medium, high")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "service": "Amazon EC2",
                "current_24h_cost": 150.00,
                "baseline_daily_avg": 100.00,
                "change_percent": 50.0,
                "cost_difference": 50.00,
                "severity": "medium",
            }
        }
    )


class EC2CostRecord(BaseModel):
    """EC2 instance cost record"""

    usage_date: str | None = Field(None, description="Date of usage")
    instance_type: str | None = Field(None, description="EC2 instance type")
    instance_id: str | None = Field(None, description="EC2 instance ID")
    cost: float = Field(..., description="Cost in USD")
    usage_hours: float | None = Field(None, description="Usage hours")


class LambdaCostRecord(BaseModel):
    """Lambda function cost record"""

    function_name: str | None = Field(None, description="Lambda function name")
    cost: float = Field(..., description="Cost in USD")
    invocations: int | None = Field(None, description="Number of invocations")
    duration_gb_seconds: float | None = Field(None, description="GB-seconds duration")


class ComputeCostBreakdown(BaseModel):
    """Compute costs (EC2 + Lambda) breakdown"""

    ec2_costs: list[EC2CostRecord] = Field(default_factory=list, description="EC2 instance costs")
    lambda_costs: list[LambdaCostRecord] = Field(
        default_factory=list, description="Lambda function costs"
    )
    ec2_total: float = Field(default=0.0, description="Total EC2 cost (USD)")
    lambda_total: float = Field(default=0.0, description="Total Lambda cost (USD)")
    compute_total: float = Field(default=0.0, description="Total compute cost (USD)")
    ec2_instance_count: int = Field(default=0, description="Number of EC2 instances")
    lambda_function_count: int = Field(default=0, description="Number of Lambda functions")


class EKSNamespaceCost(BaseModel):
    """EKS costs by namespace"""

    namespace: str | None = Field(None, description="Kubernetes namespace")
    pod_count: int | None = Field(None, description="Number of pods")
    actual_cost: float = Field(default=0.0, description="Actual cost (USD)")
    unused_cost: float = Field(default=0.0, description="Unused cost (USD)")
    total_cost: float = Field(default=0.0, description="Total cost (USD)")


class EKSCostBreakdown(BaseModel):
    """EKS/Container costs breakdown"""

    by_namespace: list[EKSNamespaceCost] = Field(
        default_factory=list, description="Costs by namespace"
    )
    total: float = Field(default=0.0, description="Total EKS cost (USD)")


class NATGatewayCostRecord(BaseModel):
    """NAT Gateway cost record"""

    nat_gateway_id: str | None = Field(None, description="NAT Gateway ID")
    az: str | None = Field(None, description="Availability Zone")
    hourly_cost: float | None = Field(None, description="Hourly charges (USD)")
    data_cost: float | None = Field(None, description="Data processing cost (USD)")
    gb_processed: float | None = Field(None, description="GB processed")
    total_cost: float = Field(default=0.0, description="Total cost (USD)")


class DataTransferCostRecord(BaseModel):
    """Data transfer cost record"""

    service: str | None = Field(None, description="AWS service")
    transfer_type: str | None = Field(None, description="Transfer type")
    from_location: str | None = Field(None, description="Source location")
    to_location: str | None = Field(None, description="Destination location")
    cost: float = Field(default=0.0, description="Cost (USD)")
    gb_transferred: float | None = Field(None, description="GB transferred")


class NetworkingCostBreakdown(BaseModel):
    """Networking costs (NAT Gateway + Data Transfer) breakdown"""

    nat_gateway_costs: list[NATGatewayCostRecord] = Field(
        default_factory=list, description="NAT Gateway costs"
    )
    data_transfer_costs: list[DataTransferCostRecord] = Field(
        default_factory=list, description="Data transfer costs"
    )
    nat_gateway_total: float = Field(default=0.0, description="Total NAT Gateway cost (USD)")
    data_transfer_total: float = Field(default=0.0, description="Total data transfer cost (USD)")
    networking_total: float = Field(default=0.0, description="Total networking cost (USD)")
    nat_gateway_count: int = Field(default=0, description="Number of NAT Gateways")


class IdleNATGateway(BaseModel):
    """Potentially idle NAT Gateway"""

    nat_gateway_id: str | None = Field(None, description="NAT Gateway ID")
    az: str | None = Field(None, description="Availability Zone")
    hourly_cost: float = Field(default=0.0, description="Hourly cost (USD)")
    bytes_processed: int | None = Field(None, description="Bytes processed in 24h")
    recommendation: str | None = Field(None, description="Optimization recommendation")


class CostSummary(BaseModel):
    """24-hour cost summary"""

    total_24h_cost: float = Field(default=0.0, description="Total cost for last 24 hours")
    compute_total: float = Field(default=0.0, description="Total compute cost")
    eks_total: float = Field(default=0.0, description="Total EKS cost")
    networking_total: float = Field(default=0.0, description="Total networking cost")
    anomaly_count: int = Field(default=0, description="Number of anomalies detected")
    idle_nat_count: int = Field(default=0, description="Number of idle NAT Gateways")
    timestamp: str = Field(..., description="Summary timestamp (ISO format)")


class AthenaCostSummaryResponse(BaseModel):
    """Response model for /athena-costs/summary endpoint."""

    status: str = Field(default="success", description="Response status")
    summary: CostSummary = Field(..., description="Cost summary")
    anomalies: list[AthenaCostAnomaly] = Field(
        default_factory=list, description="Detected anomalies"
    )
    compute: ComputeCostBreakdown = Field(..., description="Compute cost breakdown")
    eks: EKSCostBreakdown = Field(..., description="EKS cost breakdown")
    networking: NetworkingCostBreakdown = Field(..., description="Networking cost breakdown")
    idle_nat_gateways: list[IdleNATGateway] = Field(
        default_factory=list, description="Idle NAT Gateways"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Cost optimization recommendations"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "summary": {
                    "total_24h_cost": 190.0,
                    "compute_total": 125.0,
                    "eks_total": 50.0,
                    "networking_total": 15.0,
                    "anomaly_count": 1,
                    "idle_nat_count": 0,
                    "timestamp": "2025-01-22T10:00:00Z",
                },
                "anomalies": [
                    {
                        "service": "Amazon EC2",
                        "current_24h_cost": 150.0,
                        "baseline_daily_avg": 100.0,
                        "change_percent": 50.0,
                        "cost_difference": 50.0,
                        "severity": "medium",
                    }
                ],
                "recommendations": ["Review cost allocation tags for affected services"],
                "timestamp": "2025-01-22T10:00:00Z",
            }
        }
    )


class AthenaAnomalyResponse(BaseModel):
    """Response model for /athena-costs/anomalies endpoint."""

    status: str = Field(default="success", description="Response status")
    anomalies: list[AthenaCostAnomaly] = Field(
        default_factory=list, description="Detected anomalies"
    )
    anomaly_count: int = Field(default=0, description="Number of anomalies")
    threshold_percent: float = Field(..., description="Threshold used for detection")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "anomalies": [
                    {
                        "service": "Amazon EC2",
                        "current_24h_cost": 150.0,
                        "baseline_daily_avg": 100.0,
                        "change_percent": 50.0,
                        "cost_difference": 50.0,
                        "severity": "medium",
                    }
                ],
                "anomaly_count": 1,
                "threshold_percent": 20.0,
                "timestamp": "2025-01-22T10:00:00Z",
            }
        }
    )


class AthenaComputeResponse(BaseModel):
    """Response model for /athena-costs/compute endpoint"""

    status: str = Field(default="success", description="Response status")
    compute: ComputeCostBreakdown = Field(..., description="Compute cost breakdown")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")


class AthenaEKSResponse(BaseModel):
    """Response model for /athena-costs/eks endpoint"""

    status: str = Field(default="success", description="Response status")
    eks: EKSCostBreakdown = Field(..., description="EKS cost breakdown")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")


class AthenaNetworkingResponse(BaseModel):
    """Response model for /athena-costs/networking endpoint"""

    status: str = Field(default="success", description="Response status")
    networking: NetworkingCostBreakdown = Field(..., description="Networking cost breakdown")
    idle_nat_gateways: list[IdleNATGateway] = Field(
        default_factory=list, description="Idle NAT Gateways"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
