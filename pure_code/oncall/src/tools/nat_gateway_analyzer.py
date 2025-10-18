"""
NAT Gateway Traffic Analyzer
Tools for analyzing AWS NAT gateway traffic metrics and detecting spikes

These tools provide on-demand CloudWatch metrics analysis for NAT gateways
serving the dev-eks cluster. Used for correlating traffic spikes with workloads.
"""

import boto3
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import os

logger = logging.getLogger(__name__)

# Default NAT gateway for dev-eks (us-east-1c)
DEFAULT_NAT_GATEWAY_ID = "nat-07eb006676096fcd3"
DEFAULT_VPC_ID = "vpc-00a81b349b5975c2e"

# Spike detection thresholds
DEFAULT_SPIKE_THRESHOLD_GB = 10.0  # Alert if > 10 GB in 5-minute period
DEFAULT_BASELINE_GB = 5.0          # Normal traffic baseline

# CloudWatch metric configuration
CLOUDWATCH_NAMESPACE = "AWS/NATGateway"
CLOUDWATCH_PERIOD_SECONDS = 300    # 5-minute periods

# Cache configuration (prevent excessive CloudWatch API calls)
CACHE_TTL_SECONDS = 300  # 5-minute cache


@dataclass
class NATMetrics:
    """NAT gateway traffic metrics for a time period"""
    nat_gateway_id: str
    vpc_id: str
    availability_zone: str
    start_time: str
    end_time: str
    total_bytes_out: float
    total_bytes_in: float
    peak_bytes_per_second: float
    active_connections_avg: float
    data_points: List[Dict[str, Any]]
    spikes_detected: List[Dict[str, Any]]

    def to_gb(self, bytes_value: float) -> float:
        """Convert bytes to GB"""
        return bytes_value / (1024 ** 3)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)


