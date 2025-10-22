#!/usr/bin/env python3
"""Test the _extract_section function."""

import re

def _extract_section(content: str, section_pattern: str) -> str:
    """Extract a section from markdown by pattern."""
    # Match section heading (###) and capture until next heading at same or higher level
    pattern = (
        f"^###\\s+(?:{section_pattern}).*?(?=^###\\s+|\\Z)"
    )
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE | re.DOTALL)

    if match:
        return match.group(0)
    return ""

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

print("Extracting 'Key Findings' section...")
section = _extract_section(test_response, "Key Findings")
print(f"Section length: {len(section)} chars")
print(f"Contains numbered items: {'1. **MySQL**' in section}")
print(f"Content preview:\n{section[:500]}\n...")
