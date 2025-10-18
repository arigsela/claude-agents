"""
AWS Resource Integrator
Provides AWS resource verification for Kubernetes incident troubleshooting
"""

import logging
import os
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class AWSIntegrator:
    """
    AWS resource integrator for troubleshooting Kubernetes incidents.

    This class provides helper methods for verifying AWS resources:
    - Secrets Manager: Verify ExternalSecret sync issues
    - ECR: Verify container image availability
    - Future: ELB health checks, RDS status, CloudWatch metrics, etc.
    """

    # Default AWS region
    DEFAULT_REGION = 'us-east-1'

    def __init__(self, region: Optional[str] = None):
        """
        Initialize AWS integrator with boto3 clients.

        Args:
            region: AWS region (defaults to AWS_REGION env var or us-east-1)
        """
        self.region = region or os.getenv('AWS_REGION', self.DEFAULT_REGION)

        # Initialize boto3 clients (lazy initialization)
        self._secrets_client = None
        self._ecr_client = None
        self._ec2_client = None

        # Check if boto3 is available
        try:
            import boto3
            self.boto3_available = True
            logger.info(f"AWSIntegrator initialized for region: {self.region} (boto3 available)")
        except ImportError:
            self.boto3_available = False
            logger.warning("AWSIntegrator initialized but boto3 not available - operations will fail gracefully")

    @property
    def secrets_client(self):
        """Lazy initialization of Secrets Manager client."""
        if not self.boto3_available:
            return None

        if self._secrets_client is None:
            import boto3
            self._secrets_client = boto3.client('secretsmanager', region_name=self.region)

        return self._secrets_client

    @property
    def ecr_client(self):
        """Lazy initialization of ECR client."""
        if not self.boto3_available:
            return None

        if self._ecr_client is None:
            import boto3
            self._ecr_client = boto3.client('ecr', region_name=self.region)

        return self._ecr_client

    @property
    def ec2_client(self):
        """Lazy initialization of EC2 client."""
        if not self.boto3_available:
            return None

        if self._ec2_client is None:
            import boto3
            self._ec2_client = boto3.client('ec2', region_name=self.region)

        return self._ec2_client

    async def verify_secrets_manager(self, external_secrets: List[Dict]) -> List[Dict]:
        """
        Verify if secrets actually exist in AWS Secrets Manager.

        This method checks ExternalSecret resources against AWS Secrets Manager
        to determine if sync failures are due to:
        - Missing secrets in AWS (needs creation)
        - IAM permission issues (access denied)
        - SecretStore configuration issues (secret exists but can't sync)

        Args:
            external_secrets: List of ExternalSecret resources from K8s

        Returns:
            List of verification results with status and recommendations

        Example external_secret format:
            {
                "name": "proteus-secrets",
                "namespace": "proteus-dev",
                "target_secret": "proteus-app-secrets",
                "aws_secret_path": "dev/proteus/app-config",
                "is_failing": True
            }
        """
        if not self.boto3_available:
            logger.warning("boto3 not available - cannot verify AWS Secrets Manager")
            return []

        if not self.secrets_client:
            logger.error("Secrets Manager client not initialized")
            return []

        verification_results = []

        try:
            from botocore.exceptions import ClientError

            for ext_secret in external_secrets:
                k8s_name = ext_secret.get('name')
                target_secret = ext_secret.get('target_secret')
                aws_secret_path = ext_secret.get('aws_secret_path')

                if not aws_secret_path:
                    logger.warning(f"ExternalSecret '{k8s_name}' has no AWS secret path, skipping verification")
                    continue

                logger.debug(f"Checking AWS Secrets Manager for ExternalSecret '{k8s_name}' → AWS path: '{aws_secret_path}'")

                try:
                    # Get secret metadata (doesn't include the actual secret value)
                    response = self.secrets_client.describe_secret(SecretId=aws_secret_path)

                    verification_results.append({
                        "external_secret_name": k8s_name,
                        "target_k8s_secret": target_secret,
                        "aws_secret_path": aws_secret_path,
                        "exists_in_aws": True,
                        "aws_secret_name": response.get('Name'),
                        "aws_secret_arn": response.get('ARN'),
                        "last_changed": response.get('LastChangedDate').isoformat() if response.get('LastChangedDate') else None,
                        "last_accessed": response.get('LastAccessedDate').isoformat() if response.get('LastAccessedDate') else None,
                        "status": "AWS secret exists - ExternalSecret sync issue is IAM permissions or SecretStore config"
                    })

                    logger.info(f"  ✓ AWS secret at path '{aws_secret_path}' EXISTS in Secrets Manager")

                except ClientError as e:
                    error_code = e.response['Error']['Code']

                    if error_code == 'ResourceNotFoundException':
                        verification_results.append({
                            "external_secret_name": k8s_name,
                            "target_k8s_secret": target_secret,
                            "aws_secret_path": aws_secret_path,
                            "exists_in_aws": False,
                            "error_code": error_code,
                            "status": f"Secret at path '{aws_secret_path}' does NOT exist in AWS Secrets Manager - needs to be created"
                        })
                        logger.warning(f"  ✗ AWS secret at path '{aws_secret_path}' NOT FOUND in Secrets Manager")

                    elif error_code == 'AccessDeniedException':
                        verification_results.append({
                            "external_secret_name": k8s_name,
                            "target_k8s_secret": target_secret,
                            "aws_secret_path": aws_secret_path,
                            "exists_in_aws": "unknown",
                            "error_code": error_code,
                            "status": "Access Denied - IAM permissions issue preventing verification (secret may exist but we can't access it)"
                        })
                        logger.warning(f"  ⚠ Access denied checking '{aws_secret_path}' - IAM permission issue (secret may exist)")

                    else:
                        verification_results.append({
                            "external_secret_name": k8s_name,
                            "target_k8s_secret": target_secret,
                            "aws_secret_path": aws_secret_path,
                            "exists_in_aws": "unknown",
                            "error": str(e),
                            "error_code": error_code,
                            "aws_error_message": e.response.get('Error', {}).get('Message', ''),
                            "status": f"AWS API error ({error_code}): {e.response.get('Error', {}).get('Message', 'Unknown error')}"
                        })
                        logger.warning(f"  ⚠ Error checking '{aws_secret_path}': {error_code} - {e.response.get('Error', {}).get('Message', '')}")

        except ImportError:
            logger.warning("botocore not available - cannot verify AWS Secrets Manager")
        except Exception as e:
            logger.error(f"Error verifying AWS secrets: {e}")

        return verification_results

    async def verify_ecr_images(self, containers: List[Dict]) -> List[Dict]:
        """
        Verify if container images exist in ECR.

        This method checks container images against ECR to determine if
        ImagePullBackOff errors are due to:
        - Missing image tag (needs rebuild/push)
        - Missing repository (needs ECR repository creation)
        - IAM permission issues (can't pull from ECR)
        - Network connectivity issues (image exists but can't pull)

        Args:
            containers: List of container info dicts with 'image' field

        Returns:
            List of ECR verification results with status and recommendations

        Example container format:
            {
                "name": "proteus-api",
                "image": "082902060548.dkr.ecr.us-east-1.amazonaws.com/proteus:v1.2.3",
                "memory_limit": "2Gi",
                "cpu_limit": "1000m"
            }
        """
        if not self.boto3_available:
            logger.warning("boto3 not available - cannot verify ECR images")
            return []

        if not self.ecr_client:
            logger.error("ECR client not initialized")
            return []

        verification_results = []

        try:
            from botocore.exceptions import ClientError

            for container in containers:
                image_uri = container.get('image', '')

                # Parse ECR image URI: 082902060548.dkr.ecr.us-east-1.amazonaws.com/service-name:tag
                if '.amazonaws.com/' not in image_uri:
                    logger.debug(f"Skipping non-ECR image: {image_uri}")
                    continue

                try:
                    # Extract repository name and tag
                    parts = image_uri.split('/')
                    repo_and_tag = '/'.join(parts[1:])  # service-name:tag or org/service:tag

                    if ':' in repo_and_tag:
                        repo_name, tag = repo_and_tag.rsplit(':', 1)
                    else:
                        repo_name = repo_and_tag
                        tag = 'latest'

                    logger.info(f"Checking ECR for image: {repo_name}:{tag}")

                    # Describe images in ECR repository
                    response = self.ecr_client.describe_images(
                        repositoryName=repo_name,
                        imageIds=[{'imageTag': tag}]
                    )

                    image_details = response['imageDetails'][0] if response['imageDetails'] else {}

                    verification_results.append({
                        "container_name": container.get('name'),
                        "image_uri": image_uri,
                        "repository": repo_name,
                        "tag": tag,
                        "exists_in_ecr": True,
                        "image_digest": image_details.get('imageDigest'),
                        "pushed_at": image_details.get('imagePushedAt').isoformat() if image_details.get('imagePushedAt') else None,
                        "size_mb": round(image_details.get('imageSizeInBytes', 0) / 1024 / 1024, 2),
                        "status": "ECR image exists - pull issue may be IAM permissions or network"
                    })

                    logger.info(f"  ✓ ECR image '{repo_name}:{tag}' EXISTS")

                except ClientError as e:
                    error_code = e.response['Error']['Code']

                    if error_code == 'ImageNotFoundException':
                        verification_results.append({
                            "container_name": container.get('name'),
                            "image_uri": image_uri,
                            "repository": repo_name,
                            "tag": tag,
                            "exists_in_ecr": False,
                            "error_code": error_code,
                            "status": f"Image tag '{tag}' does NOT exist in ECR repository '{repo_name}'"
                        })
                        logger.warning(f"  ✗ ECR image '{repo_name}:{tag}' NOT FOUND")

                    elif error_code == 'RepositoryNotFoundException':
                        verification_results.append({
                            "container_name": container.get('name'),
                            "image_uri": image_uri,
                            "repository": repo_name,
                            "tag": tag,
                            "exists_in_ecr": False,
                            "error_code": error_code,
                            "status": f"ECR repository '{repo_name}' does NOT exist"
                        })
                        logger.warning(f"  ✗ ECR repository '{repo_name}' NOT FOUND")

                    elif error_code == 'AccessDeniedException':
                        verification_results.append({
                            "container_name": container.get('name'),
                            "image_uri": image_uri,
                            "repository": repo_name,
                            "tag": tag,
                            "exists_in_ecr": "unknown",
                            "error_code": error_code,
                            "status": "Access Denied - IAM permissions issue (image may exist but can't verify)"
                        })
                        logger.warning(f"  ⚠ Access denied checking '{repo_name}:{tag}'")

                    else:
                        verification_results.append({
                            "container_name": container.get('name'),
                            "image_uri": image_uri,
                            "repository": repo_name,
                            "tag": tag,
                            "exists_in_ecr": "unknown",
                            "error": str(e),
                            "error_code": error_code,
                            "status": f"AWS ECR error ({error_code}): {e.response.get('Error', {}).get('Message', '')}"
                        })
                        logger.warning(f"  ⚠ Error checking '{repo_name}:{tag}': {error_code}")

                except Exception as e:
                    logger.debug(f"Could not parse/check image {image_uri}: {e}")

        except ImportError:
            logger.warning("botocore not available - cannot verify ECR images")
        except Exception as e:
            logger.error(f"Error verifying ECR images: {e}")

        return verification_results

    def get_ecr_image_details(self, repository: str, tag: str = 'latest') -> Optional[Dict[str, Any]]:
        """
        Get detailed metadata for a specific ECR image.

        Args:
            repository: ECR repository name
            tag: Image tag (defaults to 'latest')

        Returns:
            Dictionary with image metadata or None if not found
        """
        if not self.boto3_available or not self.ecr_client:
            logger.warning("Cannot get ECR image details - boto3 not available")
            return None

        try:
            from botocore.exceptions import ClientError

            response = self.ecr_client.describe_images(
                repositoryName=repository,
                imageIds=[{'imageTag': tag}]
            )

            if not response['imageDetails']:
                return None

            details = response['imageDetails'][0]

            return {
                "repository": repository,
                "tag": tag,
                "digest": details.get('imageDigest'),
                "pushed_at": details.get('imagePushedAt').isoformat() if details.get('imagePushedAt') else None,
                "size_bytes": details.get('imageSizeInBytes', 0),
                "size_mb": round(details.get('imageSizeInBytes', 0) / 1024 / 1024, 2),
                "tags": details.get('imageTags', [])
            }

        except ClientError as e:
            logger.error(f"Error getting ECR image details: {e.response['Error']['Code']}")
            return None
        except Exception as e:
            logger.error(f"Error getting ECR image details: {e}")
            return None

    def parse_ecr_uri(self, image_uri: str) -> Optional[Dict[str, str]]:
        """
        Parse ECR image URI into components.

        Args:
            image_uri: Full ECR image URI

        Returns:
            Dictionary with registry, repository, and tag or None if invalid

        Example:
            Input: "082902060548.dkr.ecr.us-east-1.amazonaws.com/artemis/proteus:v1.2.3"
            Output: {
                "registry": "082902060548.dkr.ecr.us-east-1.amazonaws.com",
                "repository": "artemis/proteus",
                "tag": "v1.2.3"
            }
        """
        if '.amazonaws.com/' not in image_uri:
            return None

        try:
            # Split registry and repo
            registry, remainder = image_uri.split('/', 1)

            # Split repo and tag
            if ':' in remainder:
                repository, tag = remainder.rsplit(':', 1)
            else:
                repository = remainder
                tag = 'latest'

            return {
                "registry": registry,
                "repository": repository,
                "tag": tag,
                "full_uri": image_uri
            }

        except Exception as e:
            logger.debug(f"Could not parse ECR URI {image_uri}: {e}")
            return None

    async def get_vpc_endpoints(self, vpc_id: str) -> Dict[str, Any]:
        """
        Get VPC endpoints configured for a VPC to determine what traffic bypasses NAT gateway.

        This is critical for NAT gateway spike analysis - traffic to services with
        VPC endpoints does NOT go through NAT and cannot be the cause of spikes.

        Args:
            vpc_id: VPC ID to check for endpoints

        Returns:
            Dictionary with VPC endpoint details by service name

        Example return:
            {
                "vpc_id": "vpc-00a81b349b5975c2e",
                "total_endpoints": 15,
                "endpoints": {
                    "s3": {"type": "Gateway", "state": "available"},
                    "ecr.api": {"type": "Interface", "state": "available"},
                    "databricks": {"type": "Interface", "state": "available"},
                    ...
                },
                "nat_bypass_services": ["s3", "ecr", "databricks", "secretsmanager"]
            }
        """
        if not self.boto3_available or not self.ec2_client:
            logger.warning("Cannot get VPC endpoints - boto3/EC2 client not available")
            return {"error": "boto3 not available", "vpc_id": vpc_id}

        try:
            from botocore.exceptions import ClientError

            # Describe VPC endpoints for this VPC
            response = self.ec2_client.describe_vpc_endpoints(
                Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
            )

            endpoints_by_service = {}
            nat_bypass_services = []

            for endpoint in response.get('VpcEndpoints', []):
                service_name = endpoint.get('ServiceName', '')
                # Extract service type (e.g., "com.amazonaws.us-east-1.s3" -> "s3")
                service_type = service_name.split('.')[-1] if service_name else 'unknown'

                endpoint_info = {
                    'endpoint_id': endpoint.get('VpcEndpointId'),
                    'type': endpoint.get('VpcEndpointType'),  # Gateway or Interface
                    'state': endpoint.get('State'),
                    'service_name': service_name
                }

                endpoints_by_service[service_type] = endpoint_info

                # Track services that bypass NAT
                if endpoint['State'] == 'available':
                    nat_bypass_services.append(service_type)

            logger.info(f"Found {len(endpoints_by_service)} VPC endpoints for VPC {vpc_id}")
            logger.info(f"NAT bypass services: {nat_bypass_services}")

            return {
                'vpc_id': vpc_id,
                'total_endpoints': len(endpoints_by_service),
                'endpoints': endpoints_by_service,
                'nat_bypass_services': nat_bypass_services,
                'has_s3_endpoint': 's3' in nat_bypass_services,
                'has_ecr_endpoints': any(s.startswith('ecr') for s in nat_bypass_services),
                'has_databricks_endpoint': 'databricks' in service_name.lower() for service_name in
                    [e.get('service_name', '') for e in endpoints_by_service.values()]
            }

        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(f"Error getting VPC endpoints: {error_code}")
            return {
                'error': error_code,
                'vpc_id': vpc_id,
                'message': e.response.get('Error', {}).get('Message', '')
            }
        except Exception as e:
            logger.error(f"Error getting VPC endpoints: {e}")
            return {'error': str(e), 'vpc_id': vpc_id}
