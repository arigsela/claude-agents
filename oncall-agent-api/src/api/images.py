"""
Image Tags Endpoint (DEVOPS-7737)

Provides endpoint to retrieve currently deployed image tags from Kubernetes deployments.
This enables the EKS monitoring agent to track image deployments and detect unexpected
version changes during routine health checks.

Endpoint: GET /images/tags?service={service_name}
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.middleware import limiter_with_key, verify_api_key
from api.models import ImageTagResponse

# Import kubernetes client
try:
    from kubernetes import client, config

    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

# Cache for service mapping config (loaded once)
_service_mapping_cache: dict[str, Any] | None = None


def load_service_mapping() -> dict[str, Any]:
    """
    Load service mapping configuration from YAML file.

    Returns:
        Dictionary containing service_mappings configuration

    Raises:
        HTTPException: If config file cannot be loaded
    """
    global _service_mapping_cache

    if _service_mapping_cache is not None:
        return _service_mapping_cache

    # Determine config path - support both local dev and container deployments
    config_paths = [
        Path(__file__).parent.parent.parent / "config" / "service_mapping.yaml",
        Path("/app/config/service_mapping.yaml"),  # Container path
        Path(os.getenv("SERVICE_MAPPING_PATH", "config/service_mapping.yaml")),
    ]

    config_path = None
    for path in config_paths:
        if path.exists():
            config_path = path
            break

    if config_path is None:
        logger.error("service_mapping.yaml not found in any expected location")
        raise HTTPException(status_code=500, detail="Service mapping configuration not found")

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            _service_mapping_cache = config
            logger.info(f"Loaded service mapping from {config_path}")
            return config
    except Exception as e:
        logger.error(f"Failed to load service_mapping.yaml: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load service mapping configuration: {str(e)}"
        )


def get_service_config(service_name: str) -> dict[str, Any]:
    """
    Get configuration for a specific service.

    Args:
        service_name: Name of the service to look up

    Returns:
        Service configuration dictionary

    Raises:
        HTTPException: 404 if service not found in mapping
    """
    config = load_service_mapping()
    service_mappings = config.get("service_mappings", {})

    if service_name not in service_mappings:
        available_services = list(service_mappings.keys())
        logger.warning(f"Service '{service_name}' not found. Available: {available_services}")
        raise HTTPException(
            status_code=404,
            detail=f"Service '{service_name}' not found in service_mapping.yaml. "
            f"Available services: {', '.join(sorted(available_services))}",
        )

    return service_mappings[service_name]


def resolve_namespace(service_name: str, service_config: dict[str, Any]) -> str:
    """
    Resolve the Kubernetes namespace for a service.

    Priority:
    1. Explicit namespace in service_mapping.yaml
    2. Inferred pattern: {service}-dev

    Args:
        service_name: Name of the service
        service_config: Service configuration from mapping

    Returns:
        Resolved namespace string
    """
    if "namespace" in service_config:
        return service_config["namespace"]

    # Inference pattern - default to {service}-dev
    inferred = f"{service_name}-dev"
    logger.info(f"No explicit namespace for '{service_name}', inferring: {inferred}")
    return inferred


def get_deployment_name(service_name: str, service_config: dict[str, Any]) -> str:
    """
    Get the Kubernetes deployment name for a service.

    Args:
        service_name: Name of the service
        service_config: Service configuration from mapping

    Returns:
        Deployment name string
    """
    return service_config.get("k8s_deployment_name", service_name)


def init_k8s_client():
    """
    Initialize Kubernetes client.

    Returns:
        AppsV1Api client instance

    Raises:
        HTTPException: If K8s client cannot be initialized
    """
    if not KUBERNETES_AVAILABLE:
        raise HTTPException(status_code=500, detail="Kubernetes client library not available")

    try:
        # Try to load in-cluster config first, fall back to kubeconfig
        try:
            config.load_incluster_config()
            logger.debug("Loaded in-cluster Kubernetes config")
        except Exception:
            kubeconfig_path = os.getenv("KUBECONFIG")
            if kubeconfig_path:
                config.load_kube_config(config_file=kubeconfig_path)
            else:
                config.load_kube_config()
            logger.debug("Loaded Kubernetes config from kubeconfig")

        return client.AppsV1Api()
    except Exception as e:
        logger.error(f"Failed to initialize Kubernetes client: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to connect to Kubernetes API: {str(e)}"
        )


def get_deployment_image(
    apps_v1: client.AppsV1Api, deployment_name: str, namespace: str
) -> tuple[str, str, int]:
    """
    Get the image URL, container name, and pod count from a Kubernetes deployment.

    Args:
        apps_v1: Kubernetes AppsV1Api client
        deployment_name: Name of the deployment
        namespace: Kubernetes namespace

    Returns:
        Tuple of (image_url, container_name, pod_count)

    Raises:
        HTTPException: If deployment not found or image cannot be extracted
    """
    try:
        deployment = apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
    except client.exceptions.ApiException as e:
        if e.status == 404:
            logger.warning(f"Deployment '{deployment_name}' not found in namespace '{namespace}'")
            raise HTTPException(
                status_code=404,
                detail=f"Deployment '{deployment_name}' not found in namespace '{namespace}'",
            )
        logger.error(f"K8s API error: {e}")
        raise HTTPException(status_code=500, detail=f"Kubernetes API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error querying deployment: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query deployment: {str(e)}")

    # Extract primary container (first container in spec)
    containers = deployment.spec.template.spec.containers
    if not containers:
        raise HTTPException(
            status_code=500, detail=f"Deployment '{deployment_name}' has no containers defined"
        )

    primary_container = containers[0]
    container_name = primary_container.name
    image_url = primary_container.image

    if not image_url:
        raise HTTPException(
            status_code=500, detail=f"Container '{container_name}' has no image defined"
        )

    # Get pod count from deployment status
    pod_count = deployment.status.ready_replicas or 0

    return image_url, container_name, pod_count


@router.get(
    "/tags",
    response_model=ImageTagResponse,
    summary="Get deployed image tag for a service",
    description="Query Kubernetes to retrieve the currently deployed image tag for a service.",
    responses={
        200: {
            "description": "Successfully retrieved image tag information",
            "content": {
                "application/json": {
                    "example": {
                        "service_name": "hermes",
                        "deployment_name": "hermes-app",
                        "namespace": "artemis-dev",
                        "container_name": "app",
                        "current_image_url": "082902060548.dkr.ecr.us-east-1.amazonaws.com/hermesapp:13.14.26",
                        "pod_count": 3,
                        "timestamp": "2025-12-11T10:30:00Z",
                    }
                }
            },
        },
        404: {
            "description": "Service or deployment not found",
            "content": {
                "application/json": {
                    "examples": {
                        "service_not_found": {
                            "summary": "Service not in config",
                            "value": {
                                "detail": "Service 'unknown-service' not found in service_mapping.yaml. Available services: hermes, proteus, zeus..."
                            },
                        },
                        "deployment_not_found": {
                            "summary": "Deployment not in K8s",
                            "value": {
                                "detail": "Deployment 'hermes-app' not found in namespace 'artemis-dev'"
                            },
                        },
                    }
                }
            },
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "examples": {
                        "k8s_connection": {
                            "summary": "K8s connection error",
                            "value": {
                                "detail": "Failed to connect to Kubernetes API: Connection refused"
                            },
                        },
                        "no_image": {
                            "summary": "No image defined",
                            "value": {"detail": "Container 'app' has no image defined"},
                        },
                    }
                }
            },
        },
    },
)
@limiter_with_key.limit("60/minute")
async def get_image_tags(
    request: Request,
    service: str = Query(
        ...,
        description="Service name from service_mapping.yaml",
        min_length=1,
        max_length=255,
        examples={
            "hermes": {"value": "hermes", "summary": "Hermes (artemis-dev)"},
            "hermes-qa1": {"value": "hermes-qa1", "summary": "Hermes (artemis-qa1)"},
            "hermes-preprod": {"value": "hermes-preprod", "summary": "Hermes (artemis-preprod)"},
            "proteus": {"value": "proteus", "summary": "Proteus API (proteus-dev)"},
            "zeus": {"value": "zeus", "summary": "Zeus Web (merlinqa)"},
            "zeus-qa": {"value": "zeus-qa", "summary": "Zeus Web (qa namespace)"},
        },
    ),
    api_key: str = Depends(verify_api_key),
) -> ImageTagResponse:
    """
    Retrieve the currently deployed image tag for a Kubernetes service.

    This endpoint queries the Kubernetes API to get the current container image
    for a service's deployment. It returns comprehensive information including:

    - **service_name**: The logical service name from the request
    - **deployment_name**: The actual Kubernetes deployment name
    - **namespace**: The Kubernetes namespace where the deployment lives
    - **container_name**: Name of the primary container (first in spec)
    - **current_image_url**: Full image URL including registry and tag
    - **pod_count**: Number of ready pods for this deployment
    - **timestamp**: When this query was executed

    ## Available Services

    Services are configured in `config/service_mapping.yaml`. Current services include:

    **Hermes** (artemis-dev, artemis-qa1, artemis-qa2, artemis-qa3, artemis-preprod):
    | Service | Namespace |
    |---------|-----------|
    | hermes | artemis-dev |
    | hermes-qa1 | artemis-qa1 |
    | hermes-qa2 | artemis-qa2 |
    | hermes-qa3 | artemis-qa3 |
    | hermes-preprod | artemis-preprod |

    **Zeus** (merlinqa, qa, merlinpreprod, preprod):
    | Service | Namespace |
    |---------|-----------|
    | zeus | merlinqa |
    | zeus-qa | qa |
    | zeus-merlinpreprod | merlinpreprod |
    | zeus-preprod | preprod |

    **Other Services**:
    | Service | Namespace |
    |---------|-----------|
    | proteus | proteus-dev |
    | hermes-chartdata | artemis-preprod |

    ## Usage Examples

    ```bash
    # Get hermes image tag
    curl -H "X-API-Key: your-key" "http://localhost:8000/images/tags?service=hermes"

    # Get zeus QA image tag
    curl -H "X-API-Key: your-key" "http://localhost:8000/images/tags?service=zeus-qa"
    ```

    ## Rate Limiting

    This endpoint is rate-limited to **60 requests per minute** per API key.
    """
    logger.info(f"Image tag request for service: {service}")

    # Get service configuration
    service_config = get_service_config(service)

    # Resolve namespace and deployment name
    namespace = resolve_namespace(service, service_config)
    deployment_name = get_deployment_name(service, service_config)

    logger.info(f"Querying deployment '{deployment_name}' in namespace '{namespace}'")

    # Initialize K8s client and get deployment info
    apps_v1 = init_k8s_client()
    image_url, container_name, pod_count = get_deployment_image(apps_v1, deployment_name, namespace)

    logger.info(f"Found image for {service}: {image_url} (pods: {pod_count})")

    return ImageTagResponse(
        service_name=service,
        deployment_name=deployment_name,
        namespace=namespace,
        container_name=container_name,
        current_image_url=image_url,
        pod_count=pod_count,
        timestamp=datetime.utcnow(),
    )


@router.get(
    "/health",
    summary="Check images endpoint health",
    description="Returns health status including Kubernetes connectivity and service configuration.",
    responses={
        200: {
            "description": "Health check response",
            "content": {
                "application/json": {
                    "examples": {
                        "healthy": {
                            "summary": "All systems operational",
                            "value": {
                                "status": "healthy",
                                "kubernetes_available": True,
                                "kubernetes_connected": True,
                                "service_count": 15,
                                "timestamp": "2025-12-11T10:30:00Z",
                            },
                        },
                        "degraded": {
                            "summary": "K8s not connected",
                            "value": {
                                "status": "degraded",
                                "kubernetes_available": True,
                                "kubernetes_connected": False,
                                "kubernetes_error": "Unable to connect to K8s API",
                                "service_count": 15,
                                "timestamp": "2025-12-11T10:30:00Z",
                            },
                        },
                    }
                }
            },
        }
    },
)
async def images_health():
    """
    Health check endpoint for the images service.

    This endpoint verifies:
    - **kubernetes_available**: Whether the kubernetes Python library is installed
    - **kubernetes_connected**: Whether we can successfully connect to the K8s API
    - **service_count**: Number of services configured in service_mapping.yaml

    ## Status Values

    - **healthy**: All systems operational, K8s connected
    - **degraded**: Service running but K8s connection failed or config error

    ## Usage

    ```bash
    curl http://localhost:8000/images/health
    ```

    This endpoint does NOT require API key authentication.
    """
    health_info = {
        "status": "healthy",
        "kubernetes_available": KUBERNETES_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Try to load config
    try:
        config = load_service_mapping()
        health_info["service_count"] = len(config.get("service_mappings", {}))
    except Exception as e:
        health_info["status"] = "degraded"
        health_info["config_error"] = str(e)

    # Try to connect to K8s if available
    if KUBERNETES_AVAILABLE:
        try:
            init_k8s_client()
            health_info["kubernetes_connected"] = True
        except Exception as e:
            health_info["kubernetes_connected"] = False
            health_info["kubernetes_error"] = str(e)

    return health_info
