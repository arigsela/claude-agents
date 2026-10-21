"""
Tests for AWSAthenaQuerier class

Tests the Athena CUR query functionality for cost analysis and anomaly detection.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime, timedelta
import os
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestAWSAthenaQuerierInit:
    """Test AWSAthenaQuerier initialization"""

    def test_initialization_with_defaults(self):
        """Test AWSAthenaQuerier initializes with default values"""
        with patch.dict(os.environ, {}, clear=False):
            from tools.aws_athena_querier import AWSAthenaQuerier

            querier = AWSAthenaQuerier()

            assert querier.database == 'athenacurcfn_c_u_r_athena'
            assert querier.table == 'c_u_r_athena'
            assert querier.workgroup == 'primary'
            assert querier.region == 'us-east-1'

    def test_initialization_with_env_vars(self):
        """Test AWSAthenaQuerier uses environment variables"""
        env_vars = {
            'ATHENA_DATABASE': 'test_db',
            'ATHENA_TABLE': 'test_table',
            'ATHENA_WORKGROUP': 'test_workgroup',
            'ATHENA_OUTPUT_BUCKET': 's3://test-bucket/',
            'AWS_REGION': 'us-west-2'
        }

        with patch.dict(os.environ, env_vars, clear=False):
            from tools.aws_athena_querier import AWSAthenaQuerier

            querier = AWSAthenaQuerier()

            assert querier.database == 'test_db'
            assert querier.table == 'test_table'
            assert querier.workgroup == 'test_workgroup'
            assert querier.output_location == 's3://test-bucket/'
            assert querier.region == 'us-west-2'

    def test_initialization_with_custom_values(self):
        """Test AWSAthenaQuerier accepts custom parameter values"""
        from tools.aws_athena_querier import AWSAthenaQuerier

        querier = AWSAthenaQuerier(
            database='custom_db',
            table='custom_table',
            workgroup='custom_workgroup',
            output_location='s3://custom-bucket/',
            region='eu-west-1'
        )

        assert querier.database == 'custom_db'
        assert querier.table == 'custom_table'
        assert querier.workgroup == 'custom_workgroup'
        assert querier.output_location == 's3://custom-bucket/'
        assert querier.region == 'eu-west-1'

    def test_lazy_client_initialization(self):
        """Test Athena client is lazily initialized"""
        from tools.aws_athena_querier import AWSAthenaQuerier

        querier = AWSAthenaQuerier()

        # Client should not be initialized yet
        assert querier._athena_client is None

        # Mock boto3 for client access
        with patch('boto3.client') as mock_client:
            mock_client.return_value = Mock()

            # Access the client property
            client = querier.athena_client

            assert client is not None
            assert querier._athena_client is not None
            mock_client.assert_called_once_with('athena', region_name=querier.region)


class TestAWSAthenaQuerierQueryExecution:
    """Test query execution methods"""

    @pytest.fixture
    def querier(self):
        """Create AWSAthenaQuerier with mocked boto3"""
        from tools.aws_athena_querier import AWSAthenaQuerier

        querier = AWSAthenaQuerier(
            output_location='s3://test-bucket/results/'
        )
        querier.boto3_available = True
        return querier

    def test_build_query_replaces_placeholders(self, querier):
        """Test _build_query replaces database and table placeholders"""
        template = "SELECT * FROM ${database}.${table} WHERE cost > 0"

        result = querier._build_query(template)

        assert '${database}' not in result
        assert '${table}' not in result
        assert querier.database in result
        assert querier.table in result

    @pytest.mark.asyncio
    async def test_start_query_execution_success(self, querier):
        """Test successful query execution start"""
        mock_client = Mock()
        mock_client.start_query_execution.return_value = {
            'QueryExecutionId': 'test-execution-id-123'
        }
        querier._athena_client = mock_client

        result = await querier._start_query_execution("SELECT 1")

        assert result == 'test-execution-id-123'
        mock_client.start_query_execution.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_query_execution_no_output_location(self, querier):
        """Test error when output location not configured"""
        querier.output_location = None
        querier._athena_client = Mock()

        with pytest.raises(ValueError, match="ATHENA_OUTPUT_BUCKET not configured"):
            await querier._start_query_execution("SELECT 1")

    @pytest.mark.asyncio
    async def test_start_query_execution_no_client(self):
        """Test error when Athena client not available"""
        from tools.aws_athena_querier import AWSAthenaQuerier

        querier = AWSAthenaQuerier()
        querier.boto3_available = False

        with pytest.raises(ValueError, match="Athena client not available"):
            await querier._start_query_execution("SELECT 1")

    @pytest.mark.asyncio
    async def test_wait_for_query_completion_success(self, querier):
        """Test waiting for query completion"""
        mock_client = Mock()
        mock_client.get_query_execution.return_value = {
            'QueryExecution': {
                'Status': {
                    'State': 'SUCCEEDED'
                }
            }
        }
        querier._athena_client = mock_client

        result = await querier._wait_for_query_completion('test-id')

        assert result['Status']['State'] == 'SUCCEEDED'

    @pytest.mark.asyncio
    async def test_wait_for_query_completion_failed(self, querier):
        """Test error handling when query fails"""
        mock_client = Mock()
        mock_client.get_query_execution.return_value = {
            'QueryExecution': {
                'Status': {
                    'State': 'FAILED',
                    'StateChangeReason': 'Syntax error in SQL'
                }
            }
        }
        querier._athena_client = mock_client

        with pytest.raises(RuntimeError, match="FAILED"):
            await querier._wait_for_query_completion('test-id')

    @pytest.mark.asyncio
    async def test_wait_for_query_completion_timeout(self, querier):
        """Test timeout handling"""
        mock_client = Mock()
        mock_client.get_query_execution.return_value = {
            'QueryExecution': {
                'Status': {
                    'State': 'RUNNING'
                }
            }
        }
        mock_client.stop_query_execution = Mock()
        querier._athena_client = mock_client
        querier.MAX_QUERY_TIMEOUT_SECONDS = 0.1  # Very short timeout
        querier.POLL_INTERVAL_SECONDS = 0.05

        with pytest.raises(TimeoutError, match="timed out"):
            await querier._wait_for_query_completion('test-id')

    @pytest.mark.asyncio
    async def test_get_query_results_success(self, querier):
        """Test fetching and parsing query results"""
        mock_client = Mock()
        mock_client.get_query_results.return_value = {
            'ResultSet': {
                'ResultSetMetadata': {
                    'ColumnInfo': [
                        {'Name': 'service'},
                        {'Name': 'cost'}
                    ]
                },
                'Rows': [
                    {'Data': [{'VarCharValue': 'service'}, {'VarCharValue': 'cost'}]},  # Header
                    {'Data': [{'VarCharValue': 'EC2'}, {'VarCharValue': '125.50'}]},
                    {'Data': [{'VarCharValue': 'Lambda'}, {'VarCharValue': '45.25'}]}
                ]
            }
        }
        querier._athena_client = mock_client

        results = await querier._get_query_results('test-id')

        assert len(results) == 2
        assert results[0]['service'] == 'EC2'
        assert results[0]['cost'] == 125.50
        assert results[1]['service'] == 'Lambda'
        assert results[1]['cost'] == 45.25

    @pytest.mark.asyncio
    async def test_execute_query_full_flow(self, querier):
        """Test complete query execution flow"""
        mock_client = Mock()

        # Mock start execution
        mock_client.start_query_execution.return_value = {
            'QueryExecutionId': 'test-id'
        }

        # Mock get execution (for wait)
        mock_client.get_query_execution.return_value = {
            'QueryExecution': {
                'Status': {'State': 'SUCCEEDED'}
            }
        }

        # Mock get results
        mock_client.get_query_results.return_value = {
            'ResultSet': {
                'ResultSetMetadata': {
                    'ColumnInfo': [{'Name': 'value'}]
                },
                'Rows': [
                    {'Data': [{'VarCharValue': 'value'}]},
                    {'Data': [{'VarCharValue': 'test_result'}]}
                ]
            }
        }

        querier._athena_client = mock_client

        results = await querier.execute_query("SELECT 'test' as value")

        assert len(results) == 1
        assert results[0]['value'] == 'test_result'


class TestAWSAthenaQuerierCostQueries:
    """Test cost-specific query methods"""

    @pytest.fixture
    def querier(self):
        """Create AWSAthenaQuerier with mocked execute_query"""
        from tools.aws_athena_querier import AWSAthenaQuerier

        querier = AWSAthenaQuerier(
            output_location='s3://test-bucket/results/'
        )
        querier.boto3_available = True
        return querier

    @pytest.mark.asyncio
    async def test_get_ec2_costs_24h(self, querier):
        """Test EC2 costs query"""
        mock_results = [
            {
                'usage_date': '2025-01-21',
                'instance_type': 'm5.xlarge',
                'instance_id': 'i-1234567890abcdef0',
                'cost': 12.50,
                'usage_hours': 24.0
            }
        ]

        with patch.object(querier, 'execute_query', return_value=mock_results) as mock_exec:
            results = await querier.get_ec2_costs_24h()

            assert len(results) == 1
            assert results[0]['instance_type'] == 'm5.xlarge'

            # Verify SQL query contains correct filter
            call_args = mock_exec.call_args[0][0]
            assert 'Amazon Elastic Compute Cloud' in call_args
            assert 'DATE_ADD' in call_args

    @pytest.mark.asyncio
    async def test_get_lambda_costs_24h(self, querier):
        """Test Lambda costs query"""
        mock_results = [
            {
                'function_name': 'my-function',
                'cost': 5.25,
                'invocations': 10000,
                'duration_gb_seconds': 500.0
            }
        ]

        with patch.object(querier, 'execute_query', return_value=mock_results) as mock_exec:
            results = await querier.get_lambda_costs_24h()

            assert len(results) == 1
            assert results[0]['function_name'] == 'my-function'

            call_args = mock_exec.call_args[0][0]
            assert 'AWS Lambda' in call_args

    @pytest.mark.asyncio
    async def test_get_compute_costs_24h(self, querier):
        """Test combined compute costs"""
        ec2_results = [{'cost': 100.0}]
        lambda_results = [{'cost': 25.0}]

        with patch.object(querier, 'get_ec2_costs_24h', return_value=ec2_results):
            with patch.object(querier, 'get_lambda_costs_24h', return_value=lambda_results):
                results = await querier.get_compute_costs_24h()

                assert results['ec2_total'] == 100.0
                assert results['lambda_total'] == 25.0
                assert results['compute_total'] == 125.0
                assert results['ec2_instance_count'] == 1
                assert results['lambda_function_count'] == 1

    @pytest.mark.asyncio
    async def test_get_eks_costs_24h(self, querier):
        """Test EKS costs query with Split Cost Allocation"""
        mock_results = [
            {
                'cluster_arn': 'arn:aws:eks:us-east-1:123456789:cluster/dev-eks',
                'namespace': 'proteus-dev',
                'pod_name': 'proteus-api-abc123',
                'actual_cost': 5.50,
                'unused_cost': 1.25,
                'total_cost': 6.75
            }
        ]

        with patch.object(querier, 'execute_query', return_value=mock_results) as mock_exec:
            results = await querier.get_eks_costs_24h()

            assert len(results) == 1
            assert results[0]['namespace'] == 'proteus-dev'

            call_args = mock_exec.call_args[0][0]
            assert 'AmazonEKS' in call_args
            assert 'split_line_item' in call_args

    @pytest.mark.asyncio
    async def test_get_nat_gateway_costs_24h(self, querier):
        """Test NAT Gateway costs query"""
        mock_results = [
            {
                'nat_gateway_id': 'nat-0123456789abcdef0',
                'az': 'us-east-1a',
                'hourly_cost': 1.08,
                'data_cost': 2.50,
                'gb_processed': 55.5,
                'total_cost': 3.58
            }
        ]

        with patch.object(querier, 'execute_query', return_value=mock_results) as mock_exec:
            results = await querier.get_nat_gateway_costs_24h()

            assert len(results) == 1
            assert results[0]['nat_gateway_id'] == 'nat-0123456789abcdef0'

            call_args = mock_exec.call_args[0][0]
            assert 'NatGateway' in call_args

    @pytest.mark.asyncio
    async def test_get_networking_costs_24h(self, querier):
        """Test combined networking costs"""
        nat_results = [{'total_cost': 10.0}]
        transfer_results = [{'cost': 5.0}]

        with patch.object(querier, 'get_nat_gateway_costs_24h', return_value=nat_results):
            with patch.object(querier, 'get_data_transfer_costs_24h', return_value=transfer_results):
                results = await querier.get_networking_costs_24h()

                assert results['nat_gateway_total'] == 10.0
                assert results['data_transfer_total'] == 5.0
                assert results['networking_total'] == 15.0


class TestAWSAthenaQuerierAnomalyDetection:
    """Test anomaly detection methods"""

    @pytest.fixture
    def querier(self):
        """Create AWSAthenaQuerier with mocked execute_query"""
        from tools.aws_athena_querier import AWSAthenaQuerier

        querier = AWSAthenaQuerier(
            output_location='s3://test-bucket/results/'
        )
        querier.boto3_available = True
        return querier

    @pytest.mark.asyncio
    async def test_detect_anomalies_with_results(self, querier):
        """Test anomaly detection with actual anomalies"""
        mock_results = [
            {
                'service': 'Amazon EC2',
                'current_24h_cost': 150.0,
                'baseline_daily_avg': 100.0,
                'change_percent': 50.0,
                'cost_difference': 50.0
            },
            {
                'service': 'Amazon RDS',
                'current_24h_cost': 250.0,
                'baseline_daily_avg': 100.0,
                'change_percent': 150.0,
                'cost_difference': 150.0
            }
        ]

        with patch.object(querier, 'execute_query', return_value=mock_results):
            results = await querier.detect_anomalies(threshold_percent=20.0)

            assert len(results) == 2
            # Check severity classification
            assert results[0]['severity'] == 'medium'  # 50% increase
            assert results[1]['severity'] == 'high'    # 150% increase

    @pytest.mark.asyncio
    async def test_detect_anomalies_empty_results(self, querier):
        """Test anomaly detection with no anomalies"""
        with patch.object(querier, 'execute_query', return_value=[]):
            results = await querier.detect_anomalies()

            assert len(results) == 0

    @pytest.mark.asyncio
    async def test_detect_anomalies_custom_threshold(self, querier):
        """Test anomaly detection with custom threshold"""
        with patch.object(querier, 'execute_query', return_value=[]) as mock_exec:
            await querier.detect_anomalies(threshold_percent=50.0)

            call_args = mock_exec.call_args[0][0]
            assert '50.0' in call_args or '50' in call_args

    @pytest.mark.asyncio
    async def test_get_idle_nat_gateways(self, querier):
        """Test idle NAT Gateway detection"""
        mock_results = [
            {
                'nat_gateway_id': 'nat-idle123',
                'az': 'us-east-1a',
                'hourly_cost': 1.08,
                'bytes_processed': 512  # Very low
            }
        ]

        with patch.object(querier, 'execute_query', return_value=mock_results):
            results = await querier.get_idle_nat_gateways()

            assert len(results) == 1
            assert 'recommendation' in results[0]
            assert 'removing' in results[0]['recommendation'].lower()

    @pytest.mark.asyncio
    async def test_severity_classification(self, querier):
        """Test severity is correctly assigned based on change percentage"""
        mock_results = [
            {'service': 'A', 'current_24h_cost': 125, 'baseline_daily_avg': 100,
             'change_percent': 25.0, 'cost_difference': 25},  # low
            {'service': 'B', 'current_24h_cost': 175, 'baseline_daily_avg': 100,
             'change_percent': 75.0, 'cost_difference': 75},  # medium
            {'service': 'C', 'current_24h_cost': 250, 'baseline_daily_avg': 100,
             'change_percent': 150.0, 'cost_difference': 150}  # high
        ]

        with patch.object(querier, 'execute_query', return_value=mock_results):
            results = await querier.detect_anomalies()

            severities = {r['service']: r['severity'] for r in results}
            assert severities['A'] == 'low'
            assert severities['B'] == 'medium'
            assert severities['C'] == 'high'


class TestAWSAthenaQuerierDailySummary:
    """Test daily summary generation"""

    @pytest.fixture
    def querier(self):
        """Create AWSAthenaQuerier with mocked methods"""
        from tools.aws_athena_querier import AWSAthenaQuerier

        querier = AWSAthenaQuerier(
            output_location='s3://test-bucket/results/'
        )
        querier.boto3_available = True
        return querier

    @pytest.mark.asyncio
    async def test_get_daily_summary(self, querier):
        """Test comprehensive daily summary"""
        mock_anomalies = [
            {'service': 'EC2', 'change_percent': 50.0, 'severity': 'medium'}
        ]
        mock_compute = {
            'ec2_costs': [{'cost': 100.0}],
            'lambda_costs': [{'cost': 25.0}],
            'ec2_total': 100.0,
            'lambda_total': 25.0,
            'compute_total': 125.0,
            'ec2_instance_count': 1,
            'lambda_function_count': 1
        }
        mock_eks = [{'namespace': 'test', 'total_cost': 50.0}]
        mock_networking = {
            'nat_gateway_costs': [{'total_cost': 10.0}],
            'data_transfer_costs': [{'cost': 5.0}],
            'nat_gateway_total': 10.0,
            'data_transfer_total': 5.0,
            'networking_total': 15.0,
            'nat_gateway_count': 1
        }
        mock_idle_nats = []

        with patch.object(querier, 'detect_anomalies', return_value=mock_anomalies):
            with patch.object(querier, 'get_compute_costs_24h', return_value=mock_compute):
                with patch.object(querier, 'get_eks_costs_by_namespace', return_value=mock_eks):
                    with patch.object(querier, 'get_networking_costs_24h', return_value=mock_networking):
                        with patch.object(querier, 'get_idle_nat_gateways', return_value=mock_idle_nats):
                            result = await querier.get_daily_summary()

        # Check summary
        assert 'summary' in result
        assert result['summary']['compute_total'] == 125.0
        assert result['summary']['eks_total'] == 50.0
        assert result['summary']['networking_total'] == 15.0
        assert result['summary']['anomaly_count'] == 1

        # Check data sections
        assert 'anomalies' in result
        assert 'compute' in result
        assert 'eks' in result
        assert 'networking' in result
        assert 'recommendations' in result

    @pytest.mark.asyncio
    async def test_get_daily_summary_eks_failure(self, querier):
        """Test daily summary handles EKS query failure gracefully"""
        mock_anomalies = []
        mock_compute = {
            'ec2_costs': [],
            'lambda_costs': [],
            'compute_total': 0.0
        }
        mock_networking = {
            'nat_gateway_costs': [],
            'data_transfer_costs': [],
            'networking_total': 0.0
        }

        with patch.object(querier, 'detect_anomalies', return_value=mock_anomalies):
            with patch.object(querier, 'get_compute_costs_24h', return_value=mock_compute):
                with patch.object(querier, 'get_eks_costs_by_namespace',
                                side_effect=Exception("Split Cost Allocation not enabled")):
                    with patch.object(querier, 'get_networking_costs_24h', return_value=mock_networking):
                        with patch.object(querier, 'get_idle_nat_gateways', return_value=[]):
                            result = await querier.get_daily_summary()

        # Should still return result with empty EKS data
        assert result['eks']['total'] == 0
        assert result['eks']['by_namespace'] == []

    def test_generate_recommendations_with_anomalies(self, querier):
        """Test recommendations include anomaly warnings"""
        anomalies = [
            {'service': 'EC2', 'severity': 'high', 'change_percent': 150.0}
        ]
        idle_nats = []
        compute = {'ec2_costs': [], 'lambda_costs': []}
        networking = {'nat_gateway_total': 0}

        recommendations = querier._generate_recommendations(
            anomalies, idle_nats, compute, networking
        )

        assert any('anomal' in r.lower() for r in recommendations)

    def test_generate_recommendations_with_idle_nats(self, querier):
        """Test recommendations include idle NAT warnings"""
        anomalies = []
        idle_nats = [
            {'nat_gateway_id': 'nat-123', 'hourly_cost': 1.08}
        ]
        compute = {'ec2_costs': [], 'lambda_costs': []}
        networking = {'nat_gateway_total': 0}

        recommendations = querier._generate_recommendations(
            anomalies, idle_nats, compute, networking
        )

        assert any('idle' in r.lower() or 'nat' in r.lower() for r in recommendations)

    def test_generate_recommendations_no_issues(self, querier):
        """Test recommendations show clean status when no issues"""
        recommendations = querier._generate_recommendations(
            [], [], {'ec2_costs': []}, {'nat_gateway_total': 0}
        )

        assert any('no significant' in r.lower() or '✅' in r for r in recommendations)


class TestAWSAthenaQuerierEdgeCases:
    """Test edge cases and error handling"""

    def test_boto3_not_available(self):
        """Test graceful handling when boto3 not installed"""
        with patch.dict('sys.modules', {'boto3': None}):
            # This import would fail if boto3 check fails
            from tools.aws_athena_querier import AWSAthenaQuerier

            querier = AWSAthenaQuerier()
            # boto3_available should be set based on import success

    @pytest.mark.asyncio
    async def test_empty_query_results(self):
        """Test handling of empty result sets"""
        from tools.aws_athena_querier import AWSAthenaQuerier

        querier = AWSAthenaQuerier(output_location='s3://test/')
        querier.boto3_available = True

        mock_client = Mock()
        mock_client.get_query_results.return_value = {
            'ResultSet': {
                'ResultSetMetadata': {
                    'ColumnInfo': [{'Name': 'col1'}]
                },
                'Rows': [
                    {'Data': [{'VarCharValue': 'col1'}]}  # Header only, no data
                ]
            }
        }
        querier._athena_client = mock_client

        results = await querier._get_query_results('test-id')

        assert results == []

    @pytest.mark.asyncio
    async def test_null_values_in_results(self):
        """Test handling of NULL values in query results"""
        from tools.aws_athena_querier import AWSAthenaQuerier

        querier = AWSAthenaQuerier(output_location='s3://test/')
        querier.boto3_available = True

        mock_client = Mock()
        mock_client.get_query_results.return_value = {
            'ResultSet': {
                'ResultSetMetadata': {
                    'ColumnInfo': [{'Name': 'col1'}, {'Name': 'col2'}]
                },
                'Rows': [
                    {'Data': [{'VarCharValue': 'col1'}, {'VarCharValue': 'col2'}]},
                    {'Data': [{'VarCharValue': 'value1'}, {}]}  # NULL for col2
                ]
            }
        }
        querier._athena_client = mock_client

        results = await querier._get_query_results('test-id')

        assert len(results) == 1
        assert results[0]['col1'] == 'value1'
        assert results[0]['col2'] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
