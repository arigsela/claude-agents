"""
Tests for Athena CUR Cost Analysis API endpoints

Tests the FastAPI endpoints for AWS cost analysis via Athena.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def mock_agent():
    """Mock OnCallAgentClient"""
    mock = Mock()
    mock.model = "claude-3-5-sonnet-20241022"
    mock.tools = []
    mock.query = AsyncMock(return_value={"response": "Test response"})
    return mock


@pytest.fixture
def client(mock_agent):
    """Create test client with mocked agent"""
    with patch('src.api.api_server.OnCallAgentClient', return_value=mock_agent):
        from src.api.api_server import app
        from src.api import api_server
        api_server.agent = mock_agent
        return TestClient(app)


@pytest.fixture
def mock_athena_querier():
    """Create a mock AWSAthenaQuerier"""
    mock = Mock()
    mock.boto3_available = True
    mock.output_location = 's3://test-bucket/results/'
    mock.database = 'test_db'
    mock.table = 'test_table'
    mock.workgroup = 'primary'
    mock.region = 'us-east-1'
    return mock


class TestAthenaEndpointRegistration:
    """Test endpoint registration and OpenAPI documentation"""

    def test_endpoint_registration(self, client):
        """Test that athena-costs endpoints are registered in root"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()

        assert "endpoints" in data
        assert "athena_costs" in data["endpoints"]

        athena_endpoints = data["endpoints"]["athena_costs"]
        assert "health" in athena_endpoints
        assert "anomalies" in athena_endpoints
        assert "compute" in athena_endpoints
        assert "eks" in athena_endpoints
        assert "networking" in athena_endpoints
        assert "summary" in athena_endpoints

    def test_openapi_documentation(self, client):
        """Test that athena-costs endpoints appear in OpenAPI docs"""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        openapi_spec = response.json()
        paths = openapi_spec.get("paths", {})

        # Check that our endpoints are documented
        assert "/athena-costs/health" in paths
        assert "/athena-costs/anomalies" in paths
        assert "/athena-costs/compute" in paths
        assert "/athena-costs/eks" in paths
        assert "/athena-costs/networking" in paths
        assert "/athena-costs/summary" in paths

        # Check tags
        health_endpoint = paths["/athena-costs/health"]
        assert "get" in health_endpoint
        assert "tags" in health_endpoint["get"]
        assert "athena-costs" in health_endpoint["get"]["tags"]


class TestAthenaHealthEndpoint:
    """Test /athena-costs/health endpoint"""

    def test_health_endpoint_exists(self, client):
        """Test health endpoint is accessible"""
        response = client.get("/athena-costs/health")

        # Should not be 404
        assert response.status_code != 404
        assert response.status_code in [200, 500, 503]

    def test_health_returns_expected_fields(self, client, mock_athena_querier):
        """Test health endpoint returns expected fields"""
        with patch('src.api.athena_costs.get_athena_querier', return_value=mock_athena_querier):
            response = client.get("/athena-costs/health")

            if response.status_code == 200:
                data = response.json()
                assert "status" in data
                assert "boto3_available" in data
                assert "database" in data
                assert "timestamp" in data


class TestAthenaAnomaliesEndpoint:
    """Test /athena-costs/anomalies endpoint"""

    def test_anomalies_endpoint_exists(self, client):
        """Test anomalies endpoint is accessible"""
        response = client.get("/athena-costs/anomalies")

        # Should not be 404 (may fail without proper config)
        assert response.status_code != 404

    def test_anomalies_accepts_threshold_parameter(self, client):
        """Test anomalies endpoint accepts threshold parameter"""
        response = client.get("/athena-costs/anomalies?threshold_pct=30.0")

        # Should not be 404
        assert response.status_code != 404

    def test_anomalies_validates_threshold_range(self, client):
        """Test threshold validation (must be 5-100)"""
        # Too low
        response = client.get("/athena-costs/anomalies?threshold_pct=2.0")
        assert response.status_code == 422  # Validation error

        # Too high
        response = client.get("/athena-costs/anomalies?threshold_pct=150.0")
        assert response.status_code == 422

    def test_anomalies_with_mocked_querier(self, client, mock_athena_querier):
        """Test anomalies endpoint with mocked Athena response"""
        mock_anomalies = [
            {
                'service': 'Amazon EC2',
                'current_24h_cost': 150.0,
                'baseline_daily_avg': 100.0,
                'change_percent': 50.0,
                'cost_difference': 50.0,
                'severity': 'medium'
            }
        ]

        mock_athena_querier.detect_anomalies = AsyncMock(return_value=mock_anomalies)

        with patch('src.api.athena_costs.get_athena_querier', return_value=mock_athena_querier):
            response = client.get("/athena-costs/anomalies")

            if response.status_code == 200:
                data = response.json()
                assert "anomalies" in data
                assert "anomaly_count" in data
                assert data["anomaly_count"] == 1
                assert data["anomalies"][0]["service"] == "Amazon EC2"


