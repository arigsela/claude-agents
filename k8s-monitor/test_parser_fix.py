#!/usr/bin/env python3
"""Test the parser fix with actual response format from logs."""

from src.utils.parsers import parse_k8s_analyzer_output

# This is the actual response format from the logs
test_response = """I'll use the k8s-analyzer agent to check the K3s cluster health comprehensively.

The k8s-analyzer agent has completed a comprehensive health check of your K3s cluster. Here's a summary of the findings:

## **Cluster Status: DEGRADED** ⚠️

### Key Findings:

**Infrastructure Health:** ✅ HEALTHY
- All 4 nodes ready and reporting normally
- No memory, disk, or PID pressure
- Resource utilization is well within limits (31% CPU, 15% memory)

**Critical Issues Requiring Immediate Action:**

1. **MySQL** - All replicas down (0/1 pods running, CrashLoopBackOff detected)
   - Impact: Database layer unavailable, chores-tracker-backend cannot connect
   - Max Downtime: 0 minutes ❌ EXCEEDED
   - Recommended Action: Check MySQL pod logs and restart if needed

2. **PostgreSQL** - Single replica experiencing high memory usage (92% of limit)
   - Impact: n8n workflows may be affected if memory pressure causes OOM
   - Status: Still running but at risk
   - Recommended Action: Monitor memory usage, consider increasing limits

3. **Ingress Controller** - nginx-ingress showing degraded performance
   - Status: Running but with increased latency
   - Impact: External access to services may be slow

### Summary:
- **Cluster Status**: DEGRADED
- **Nodes**: 4/4 Ready ✅
- **Pods Running**: 45/48 (3 pods not running)
- **Critical P0 Issues**: 1 (MySQL completely down)
- **High Priority P1 Issues**: 2 (PostgreSQL memory, Ingress)
- **Expected Resolution Time**: Investigate MySQL immediately
"""

def test_parser():
    """Test the parser with the actual response."""
    print("Testing parser with actual response format...\n")

    findings = parse_k8s_analyzer_output(test_response)

    print(f"✅ Parser returned {len(findings)} findings\n")

    if not findings:
        print("❌ FAILED: Parser returned 0 findings but response contains critical issues!")
        print("\nExpected to find:")
        print("  - MySQL (Critical, P0)")
        print("  - PostgreSQL (High, P1)")
        print("  - Ingress Controller (High, P1)")
        return False

    print("Parsed Findings:")
    print("-" * 80)
    for i, finding in enumerate(findings, 1):
        print(f"{i}. Service: {finding.service if hasattr(finding, 'service') else 'N/A'}")
        print(f"   Severity: {finding.severity if hasattr(finding, 'severity') else 'N/A'}")
        print(f"   Priority: {finding.priority if hasattr(finding, 'priority') else 'N/A'}")
        print(f"   Description: {finding.description if hasattr(finding, 'description') else 'N/A'}")
        print()

    # Verify we got the critical issues
    descriptions = [f.description if hasattr(f, 'description') else '' for f in findings]

    has_mysql = any('MySQL' in d for d in descriptions)
    has_postgresql = any('PostgreSQL' in d for d in descriptions)

    if has_mysql and has_postgresql:
        print("✅ SUCCESS: Parser correctly extracted MySQL and PostgreSQL issues!")
        return True
    else:
        print("❌ FAILED: Parser didn't extract expected issues")
        if not has_mysql:
            print("  - Missing MySQL issue")
        if not has_postgresql:
            print("  - Missing PostgreSQL issue")
        return False

if __name__ == "__main__":
    success = test_parser()
    exit(0 if success else 1)
