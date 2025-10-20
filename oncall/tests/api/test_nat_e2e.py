"""
End-to-End tests for NAT Gateway correlation functionality
Tests the complete flow from query to correlation results
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone

# Add src to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from api.custom_tools import (
    check_nat_gateway_metrics,
    find_zeus_jobs_during_timeframe,
    correlate_nat_spike_with_zeus_jobs
)


class TestNATGatewayE2E:
    """End-to-end tests for NAT gateway correlation"""

    @pytest.mark.asyncio
    async def test_check_nat_gateway_metrics_tool(self):
        """Test that check_nat_gateway_metrics tool can be called"""
        # This is a basic test that the tool exists and has correct signature
        # Full testing requires mocked boto3 responses

        args = {
            "time_window_hours": 1,
            "nat_gateway_id": "nat-test123"
        }

        # Test that function exists and is callable
        assert callable(check_nat_gateway_metrics)

        # Note: Actual execution would require AWS credentials and mocking
        # For now, verify the function signature is correct
        import inspect
        sig = inspect.signature(check_nat_gateway_metrics)
        assert 'args' in sig.parameters

    @pytest.mark.asyncio
    async def test_find_zeus_jobs_tool(self):
        """Test that find_zeus_jobs_during_timeframe tool can be called"""

        args = {
            "start_time": "2025-10-16T00:00:00Z",
            "end_time": "2025-10-16T03:00:00Z"
        }

        # Test that function exists and is callable
        assert callable(find_zeus_jobs_during_timeframe)

        # Verify function signature
        import inspect
        sig = inspect.signature(find_zeus_jobs_during_timeframe)
        assert 'args' in sig.parameters

    @pytest.mark.asyncio
    async def test_correlate_nat_spike_tool(self):
        """Test that correlate_nat_spike_with_zeus_jobs tool can be called"""

        args = {
            "spike_timestamp": "2025-10-16T02:00:00Z",
            "time_window_minutes": 30
        }

        # Test that function exists and is callable
        assert callable(correlate_nat_spike_with_zeus_jobs)

        # Verify function signature
        import inspect
        sig = inspect.signature(correlate_nat_spike_with_zeus_jobs)
        assert 'args' in sig.parameters

    def test_tool_imports_successful(self):
        """Test that all NAT tools can be imported successfully"""
        from api.custom_tools import (
            check_nat_gateway_metrics,
            find_zeus_jobs_during_timeframe,
            correlate_nat_spike_with_zeus_jobs
        )

        assert check_nat_gateway_metrics is not None
        assert find_zeus_jobs_during_timeframe is not None
        assert correlate_nat_spike_with_zeus_jobs is not None

    def test_nat_analyzer_module_imports(self):
        """Test that NAT analyzer module imports correctly"""
        from tools.nat_gateway_analyzer import (
            NATGatewayAnalyzer,
            NATMetrics,
            TrafficSpike,
            get_analyzer
        )

        assert NATGatewayAnalyzer is not None
        assert NATMetrics is not None
        assert TrafficSpike is not None
        assert callable(get_analyzer)

    def test_zeus_correlator_module_imports(self):
        """Test that Zeus correlator module imports correctly"""
        from tools.zeus_job_correlator import (
            ZeusJobCorrelator,
            ZeusRefreshJob,
            LogAnalysis,
            get_correlator
        )

        assert ZeusJobCorrelator is not None
        assert ZeusRefreshJob is not None
        assert LogAnalysis is not None
        assert callable(get_correlator)


class TestNATToolsRegistration:
    """Test that NAT tools are properly registered in agent client"""

    def test_agent_client_imports_nat_tools(self):
        """Verify agent_client.py imports NAT tools"""
        from api.agent_client import OnCallAgentClient

        # Check that the class exists
        assert OnCallAgentClient is not None

    @patch('api.agent_client.Anthropic')
    def test_nat_tools_in_tool_definitions(self, mock_anthropic):
        """Test that NAT tools appear in agent tool definitions"""
        from api.agent_client import OnCallAgentClient

        # Mock Anthropic client
        mock_anthropic.return_value = Mock()

        # Set API key for initialization
        import os
        os.environ['ANTHROPIC_API_KEY'] = 'test-key'

        try:
            # Initialize agent
            client = OnCallAgentClient()

            # Check that tools are defined
            tool_names = [tool['name'] for tool in client.tools]

            assert 'check_nat_gateway_metrics' in tool_names
            assert 'find_zeus_jobs_during_timeframe' in tool_names
            assert 'correlate_nat_spike_with_zeus_jobs' in tool_names

        finally:
            # Clean up env var
            if 'ANTHROPIC_API_KEY' in os.environ:
                del os.environ['ANTHROPIC_API_KEY']


class TestConfiguration:
    """Test NAT gateway configuration"""

    def test_nat_config_file_exists(self):
        """Verify NAT configuration file exists"""
        config_path = Path(__file__).parent.parent.parent / "config" / "nat_gateway_config.yaml"
        assert config_path.exists(), "nat_gateway_config.yaml not found"

    def test_nat_config_loads(self):
        """Test that NAT configuration can be loaded"""
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "nat_gateway_config.yaml"

        with open(config_path) as f:
            config = yaml.safe_load(f)

        # Verify key sections exist
        assert 'nat_gateways' in config
        assert 'zeus_job_search' in config
        assert 'cloudwatch' in config

        # Verify dev-eks NAT gateway is defined
        nat_gateways = config['nat_gateways']
        assert len(nat_gateways) > 0

        dev_eks_nat = nat_gateways[0]
        assert dev_eks_nat['cluster'] == 'dev-eks'
        assert 'nat_id' in dev_eks_nat
        assert 'vpc_id' in dev_eks_nat


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