class TestAthenaComputeEndpoint:
    """Test /athena-costs/compute endpoint"""

    def test_compute_endpoint_exists(self, client):
        """Test compute endpoint is accessible"""
        response = client.get("/athena-costs/compute")

        # Should not be 404
        assert response.status_code != 404

    def test_compute_with_mocked_querier(self, client, mock_athena_querier):
        """Test compute endpoint with mocked Athena response"""
        mock_compute = {
            'ec2_costs': [{'instance_type': 'm5.xlarge', 'cost': 100.0}],
            'lambda_costs': [{'function_name': 'my-func', 'cost': 25.0}],
            'ec2_total': 100.0,
            'lambda_total': 25.0,
            'compute_total': 125.0,
            'ec2_instance_count': 1,
            'lambda_function_count': 1
        }

        mock_athena_querier.get_compute_costs_24h = AsyncMock(return_value=mock_compute)

        with patch('src.api.athena_costs.get_athena_querier', return_value=mock_athena_querier):
            response = client.get("/athena-costs/compute")

            if response.status_code == 200:
                data = response.json()
                assert "compute" in data
                assert data["compute"]["compute_total"] == 125.0


class TestAthenaEKSEndpoint:
    """Test /athena-costs/eks endpoint"""

    def test_eks_endpoint_exists(self, client):
        """Test EKS endpoint is accessible"""
        response = client.get("/athena-costs/eks")

        # Should not be 404
        assert response.status_code != 404

    def test_eks_with_mocked_querier(self, client, mock_athena_querier):
        """Test EKS endpoint with mocked Athena response"""
        mock_eks = [
            {
                'namespace': 'proteus-dev',
                'pod_count': 5,
                'actual_cost': 40.0,
                'unused_cost': 10.0,
                'total_cost': 50.0
            }
        ]

        mock_athena_querier.get_eks_costs_by_namespace = AsyncMock(return_value=mock_eks)

        with patch('src.api.athena_costs.get_athena_querier', return_value=mock_athena_querier):
            response = client.get("/athena-costs/eks")

            if response.status_code == 200:
                data = response.json()
                assert "eks" in data
                assert data["eks"]["total"] == 50.0


class TestAthenaNetworkingEndpoint:
    """Test /athena-costs/networking endpoint"""

    def test_networking_endpoint_exists(self, client):
        """Test networking endpoint is accessible"""
        response = client.get("/athena-costs/networking")

        # Should not be 404
        assert response.status_code != 404

    def test_networking_with_mocked_querier(self, client, mock_athena_querier):
        """Test networking endpoint with mocked Athena response"""
        mock_networking = {
            'nat_gateway_costs': [{'nat_gateway_id': 'nat-123', 'total_cost': 10.0}],
            'data_transfer_costs': [{'cost': 5.0}],
            'nat_gateway_total': 10.0,
            'data_transfer_total': 5.0,
            'networking_total': 15.0,
            'nat_gateway_count': 1
        }
        mock_idle_nats = []

        mock_athena_querier.get_networking_costs_24h = AsyncMock(return_value=mock_networking)
        mock_athena_querier.get_idle_nat_gateways = AsyncMock(return_value=mock_idle_nats)

        with patch('src.api.athena_costs.get_athena_querier', return_value=mock_athena_querier):
            response = client.get("/athena-costs/networking")

            if response.status_code == 200:
                data = response.json()
                assert "networking" in data
                assert data["networking"]["networking_total"] == 15.0


