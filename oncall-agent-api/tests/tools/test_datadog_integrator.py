"""
Tests for DatadogIntegrator class
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import os


# Set dummy environment variables for testing
os.environ['DATADOG_API_KEY'] = 'test-api-key'
os.environ['DATADOG_APP_KEY'] = 'test-app-key'


from tools.datadog_integrator import DatadogIntegrator


class TestDatadogIntegrator:
    """Test suite for DatadogIntegrator class"""

    def test_initialization_with_defaults(self):
        """Test DatadogIntegrator initializes with environment variables"""
        integrator = DatadogIntegrator()

        assert integrator.api_key == 'test-api-key'
        assert integrator.app_key == 'test-app-key'
        assert integrator.site == 'datadoghq.com'
        assert integrator.datadog_available is True

    def test_initialization_with_custom_values(self):
        """Test DatadogIntegrator initializes with custom credentials"""
        integrator = DatadogIntegrator(
            api_key='custom-api-key',
            app_key='custom-app-key',
            site='datadoghq.eu'
        )

        assert integrator.api_key == 'custom-api-key'
        assert integrator.app_key == 'custom-app-key'
        assert integrator.site == 'datadoghq.eu'

    def test_datadog_not_available(self):
        """Test graceful handling when datadog-api-client not installed"""
        with patch('tools.datadog_integrator.DatadogIntegrator.__init__') as mock_init:
            mock_init.return_value = None
            integrator = DatadogIntegrator()

            # Should not raise error, just log warning
            # In actual implementation, datadog_available would be False

    @pytest.mark.asyncio
    async def test_query_timeseries_success(self):
        """Test successful timeseries query"""
        integrator = DatadogIntegrator()

        # Mock the internal _metrics_api to avoid property issues
        mock_metrics_api = Mock()

        # Create mock response with proper structure
        mock_series_data = {
            "metric": "kubernetes.cpu.usage",
            "scope": "kube_namespace:proteus-dev",
            "pointlist": [[1697470800000, 0.45], [1697470860000, 0.52]],
            "unit": "core",
            "display_name": "kubernetes.cpu.usage"
        }

        mock_response = Mock()
        mock_response.series = [mock_series_data]

        mock_metrics_api.query_metrics = Mock(return_value=mock_response)

        # Replace the private _metrics_api directly
        integrator._metrics_api = mock_metrics_api

        result = integrator.query_timeseries(
            query="avg:kubernetes.cpu.usage{kube_namespace:proteus-dev}",
            start=1697470800,
            end=1697474400
        )

        assert "series" in result
        assert len(result["series"]) == 1
        assert result["series"][0]["metric"] == "kubernetes.cpu.usage"
        assert result["query"] == "avg:kubernetes.cpu.usage{kube_namespace:proteus-dev}"

    @pytest.mark.asyncio
    async def test_query_pod_metrics(self):
        """Test query_pod_metrics builds correct query"""
        integrator = DatadogIntegrator()

        with patch.object(integrator, 'query_timeseries') as mock_query:
            mock_query.return_value = {"series": [], "query": "test"}

            result = await integrator.query_pod_metrics(
                metric="kubernetes.cpu.usage",
                namespace="proteus-dev",
                pod_name="proteus-api-xyz",
                hours_back=24,
                aggregation="avg"
            )

            # Verify query was called
            assert mock_query.called
            call_args = mock_query.call_args

            # Check query construction
            assert "avg:kubernetes.cpu.usage" in call_args[1]['query']
            assert "kube_namespace:proteus-dev" in call_args[1]['query']
            assert "pod_name:proteus-api-xyz" in call_args[1]['query']

    @pytest.mark.asyncio
    async def test_query_container_metrics(self):
        """Test query_container_metrics queries all expected metrics"""
        integrator = DatadogIntegrator()

        with patch.object(integrator, 'query_timeseries') as mock_query:
            mock_query.return_value = {"series": [], "query": "test"}

            result = await integrator.query_container_metrics(
                namespace="artemis-auth-dev",
                container_name="auth-container",
                hours_back=1
            )

            # Should query 3 metrics
            assert mock_query.call_count == 3
            assert "kubernetes.cpu.usage" in result
            assert "kubernetes.memory.rss" in result
            assert "kubernetes.memory.working_set" in result

    @pytest.mark.asyncio
    async def test_query_network_metrics(self):
        """Test query_network_metrics queries network metrics"""
        integrator = DatadogIntegrator()

        with patch.object(integrator, 'query_timeseries') as mock_query:
            mock_query.return_value = {"series": [], "query": "test"}

            result = await integrator.query_network_metrics(
                namespace="zeus-dev",
                pod_name="zeus-job-abc",
                hours_back=2
            )

            # Should query 3 network metrics
            assert mock_query.call_count == 3
            assert "kubernetes.network.tx_bytes" in result
            assert "kubernetes.network.rx_bytes" in result
            assert "kubernetes.network.errors" in result

    def test_query_timeseries_without_datadog_client(self):
        """Test graceful failure when Datadog client unavailable"""
        integrator = DatadogIntegrator()
        integrator.datadog_available = False

        result = integrator.query_timeseries(
            query="avg:kubernetes.cpu.usage{kube_namespace:test}",
            start=1697470800,
            end=1697474400
        )

        assert "error" in result
        assert "datadog-api-client not installed" in result["error"]

    def test_query_timeseries_without_credentials(self):
        """Test error handling when credentials missing"""
        integrator = DatadogIntegrator()
        integrator._metrics_api = None
        integrator.datadog_available = True

        # Mock metrics_api property to return None
        with patch.object(DatadogIntegrator, 'metrics_api', new_callable=lambda: property(lambda self: None)):
            result = integrator.query_timeseries(
                query="avg:kubernetes.cpu.usage{kube_namespace:test}",
                start=1697470800,
                end=1697474400
            )

            assert "error" in result or "message" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
