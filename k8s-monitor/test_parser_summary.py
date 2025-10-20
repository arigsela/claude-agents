#!/usr/bin/env python3
"""Test parser with summary format response."""

from src.utils.parsers import parse_k8s_analyzer_output

# Actual summary response from k8s-analyzer (from the latest run)
SUMMARY_RESPONSE = """
## K3s Cluster Health Summary

The k8s-analyzer has completed a comprehensive health check of your K3s homelab cluster. Here are the key findings:

### 🟢 Overall Status: HEALTHY
- **All P0 (business-critical) services**: 7/7 operational ✅
- **All P1 (infrastructure) services**: 5/5 operational ✅
- **All nodes**: 4/4 ready and healthy ✅

### Critical Services Status
- **chores-tracker** (frontend & backend): Both running with 2 replicas each
- **mysql & postgresql**: Single replicas running normally (as designed)
- **n8n**: AI automation workflows operational
- **nginx-ingress**: All traffic routing properly with valid TLS certificates

### Minor Issues Found (No Immediate Action Needed)
1. **route53-updater**: Wrong ECR region in image config (P3 service, low priority fix)
2. **ECR secret warnings**: Cosmetic warnings during secret rotation, all pods healthy
3. **mysql ArgoCD status**: Shows "Progressing" which is normal during continuous sync

### Resource Utilization
- **Nodes**: 12-41% CPU, 23-30% memory usage (healthy levels)
- **MySQL**: 26-52% memory usage (normal)
- **PostgreSQL**: 3-7% memory usage (very healthy)

The cluster is operating excellently with all business-critical services within their design parameters and tolerances. No immediate remediation is required.
"""

def main():
    print("=" * 80)
    print("Testing Parser with Summary Format")
    print("=" * 80)

    findings = parse_k8s_analyzer_output(SUMMARY_RESPONSE)
    print(f"\nFound {len(findings)} findings:")

    for i, finding in enumerate(findings, 1):
        print(f"\n{i}. [{finding['severity'].upper()}] {finding['priority']}")
        print(f"   {finding['description']}")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
