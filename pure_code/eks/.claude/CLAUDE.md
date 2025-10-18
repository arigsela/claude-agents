# EKS Cluster Monitoring Context

## Cluster Information
- **Cluster Name**: dev-eks
- **Environment**: DEV (not production)
- **Region**: us-east-1
- **Kubernetes Version**: 1.32
- **Node Count**: 40

## Critical Infrastructure Namespaces
- `kube-system`: System components (AWS LB Controller, CoreDNS, kube-proxy)
- `karpenter`: Cluster autoscaling
- `datadog-operator-dev`: Monitoring agents
- `actions-runner-controller-dev`: GitHub Actions runners
- `crossplane-system`: Infrastructure-as-Code provider
- `cert-manager-dev`: Certificate management
- `keda-controller-dev`: Keda controller
- `karpenter-controller-dev`: Karpenter controller
- `kyverno-dev`: Kyverno operator
- `kyverno-policies-dev`: Kyverno policies
- `n8n-dev`: Instance of n8n
- `nginx-ingress-dev`: Nginx ingress controller
- `versprite-security`: Security sensors

## Critical Application Namespaces
- `artemis-app-preprod`: Frontend container for preprod environment
- `artemis-auth-kafka-consumer-preprod`: Kafka consumer for artemis auth service in preprod environment
- `artemis-auth-keycloak-preprod`: Keycloak deployment in the preprod environment
- `artemis-auth-preprod`: Auth service in the preprod environment
- `artemis-preprod`: Main artemis application HERMES service in preprod environment
- `chronos-preprod`: V2 of the frontend service in the preprod environment
- `delivery-preprod`: Delivery service in the preprod environment
- `excel-writer-preprod`: Excel writer service in the preprod environment
- `export-manager-kafka-preprod`: Kafka consumer for export manager service in preprod environment
- `export-manager-preprod`: Export manager service in the preprod environment
- `metric-usage-service-preprod`: Metric usage service in the preprod environment
- `plutus-celery-worker-preprod`: Plutus microservice celery worker for preprod environment
- `plutus-kafka-worker-preprod`: Plutus microservice kafka worker for preprod environment
- `powerpoint-writer-preprod`: PowerPoint writer service in the preprod environment
- `proteus-*`: Any that starts with proteus is considered critical

## Known Issues & Patterns

**NOTE:** This section should be updated based on actual recurring issues found during monitoring cycles.

Currently monitoring dev-eks cluster - no known recurring patterns documented yet.

## Standard Operating Procedures

### Escalation Criteria
Escalate to human if:
- Any operation on `kube-system` namespace
- Deletion of PersistentVolumes
- More than 5 pods failing in same namespace

### Approved Auto-Remediation
**Note: This is a DEV cluster - more permissive than production**

Safe Operations:
- Rolling restarts of deployments with 2+ replicas (non-disruptive)
- Clear Failed/Evicted pods in any namespace
- Scale deployments by ±2 replicas
- Pod deletions in non-system namespaces (karpenter, datadog-operator-test, actions-runner-controller-test)

**Still Blocked:**
- Namespace deletions (requires human approval)
- PersistentVolume deletions
- Operations on kube-system namespace (safety hooks enforce this)

## Team Contacts
- On-call: #oncall-engineering
- Kubernetes Team: #devops-team
