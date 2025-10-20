"""
Datadog Metrics Integrator
Provides Datadog metrics queries for Kubernetes incident troubleshooting
"""

import logging
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _to_json_serializable(obj):
    """
    Convert Datadog API objects to JSON-serializable types.

    Handles:
    - Point objects → [timestamp, value]
    - Enum objects (MetricsQueryUnit) → string value
    - Other objects → string representation
    """
    if obj is None:
        return None
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [_to_json_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: _to_json_serializable(v) for k, v in obj.items()}
    elif hasattr(obj, 'value'):
        # Enum-like object with .value attribute
        return str(obj.value)
    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
        # Iterable (like Point) - convert to list
        return list(obj)
    else:
        # Fallback: convert to string
        return str(obj)


class DatadogIntegrator:
    """
    Datadog metrics integrator for troubleshooting Kubernetes incidents.

    This class provides helper methods for querying Datadog metrics:
    - Timeseries metrics: Query any Datadog metric over time
    - Pod metrics: CPU, memory, network for specific pods
    - Container metrics: Resource usage at container level
    - Network metrics: Traffic patterns and correlation with NAT
    """

    # Default Datadog site
    DEFAULT_SITE = 'datadoghq.com'

    def __init__(self, api_key: Optional[str] = None, app_key: Optional[str] = None, site: Optional[str] = None):
        """
        Initialize Datadog integrator with API clients.

        Args:
            api_key: Datadog API key (defaults to DATADOG_API_KEY env var)
            app_key: Datadog Application key (defaults to DATADOG_APP_KEY env var)
            site: Datadog site (defaults to DATADOG_SITE env var or datadoghq.com)
        """
        self.api_key = api_key or os.getenv('DATADOG_API_KEY')
        self.app_key = app_key or os.getenv('DATADOG_APP_KEY')
        self.site = site or os.getenv('DATADOG_SITE', self.DEFAULT_SITE)

        # Initialize Datadog API clients (lazy initialization)
        self._metrics_api = None
        self._api_client = None

        # Check if datadog-api-client is available
        try:
            import datadog_api_client
            self.datadog_available = True
            logger.info(f"DatadogIntegrator initialized for site: {self.site} (datadog-api-client available)")
        except ImportError:
            self.datadog_available = False
            logger.warning("DatadogIntegrator initialized but datadog-api-client not available - operations will fail gracefully")

    @property
    def api_client(self):
        """Lazy initialization of Datadog API client."""
        if not self.datadog_available:
            return None

        if self._api_client is None:
            from datadog_api_client import ApiClient, Configuration

            configuration = Configuration()
            configuration.api_key["apiKeyAuth"] = self.api_key
            configuration.api_key["appKeyAuth"] = self.app_key

            # Set Datadog site (US or EU)
            if self.site:
                configuration.server_variables["site"] = self.site

            self._api_client = ApiClient(configuration)

        return self._api_client

    @property
    def metrics_api(self):
        """Lazy initialization of Metrics API client."""
        if not self.datadog_available:
            return None

        if self._metrics_api is None:
            from datadog_api_client.v1.api.metrics_api import MetricsApi

            if self.api_client is None:
                logger.error("Cannot initialize MetricsApi - API client not available")
                return None

            self._metrics_api = MetricsApi(self.api_client)

        return self._metrics_api

    def query_timeseries(
        self,
        query: str,
        start: int,
        end: int
    ) -> Dict[str, Any]:
        """
        Query Datadog timeseries metrics.

        This method queries the Datadog Metrics API for timeseries data over a
        specified time range. The query uses Datadog's query syntax with metric
        names, aggregation functions, and tag filters.

        Args:
            query: Datadog metric query (e.g., "avg:kubernetes.cpu.usage{kube_namespace:proteus-dev}")
            start: Start timestamp (Unix epoch seconds)
            end: End timestamp (Unix epoch seconds)

        Returns:
            Dictionary with series data and metadata

        Example return:
            {
                "query": "avg:kubernetes.cpu.usage{kube_namespace:proteus-dev}",
                "from_ts": 1697470800,
                "to_ts": 1697474400,
                "series": [
                    {
                        "metric": "kubernetes.cpu.usage",
                        "scope": "kube_namespace:proteus-dev",
                        "pointlist": [[1697470800000, 0.45], [1697470860000, 0.52], ...],
                        "unit": "core",
                        "display_name": "kubernetes.cpu.usage"
                    }
                ]
            }
        """
        if not self.datadog_available:
            logger.warning("Cannot query Datadog - datadog-api-client not available")
            return {
                "error": "datadog-api-client not installed",
                "message": "Install with: pip install datadog-api-client"
            }

        if not self.metrics_api:
            logger.error("Metrics API client not initialized")
            return {
                "error": "Datadog client not initialized",
                "message": "Check DATADOG_API_KEY and DATADOG_APP_KEY environment variables"
            }

        try:
            logger.info(f"Querying Datadog: {query} from {start} to {end}")

            response = self.metrics_api.query_metrics(
                _from=start,
                to=end,
                query=query
            )

            # Convert response to dictionary
            result = {
                "query": query,
                "from_ts": start,
                "to_ts": end,
                "series": []
            }

            if response.series:
                for series in response.series:
                    # Extract values using helper for both dict and attribute access
                    def get_value(obj, key):
                        if hasattr(obj, 'get'):
                            return obj.get(key)
                        else:
                            return getattr(obj, key, None)

                    # Get raw pointlist
                    raw_pointlist = get_value(series, 'pointlist') or []

                    # Convert all data to JSON-serializable format
                    series_data = {
                        "metric": _to_json_serializable(get_value(series, 'metric')),
                        "scope": _to_json_serializable(get_value(series, 'scope')),
                        "pointlist": _to_json_serializable(raw_pointlist),
                        "unit": _to_json_serializable(get_value(series, 'unit')),
                        "display_name": _to_json_serializable(get_value(series, 'display_name'))
                    }
                    result["series"].append(series_data)

                logger.info(f"✓ Retrieved {len(result['series'])} series from Datadog")
            else:
                logger.warning(f"No data returned for query: {query}")
                result["message"] = "No data available for this query and time range"

            return result

        except Exception as e:
            logger.error(f"Error querying Datadog: {e}")
            return {
                "error": str(e),
                "query": query,
                "message": "Datadog API error - check credentials and query syntax"
            }

    async def query_pod_metrics(
        self,
        metric: str,
        namespace: str,
        pod_name: Optional[str] = None,
        hours_back: int = 1,
        aggregation: str = "avg"
    ) -> Dict[str, Any]:
        """
        Query metrics for specific Kubernetes pods.

        This method builds a Datadog query for Kubernetes-specific metrics and
        retrieves timeseries data for pods in a given namespace. It supports
        filtering by pod name and various aggregation functions.

        Args:
            metric: Metric name (e.g., "kubernetes.cpu.usage", "kubernetes.memory.rss")
            namespace: Kubernetes namespace
            pod_name: Optional pod name for filtering
            hours_back: Hours to look back (default: 1)
            aggregation: Aggregation function (avg, max, min, sum)

        Returns:
            Timeseries data with values and timestamps

        Example usage:
            result = await integrator.query_pod_metrics(
                metric="kubernetes.cpu.usage",
                namespace="proteus-dev",
                pod_name="proteus-api-abc123",
                hours_back=24,
                aggregation="avg"
            )
        """
        # Build Datadog query with tags
        query = f"{aggregation}:{metric}{{kube_namespace:{namespace}"
        if pod_name:
            query += f",pod_name:{pod_name}"
        query += "}"

        # Calculate time range
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours_back)

        logger.info(f"Querying pod metrics: {metric} for namespace={namespace}, pod={pod_name or 'all'}, hours={hours_back}")

        result = self.query_timeseries(
            query=query,
            start=int(start_time.timestamp()),
            end=int(end_time.timestamp())
        )

        return result

    async def query_container_metrics(
        self,
        namespace: str,
        container_name: Optional[str] = None,
        hours_back: int = 1
    ) -> Dict[str, Any]:
        """
        Query container-level resource metrics.

        Returns CPU, memory, and network metrics for containers. This method
        queries multiple metrics in parallel to provide a comprehensive view
        of container resource usage.

        Args:
            namespace: Kubernetes namespace
            container_name: Optional container name filter
            hours_back: Hours to look back

        Returns:
            Dictionary with CPU, memory, and network metrics

        Example return:
            {
                "kubernetes.cpu.usage": {
                    "query": "avg:kubernetes.cpu.usage{kube_namespace:proteus-dev}",
                    "series": [...]
                },
                "kubernetes.memory.rss": {
                    "query": "avg:kubernetes.memory.rss{kube_namespace:proteus-dev}",
                    "series": [...]
                },
                "kubernetes.memory.working_set": {
                    "query": "avg:kubernetes.memory.working_set{kube_namespace:proteus-dev}",
                    "series": [...]
                }
            }
        """
        metrics_to_query = [
            "kubernetes.cpu.usage.total",  # Use .total variant which has data
            "kubernetes.memory.rss",
            "kubernetes.memory.working_set"
        ]

        results = {}

        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours_back)
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())

        logger.info(f"Querying container metrics for namespace={namespace}, container={container_name or 'all'}, hours={hours_back}")

        for metric in metrics_to_query:
            query = f"avg:{metric}{{kube_namespace:{namespace}"
            if container_name:
                query += f",container_name:{container_name}"
            query += "}"

            metric_data = self.query_timeseries(
                query=query,
                start=start_ts,
                end=end_ts
            )

            results[metric] = metric_data

        logger.info(f"✓ Retrieved {len(results)} container metrics")

        return results

    async def query_network_metrics(
        self,
        namespace: str,
        pod_name: Optional[str] = None,
        hours_back: int = 1
    ) -> Dict[str, Any]:
        """
        Query network traffic metrics for pods.

        Returns network transmission/reception metrics and error rates. Useful
        for correlating with NAT gateway spikes or investigating connectivity issues.

        Args:
            namespace: Kubernetes namespace
            pod_name: Optional pod name filter
            hours_back: Hours to look back

        Returns:
            Dictionary with network TX/RX bytes and errors

        Example return:
            {
                "kubernetes.network.tx_bytes": {
                    "query": "sum:kubernetes.network.tx_bytes{kube_namespace:zeus-dev}by{pod_name}",
                    "series": [...]
                },
                "kubernetes.network.rx_bytes": {
                    "query": "sum:kubernetes.network.rx_bytes{kube_namespace:zeus-dev}by{pod_name}",
                    "series": [...]
                },
                "kubernetes.network.errors": {
                    "query": "sum:kubernetes.network.errors{kube_namespace:zeus-dev}by{pod_name}",
                    "series": [...]
                }
            }
        """
        network_metrics = [
            "kubernetes.network.tx_bytes",
            "kubernetes.network.rx_bytes",
            "kubernetes.network.errors"
        ]

        results = {}

        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours_back)
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())

        logger.info(f"Querying network metrics for namespace={namespace}, pod={pod_name or 'all'}, hours={hours_back}")

        for metric in network_metrics:
            # Use sum aggregation for byte counts
            query = f"sum:{metric}{{kube_namespace:{namespace}"
            if pod_name:
                query += f",pod_name:{pod_name}"
            query += "}by{{pod_name}}"

            metric_data = self.query_timeseries(
                query=query,
                start=start_ts,
                end=end_ts
            )

            results[metric] = metric_data

        logger.info(f"✓ Retrieved {len(results)} network metrics")

        return results
