#!/usr/bin/env python3
"""Debug parser with actual k8s-analyzer response."""

import re

# Actual response from k8s-analyzer
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
"""


def _extract_section(content: str, section_pattern: str) -> str:
    """Extract a section from markdown by pattern."""
    # Match section heading (###) and capture until next heading at same or higher level
    # This allows #### subsections within the ### section
    pattern = (
        f"^###\\s+(?:{section_pattern}).*?(?=^###\\s+|\\Z)"
    )
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE | re.DOTALL)

    if match:
        return match.group(0)
    return ""


def main():
    print("=" * 80)
    print("Debug: Section Extraction")
    print("=" * 80)

    # Test Critical section
    print("\n--- Testing Critical Issues extraction ---")
    critical_section = _extract_section(DETAILED_RESPONSE, "Critical Issues|P0")
    print(f"Found: {len(critical_section)} characters")
    if critical_section:
        print(f"Content preview:\n{critical_section[:200]}...")
    else:
        print("NOT FOUND")

    # Test High Priority section
    print("\n--- Testing High Priority extraction ---")
    high_section = _extract_section(DETAILED_RESPONSE, "High Priority|P1")
    print(f"Found: {len(high_section)} characters")
    if high_section:
        print(f"Content preview:\n{high_section[:200]}...")
    else:
        print("NOT FOUND")

    # Test Warnings section
    print("\n--- Testing Warnings extraction ---")
    warning_section = _extract_section(DETAILED_RESPONSE, "Warnings|P2|P3")
    print(f"Found: {len(warning_section)} characters")
    if warning_section:
        print(f"Content preview:\n{warning_section[:500]}...")

        # Now test bullet point extraction
        print("\n--- Testing bullet point extraction from Warnings ---")
        pattern = r"^[\s]*[-*]\s+(.+?)(?=\n[\s]*[-*#]|\n\n\n|$)"
        matches = re.finditer(pattern, warning_section, re.MULTILINE | re.DOTALL)

        bullet_count = 0
        for match in matches:
            bullet_count += 1
            issue_text = match.group(1).strip()
            print(f"\nBullet {bullet_count}:")
            print(f"  Length: {len(issue_text)} chars")
            print(f"  Preview: {issue_text[:150]}...")
    else:
        print("NOT FOUND")


if __name__ == "__main__":
    main()
