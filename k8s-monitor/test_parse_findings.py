#!/usr/bin/env python3
"""Test _parse_key_findings_section directly."""

import re
from typing import Any

def _parse_key_findings_section(section: str) -> list[dict[str, Any]]:
    """Parse findings from generic Key Findings section."""
    findings = []

    # Strategy 1: Look for numbered items like "1. **MySQL** - Issue"
    numbered_pattern = r'^\s*\d+\.\s+\*\*([^*]+)\*\*\s*[-–]\s*(.+?)(?=\n\s*\d+\.|\n\n|$)'
    matches = list(re.finditer(numbered_pattern, section, re.MULTILINE | re.DOTALL))

    print(f"Found {len(matches)} numbered items")

    if matches:
        for match in matches:
            service_name = match.group(1).strip()
            description = match.group(2).strip()

            print(f"  - Service: {service_name}")
            print(f"    Desc (first 50): {description[:50]}")
            print(f"    Len: {len(description)}")

            if description and len(description) > 5:
                # Infer severity from context
                match_start = match.start()
                preceding_text = section[:match_start]

                last_critical = preceding_text.rfind('🔴')
                last_warning = preceding_text.rfind('⚠️')
                last_degraded = preceding_text.rfind('DEGRADED')

                print(f"    Last critical: {last_critical}, last warning: {last_warning}, last degraded: {last_degraded}")

                # If we see DEGRADED or 🔴, mark as critical
                if last_degraded > last_critical and last_degraded > last_warning:
                    severity = "critical"
                    priority = "P0"
                elif last_critical > last_warning:
                    severity = "critical"
                    priority = "P0"
                else:
                    severity = "warning"
                    priority = "P2/P3"

                findings.append({
                    "severity": severity,
                    "priority": priority,
                    "description": f"{service_name} - {description}",
                })
                print(f"    Added: {severity}/{priority}")

        if findings:
            return findings

    return findings

# Extract the section
def _extract_section(content: str, section_pattern: str) -> str:
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

section = _extract_section(test_response, "Key Findings")
print(f"Section length: {len(section)} chars\n")

findings = _parse_key_findings_section(section)
print(f"\nTotal findings returned: {len(findings)}")
for f in findings:
    print(f"  - {f}")
