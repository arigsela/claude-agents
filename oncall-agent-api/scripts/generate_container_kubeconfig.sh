#!/bin/bash
# Generate container-friendly kubeconfig without AWS SSO profile references

set -e

CLUSTER_NAME="dev-eks"
OUTPUT_FILE="${1:-config/kubeconfig-container.yaml}"

echo "Generating container-friendly kubeconfig..."

# Get current cluster info
CLUSTER_ENDPOINT=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
CLUSTER_CA=$(kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

# Create kubeconfig that uses environment variable credentials
cat > "$OUTPUT_FILE" << EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: ${CLUSTER_CA}
    server: ${CLUSTER_ENDPOINT}
  name: ${CLUSTER_NAME}
contexts:
- context:
    cluster: ${CLUSTER_NAME}
    user: ${CLUSTER_NAME}
  name: ${CLUSTER_NAME}
current-context: ${CLUSTER_NAME}
users:
- name: ${CLUSTER_NAME}
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: aws
      args:
      - eks
      - get-token
      - --cluster-name
      - ${CLUSTER_NAME}
      - --region
      - us-east-1
      # NOTE: No --profile flag - uses AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from environment
      env: null
      interactiveMode: Never
      provideClusterInfo: false
EOF

echo "✅ Created $OUTPUT_FILE"
echo ""
echo "This kubeconfig:"
echo "  - Uses AWS CLI to get EKS tokens"
echo "  - Reads AWS credentials from environment variables (not SSO)"
echo "  - Works in containers with AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
echo ""
echo "To use in docker-compose:"
echo "  Update volumes section to mount this file instead:"
echo "  - ./config/kubeconfig-container.yaml:/root/.kube/config:ro"