@dataclass
class TrafficSpike:
    """Represents a detected traffic spike"""
    timestamp: str
    bytes_transferred: float
    bytes_transferred_gb: float
    baseline_gb: float
    multiplier: float
    severity: str  # info, medium, high, critical

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class NATGatewayAnalyzer:
    """
    Analyzer for AWS NAT gateway traffic metrics.

    Fetches CloudWatch metrics, detects spikes, and provides structured data
    for correlation with Kubernetes workloads.
    """

    def __init__(self, aws_profile: Optional[str] = None, aws_region: str = "us-east-1"):
        """
        Initialize NAT gateway analyzer.

        Args:
            aws_profile: AWS profile name (optional, for local dev only - uses env vars in production)
            aws_region: AWS region (default: us-east-1)
        """
        self.region = aws_region

        # Initialize boto3 clients
        # In Kubernetes, boto3 will automatically use environment variables:
        # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN (optional)
        # Only use profile for local development
        session_kwargs = {"region_name": self.region}

        # Only use profile if explicitly provided AND not in Kubernetes
        # In K8s, environment variables from ExternalSecret will be used
        if aws_profile and not os.getenv('KUBERNETES_SERVICE_HOST'):
            session_kwargs["profile_name"] = aws_profile
            logger.info(f"Using AWS profile: {aws_profile}")
        else:
            logger.info("Using AWS credentials from environment variables (KUBERNETES or default)")

        session = boto3.Session(**session_kwargs)
        self.cloudwatch = session.client('cloudwatch')
        self.ec2 = session.client('ec2')

        # Simple in-memory cache
        self._cache: Dict[str, tuple[datetime, NATMetrics]] = {}

        logger.info(f"Initialized NATGatewayAnalyzer for region {self.region}")

    def fetch_nat_metrics(
        self,
        nat_gateway_id: str = DEFAULT_NAT_GATEWAY_ID,
        time_window_hours: int = 1,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> NATMetrics:
        """
        Fetch NAT gateway traffic metrics from CloudWatch.

        Args:
            nat_gateway_id: NAT gateway ID (default: dev-eks primary NAT)
            time_window_hours: Hours to look back (default: 1, max: 168)
            start_time: Custom start time (overrides time_window_hours)
            end_time: Custom end time (default: now)

        Returns:
            NATMetrics object with traffic data and spike detection

        Raises:
            ValueError: Invalid time range or NAT gateway ID
            boto3.exceptions.ClientError: AWS API errors
        """
        # Validate time window
        if time_window_hours < 1 or time_window_hours > 168:
            raise ValueError("time_window_hours must be between 1 and 168 (1 week)")

        # Calculate time range
        if end_time is None:
            end_time = datetime.now(timezone.utc)

        if start_time is None:
            start_time = end_time - timedelta(hours=time_window_hours)

        # Validate time range
        if start_time >= end_time:
            raise ValueError("start_time must be before end_time")

        # Check cache
        cache_key = f"{nat_gateway_id}:{start_time.isoformat()}:{end_time.isoformat()}"
        if cache_key in self._cache:
            cached_time, cached_metrics = self._cache[cache_key]
            if datetime.now(timezone.utc) - cached_time < timedelta(seconds=CACHE_TTL_SECONDS):
                logger.info(f"Cache hit for NAT metrics: {cache_key}")
                return cached_metrics

        logger.info(f"Fetching NAT metrics for {nat_gateway_id} from {start_time} to {end_time}")

        try:
            # Fetch NAT gateway info
            nat_info = self.get_nat_gateway_info(nat_gateway_id)

            # Fetch BytesOutToDestination (primary metric for egress traffic)
            bytes_out_response = self.cloudwatch.get_metric_statistics(
                Namespace=CLOUDWATCH_NAMESPACE,
                MetricName='BytesOutToDestination',
                Dimensions=[{'Name': 'NatGatewayId', 'Value': nat_gateway_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=CLOUDWATCH_PERIOD_SECONDS,
                Statistics=['Sum', 'Maximum']
            )

            # Fetch BytesInFromSource (return traffic)
            bytes_in_response = self.cloudwatch.get_metric_statistics(
                Namespace=CLOUDWATCH_NAMESPACE,
                MetricName='BytesInFromSource',
                Dimensions=[{'Name': 'NatGatewayId', 'Value': nat_gateway_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=CLOUDWATCH_PERIOD_SECONDS,
                Statistics=['Sum']
            )

            # Fetch PeakBytesPerSecond
            peak_response = self.cloudwatch.get_metric_statistics(
                Namespace=CLOUDWATCH_NAMESPACE,
                MetricName='PeakBytesPerSecond',
                Dimensions=[{'Name': 'NatGatewayId', 'Value': nat_gateway_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=CLOUDWATCH_PERIOD_SECONDS,
                Statistics=['Maximum']
            )

            # Fetch ActiveConnectionCount
            connections_response = self.cloudwatch.get_metric_statistics(
                Namespace=CLOUDWATCH_NAMESPACE,
                MetricName='ActiveConnectionCount',
                Dimensions=[{'Name': 'NatGatewayId', 'Value': nat_gateway_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=CLOUDWATCH_PERIOD_SECONDS,
                Statistics=['Average']
            )

            # Process data points
            bytes_out_data = sorted(bytes_out_response.get('Datapoints', []), key=lambda x: x['Timestamp'])
            bytes_in_data = sorted(bytes_in_response.get('Datapoints', []), key=lambda x: x['Timestamp'])
            peak_data = sorted(peak_response.get('Datapoints', []), key=lambda x: x['Timestamp'])
            connections_data = sorted(connections_response.get('Datapoints', []), key=lambda x: x['Timestamp'])

            # Calculate totals
            total_bytes_out = sum(dp.get('Sum', 0) for dp in bytes_out_data)
            total_bytes_in = sum(dp.get('Sum', 0) for dp in bytes_in_data)
            peak_throughput = max((dp.get('Maximum', 0) for dp in peak_data), default=0)
            avg_connections = sum(dp.get('Average', 0) for dp in connections_data) / len(connections_data) if connections_data else 0

            # Combine data points by timestamp
            combined_data = self._combine_data_points(bytes_out_data, bytes_in_data, peak_data, connections_data)

            # Detect spikes
            spikes = self._detect_spikes(bytes_out_data, DEFAULT_SPIKE_THRESHOLD_GB, DEFAULT_BASELINE_GB)

            # Build metrics object
            metrics = NATMetrics(
                nat_gateway_id=nat_gateway_id,
                vpc_id=nat_info['vpc_id'],
                availability_zone=nat_info['availability_zone'],
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                total_bytes_out=total_bytes_out,
                total_bytes_in=total_bytes_in,
                peak_bytes_per_second=peak_throughput,
                active_connections_avg=avg_connections,
                data_points=combined_data,
                spikes_detected=spikes
            )

            # Cache results
            self._cache[cache_key] = (datetime.now(timezone.utc), metrics)

            logger.info(f"Fetched NAT metrics: {total_bytes_out / (1024**3):.2f} GB egress, {len(spikes)} spikes detected")

            return metrics

        except self.cloudwatch.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'Throttling':
                logger.warning(f"CloudWatch API throttled for {nat_gateway_id}")
                raise ValueError("AWS CloudWatch API is being throttled. Please retry in a few seconds.")
            else:
                logger.error(f"CloudWatch API error: {error_code} - {e.response['Error']['Message']}")
                raise
        except Exception as e:
            logger.error(f"Error fetching NAT metrics: {str(e)}")
            raise

    def get_nat_gateway_info(self, nat_gateway_id: str) -> Dict[str, Any]:
        """
        Get NAT gateway metadata from EC2 API.

        Args:
            nat_gateway_id: NAT gateway ID

        Returns:
            Dictionary with VPC ID, subnet, AZ, tags, state

        Raises:
            ValueError: NAT gateway not found
        """
        try:
            response = self.ec2.describe_nat_gateways(
                NatGatewayIds=[nat_gateway_id]
            )

            if not response['NatGateways']:
                raise ValueError(f"NAT gateway {nat_gateway_id} not found")

            nat = response['NatGateways'][0]

            # Extract tags as dict
            tags = {tag['Key']: tag['Value'] for tag in nat.get('Tags', [])}

            info = {
                'nat_gateway_id': nat['NatGatewayId'],
                'vpc_id': nat['VpcId'],
                'subnet_id': nat['SubnetId'],
                'state': nat['State'],
                'availability_zone': tags.get('Name', 'unknown').split('-')[-1] if 'Name' in tags else 'unknown',
                'tags': tags,
                'public_ip': nat['NatGatewayAddresses'][0]['PublicIp'] if nat['NatGatewayAddresses'] else None
            }

            logger.info(f"NAT gateway info: {nat_gateway_id} in VPC {info['vpc_id']}, AZ {info['availability_zone']}")

            return info

        except self.ec2.exceptions.ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'InvalidNatGatewayID.NotFound':
                raise ValueError(f"NAT gateway {nat_gateway_id} not found")
            else:
                logger.error(f"EC2 API error: {error_code} - {e.response['Error']['Message']}")
                raise

    def _combine_data_points(
        self,
        bytes_out: List[Dict],
        bytes_in: List[Dict],
        peak: List[Dict],
        connections: List[Dict]
    ) -> List[Dict[str, Any]]:
        """Combine metrics from different API calls by timestamp"""
        # Create a dict keyed by timestamp
        combined = {}

        for dp in bytes_out:
            ts = dp['Timestamp'].isoformat()
            combined[ts] = {
                'timestamp': ts,
                'bytes_out': dp.get('Sum', 0),
                'bytes_out_gb': dp.get('Sum', 0) / (1024 ** 3),
                'bytes_in': 0,
                'peak_bytes_per_sec': 0,
                'active_connections': 0
            }

        for dp in bytes_in:
            ts = dp['Timestamp'].isoformat()
            if ts in combined:
                combined[ts]['bytes_in'] = dp.get('Sum', 0)

        for dp in peak:
            ts = dp['Timestamp'].isoformat()
            if ts in combined:
                combined[ts]['peak_bytes_per_sec'] = dp.get('Maximum', 0)

        for dp in connections:
            ts = dp['Timestamp'].isoformat()
            if ts in combined:
                combined[ts]['active_connections'] = dp.get('Average', 0)

        # Return sorted by timestamp
        return sorted(combined.values(), key=lambda x: x['timestamp'])

    def _detect_spikes(
        self,
        bytes_out_data: List[Dict],
        spike_threshold_gb: float,
        baseline_gb: float
    ) -> List[Dict[str, Any]]:
        """
        Detect traffic spikes in the data.

        Args:
            bytes_out_data: CloudWatch data points for BytesOutToDestination
            spike_threshold_gb: Threshold in GB for spike detection
            baseline_gb: Normal baseline traffic in GB

        Returns:
            List of detected spikes with timestamp, volume, and severity
        """
        spikes = []

        for dp in bytes_out_data:
            bytes_value = dp.get('Sum', 0)
            gb_value = bytes_value / (1024 ** 3)

            if gb_value > spike_threshold_gb:
                # Calculate severity based on multiplier over baseline
                multiplier = gb_value / baseline_gb if baseline_gb > 0 else gb_value

                if multiplier > 10:
                    severity = "critical"
                elif multiplier > 5:
                    severity = "high"
                elif multiplier > 2:
                    severity = "medium"
                else:
                    severity = "info"

                spike = {
                    'timestamp': dp['Timestamp'].isoformat(),
                    'bytes_transferred': bytes_value,
                    'bytes_transferred_gb': round(gb_value, 3),
                    'baseline_gb': baseline_gb,
                    'multiplier': round(multiplier, 2),
                    'severity': severity
                }

                spikes.append(spike)
                logger.info(f"Spike detected: {gb_value:.2f} GB at {spike['timestamp']} ({severity})")

        return spikes

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for debugging"""
        return {
            'cache_size': len(self._cache),
            'cache_keys': list(self._cache.keys()),
            'oldest_entry': min((t.isoformat() for t, _ in self._cache.values()), default=None),
            'newest_entry': max((t.isoformat() for t, _ in self._cache.values()), default=None)
        }

    def clear_cache(self):
        """Clear the metrics cache"""
        self._cache.clear()
        logger.info("NAT metrics cache cleared")

    def format_metrics_for_llm(self, metrics: NATMetrics) -> str:
        """
        Format metrics as human-readable string for LLM consumption.

        Args:
            metrics: NATMetrics object

        Returns:
            Formatted string with key metrics and spike information
        """
        total_gb_out = metrics.total_bytes_out / (1024 ** 3)
        total_gb_in = metrics.total_bytes_in / (1024 ** 3)
        peak_mbps = (metrics.peak_bytes_per_second * 8) / (1024 ** 2)  # Convert to Mbps

        output = f"""NAT Gateway Traffic Analysis
Gateway: {metrics.nat_gateway_id} ({metrics.availability_zone})
VPC: {metrics.vpc_id}
Time Period: {metrics.start_time} to {metrics.end_time}

Traffic Summary:
- Total Egress: {total_gb_out:.3f} GB
- Total Ingress: {total_gb_in:.3f} GB
- Peak Throughput: {peak_mbps:.2f} Mbps
- Avg Active Connections: {metrics.active_connections_avg:.0f}
- Data Points: {len(metrics.data_points)}

"""

        if metrics.spikes_detected:
            output += f"⚠️ Traffic Spikes Detected: {len(metrics.spikes_detected)}\n\n"
            for spike in metrics.spikes_detected:
                output += f"  • {spike['timestamp']}: {spike['bytes_transferred_gb']} GB "
                output += f"({spike['multiplier']}x baseline, severity: {spike['severity']})\n"
        else:
            output += "✅ No significant traffic spikes detected (all periods < threshold)\n"

        return output


# Global instance (initialized lazily)
_analyzer: Optional[NATGatewayAnalyzer] = None


def get_analyzer() -> NATGatewayAnalyzer:
    """Get or create the global NAT analyzer instance"""
    global _analyzer
    if _analyzer is None:
        # In Kubernetes: Use environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        # In local dev: Optionally use AWS_PROFILE if set
        aws_profile = os.environ.get('AWS_PROFILE')  # None if not set
        aws_region = os.environ.get('AWS_REGION', 'us-east-1')

        _analyzer = NATGatewayAnalyzer(aws_profile=aws_profile, aws_region=aws_region)
    return _analyzer
