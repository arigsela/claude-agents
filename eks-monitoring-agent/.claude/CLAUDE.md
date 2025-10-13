# EKS Cluster Monitoring Context

## Cluster Information
- **Cluster Name**: production-eks-us-west-2
- **Region**: us-west-2
- **Kubernetes Version**: 1.28
- **Node Count**: 15

## Critical Namespaces
- `production`: Main application workloads
- `staging`: Staging environment
- `kube-system`: System components

## Known Issues & Patterns

### Recurring Issues
1. **auth-service memory leaks**
   - Symptom: OOMKilled every 2-3 days
   - Workaround: Restart every 48 hours

## Standard Operating Procedures

### Escalation Criteria
Escalate to human if:
- Any operation on `kube-system` namespace
- Deletion of PersistentVolumes
- More than 5 pods failing in same namespace

### Approved Auto-Remediation
- Restart single pods in non-production namespaces
- Clear Failed/Evicted pods
- Scale deployments by ±2 replicas

## Team Contacts
- On-call: #oncall-engineering
- Kubernetes Team: #platform-team
