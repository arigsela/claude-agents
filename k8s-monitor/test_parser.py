#!/usr/bin/env python3
"""Test parser with actual k8s-analyzer response."""

from src.utils.parsers import parse_k8s_analyzer_output

# Actual response from k8s-analyzer (from the debug output)
SAMPLE_RESPONSE = """
## K3s Cluster Health Analysis Complete ✅

The k8s-analyzer subagent has completed a comprehensive health check of your K3s homelab cluster. Here's the summary:

### **Overall Status: HEALTHY** 🟢

**All critical services are operational:**
- ✅ **7/7 P0 services** (business-critical) running normally
- ✅ **5/5 P1 services** (infrastructure dependencies) operational
- ✅ **All 4 cluster nodes** healthy with 42 days uptime
- ✅ **100% availability** for customer-facing applications

### **Key Findings:**

**No Critical Issues** - All business-critical services (chores-tracker, mysql, n8n, postgresql, nginx-ingress, oncall-agent) are running with proper high availability where configured.

**Minor Warning** - The `route53-updater` service has an ImagePullBackOff due to an ECR region mismatch (using `us-east-1` instead of `us-east-2`). This is a P3 support service and doesn't impact core operations.

**Notable Stability:**
- MySQL database: 31 days uptime (excellent for single replica)
- Cluster nodes: 42 days uptime across all nodes
- TLS certificates: All valid and auto-renewed
- GitOps: ArgoCD healthy, deployments syncing normally

The cluster is performing excellently with all critical services stable and properly monitored. The only action item is fixing the route53-updater ECR region configuration, which is low priority.
"""

# More detailed response format from the actual full output
DETAILED_RESPONSE = """
## K8s Health Analysis Report
**Timestamp**: 2025-10-20
**Cluster**: K3s Homelab (v1.33.4+k3s1)

### Critical Issues (P0 - Immediate Action Required)

**None detected** - All P0 business-critical services are healthy and operational.

---

### High Priority Issues (P1 - Monitor Closely)

**None detected** - All P1 infrastructure dependency services are healthy and operational.

---

### Warnings (P2/P3 - Informational)

#### 1. route53-updater - ImagePullBackOff (P3)

- **Service**: route53-updater (CronJob)
- **Namespace**: route53-updater
- **Issue**: CronJob pod stuck in ImagePullBackOff for 7+ days
- **Recent Events**:
  - Image pull failure: `852893458518.dkr.ecr.us-east-1.amazonaws.com/route53-updater:latest` (403 Forbidden)
  - Wrong ECR region: Using `us-east-1` instead of `us-east-2`
  - CronJob warning: "too many missed start times"
- **Impact**: DNS Route53 updates not running (likely for dynamic DNS updates)
- **Max Downtime**: N/A (support service, not critical)
- **Root Cause**: Image is in ECR `us-east-2` but manifest references `us-east-1`

**Recommendation**: Update route53-updater manifest to use correct ECR region (`us-east-2`)

---

#### 2. ECR Registry Secret Warnings (Transient - Expected Behavior)

- **Services Affected**: chores-tracker-frontend, oncall-agent
- **Issue**: Periodic warnings about `ecr-registry` secret retrieval
- **Recent Events**: "Unable to retrieve some image pull secrets (ecr-registry)"
- **Impact**: None - pods are running successfully despite warnings
- **Root Cause**: ECR credentials sync runs hourly, warnings appear during brief refresh period
- **Status**: Self-resolving - ecr-credentials-sync CronJob just completed successfully (4 minutes ago)
- **Note**: This is expected behavior from the ECR token refresh mechanism

---

### All Clear (Healthy Services)

#### P0 - Business Critical (All Operational - 0 min max downtime)

- ✅ **chores-tracker-backend**: 2/2 pods running (HA enabled)
- ✅ **chores-tracker-frontend**: 2/2 pods running (HA enabled)
- ✅ **mysql**: 1/1 pods running (single replica - expected)
"""

def main():
    print("=" * 80)
    print("Testing Parser with K8s-Analyzer Response")
    print("=" * 80)

    print("\n\n--- Test 1: Simple Summary Response ---")
    findings1 = parse_k8s_analyzer_output(SAMPLE_RESPONSE)
    print(f"Found {len(findings1)} findings:")
    for i, finding in enumerate(findings1, 1):
        print(f"\n{i}. [{finding['severity'].upper()}] {finding['priority']}")
        print(f"   {finding['description'][:100]}...")

    print("\n\n--- Test 2: Detailed Response ---")
    findings2 = parse_k8s_analyzer_output(DETAILED_RESPONSE)
    print(f"Found {len(findings2)} findings:")
    for i, finding in enumerate(findings2, 1):
        print(f"\n{i}. [{finding['severity'].upper()}] {finding['priority']}")
        print(f"   {finding['description'][:200]}...")

    print("\n\n" + "=" * 80)
    print("Test Complete")
    print("=" * 80)


if __name__ == "__main__":
    main()
