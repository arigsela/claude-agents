#!/bin/bash
# Script to check all critical namespaces systematically

# Infrastructure namespaces
INFRA_NS=(
  "kube-system"
  "karpenter"
  "datadog-operator-dev"
  "actions-runner-controller-dev"
  "crossplane-system"
  "cert-manager-dev"
  "keda-controller-dev"
  "karpenter-controller-dev"
  "kyverno-dev"
  "kyverno-policies-dev"
  "n8n-dev"
  "nginx-ingress-dev"
  "versprite-security"
)

# Application namespaces
APP_NS=(
  "artemis-app-preprod"
  "artemis-auth-kafka-consumer-preprod"
  "artemis-auth-keycloak-preprod"
  "artemis-auth-preprod"
  "artemis-preprod"
  "chronos-preprod"
  "delivery-preprod"
  "excel-writer-preprod"
  "export-manager-kafka-preprod"
  "export-manager-preprod"
  "metric-usage-service-preprod"
  "plutus-celery-worker-preprod"
  "plutus-kafka-worker-preprod"
  "powerpoint-writer-preprod"
)

echo "=== INFRASTRUCTURE NAMESPACES ==="
for ns in "${INFRA_NS[@]}"; do
  echo "--- $ns ---"
  kubectl get pods -n "$ns" --field-selector=status.phase!=Succeeded 2>&1 | head -20
  echo ""
done

echo "=== APPLICATION NAMESPACES ==="
for ns in "${APP_NS[@]}"; do
  echo "--- $ns ---"
  kubectl get pods -n "$ns" --field-selector=status.phase!=Succeeded 2>&1 | head -20
  echo ""
done

echo "=== PROTEUS NAMESPACES ==="
for ns in $(kubectl get namespaces -o json | jq -r '.items[].metadata.name' | grep '^proteus-'); do
  echo "--- $ns ---"
  kubectl get pods -n "$ns" --field-selector=status.phase!=Succeeded 2>&1 | head -20
  echo ""
done