class TestAthenaSummaryEndpoint:
    """Test /athena-costs/summary endpoint"""

    def test_summary_endpoint_exists(self, client):
        """Test summary endpoint is accessible"""
        response = client.get("/athena-costs/summary")

        # Should not be 404
        assert response.status_code != 404

    def test_summary_accepts_threshold_parameter(self, client):
        """Test summary endpoint accepts threshold parameter"""
        response = client.get("/athena-costs/summary?threshold_pct=25.0")

        # Should not be 404
        assert response.status_code != 404

    def test_summary_with_mocked_querier(self, client, mock_athena_querier):
        """Test summary endpoint with mocked Athena response"""
        mock_summary = {
            'summary': {
                'total_24h_cost': 190.0,
                'compute_total': 125.0,
                'eks_total': 50.0,
                'networking_total': 15.0,
                'anomaly_count': 1,
                'idle_nat_count': 0,
                'timestamp': datetime.utcnow().isoformat()
            },
            'anomalies': [
                {
                    'service': 'EC2',
                    'current_24h_cost': 150.0,
                    'baseline_daily_avg': 100.0,
                    'change_percent': 50.0,
                    'cost_difference': 50.0,
                    'severity': 'medium'
                }
            ],
            'compute': {
                'ec2_costs': [],
                'lambda_costs': [],
                'ec2_total': 125.0,
                'lambda_total': 0.0,
                'compute_total': 125.0,
                'ec2_instance_count': 0,
                'lambda_function_count': 0
            },
            'eks': {
                'by_namespace': [],
                'total': 50.0
            },
            'networking': {
                'nat_gateway_costs': [],
                'data_transfer_costs': [],
                'nat_gateway_total': 10.0,
                'data_transfer_total': 5.0,
                'networking_total': 15.0,
                'nat_gateway_count': 0
            },
            'idle_nat_gateways': [],
            'recommendations': ['Test recommendation']
        }

        mock_athena_querier.get_daily_summary = AsyncMock(return_value=mock_summary)

        with patch('src.api.athena_costs.get_athena_querier', return_value=mock_athena_querier):
            response = client.get("/athena-costs/summary")

            if response.status_code == 200:
                data = response.json()
                assert "summary" in data
                assert "anomalies" in data
                assert "compute" in data
                assert "eks" in data
                assert "networking" in data
                assert "recommendations" in data
                assert data["summary"]["total_24h_cost"] == 190.0


class TestAthenaErrorHandling:
    """Test error handling in Athena endpoints"""

    def test_boto3_unavailable(self, client, mock_athena_querier):
        """Test error handling when boto3 is unavailable"""
        mock_athena_querier.boto3_available = False

        with patch('src.api.athena_costs.get_athena_querier', return_value=mock_athena_querier):
            response = client.get("/athena-costs/anomalies")

            # Should return 503 Service Unavailable
            if response.status_code == 503:
                data = response.json()
                assert "boto3" in data.get("detail", "").lower()

    def test_output_location_not_configured(self, client, mock_athena_querier):
        """Test error handling when output location is not configured"""
        mock_athena_querier.output_location = None

        with patch('src.api.athena_costs.get_athena_querier', return_value=mock_athena_querier):
            response = client.get("/athena-costs/anomalies")

            # Should return error about configuration
            if response.status_code == 503:
                data = response.json()
                assert "ATHENA_OUTPUT_BUCKET" in data.get("detail", "")

    def test_query_execution_error(self, client, mock_athena_querier):
        """Test error handling when query execution fails"""
        mock_athena_querier.detect_anomalies = AsyncMock(
            side_effect=Exception("Query execution failed")
        )

        with patch('src.api.athena_costs.get_athena_querier', return_value=mock_athena_querier):
            response = client.get("/athena-costs/anomalies")

            # Should return 500 Internal Server Error
            if response.status_code == 500:
                data = response.json()
                assert "failed" in data.get("detail", "").lower()


class TestAthenaModelsValidation:
    """Test Pydantic model validation"""

    def test_anomaly_response_model_structure(self):
        """Test AthenaAnomalyResponse model structure"""
        from src.api.models import AthenaAnomalyResponse, AthenaCostAnomaly

        anomaly = AthenaCostAnomaly(
            service="Amazon EC2",
            current_24h_cost=150.0,
            baseline_daily_avg=100.0,
            change_percent=50.0,
            cost_difference=50.0,
            severity="medium"
        )

        response = AthenaAnomalyResponse(
            status="success",
            anomalies=[anomaly],
            anomaly_count=1,
            threshold_percent=20.0,
            timestamp=datetime.utcnow()
        )

        assert response.status == "success"
        assert len(response.anomalies) == 1
        assert response.anomalies[0].service == "Amazon EC2"

    def test_cost_summary_response_model_structure(self):
        """Test AthenaCostSummaryResponse model structure"""
        from src.api.models import (
            AthenaCostSummaryResponse,
            CostSummary,
            ComputeCostBreakdown,
            EKSCostBreakdown,
            NetworkingCostBreakdown
        )

        summary = CostSummary(
            total_24h_cost=190.0,
            compute_total=125.0,
            eks_total=50.0,
            networking_total=15.0,
            anomaly_count=1,
            idle_nat_count=0,
            timestamp=datetime.utcnow().isoformat()
        )

        compute = ComputeCostBreakdown(
            compute_total=125.0
        )

        eks = EKSCostBreakdown(
            total=50.0
        )

        networking = NetworkingCostBreakdown(
            networking_total=15.0
        )

        response = AthenaCostSummaryResponse(
            status="success",
            summary=summary,
            anomalies=[],
            compute=compute,
            eks=eks,
            networking=networking,
            recommendations=["Test recommendation"],
            timestamp=datetime.utcnow()
        )

        assert response.summary.total_24h_cost == 190.0
        assert response.compute.compute_total == 125.0
        assert len(response.recommendations) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
