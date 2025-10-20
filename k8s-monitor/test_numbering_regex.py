#!/usr/bin/env python3
"""Debug numbered list regex."""

import re

TEXT = """### Minor Issues Found (No Immediate Action Needed)
1. **route53-updater**: Wrong ECR region in image config (P3 service, low priority fix)
2. **ECR secret warnings**: Cosmetic warnings during secret rotation, all pods healthy
3. **mysql ArgoCD status**: Shows "Progressing" which is normal during continuous sync

### Resource Utilization
"""

pattern = r"^\s*\d+\.\s+(.+?)(?=^\s*\d+\.|\n\n|$)"

matches = list(re.finditer(pattern, TEXT, re.MULTILINE | re.DOTALL))

print(f"Found {len(matches)} matches:")
for i, match in enumerate(matches, 1):
    print(f"\n{i}. Match:")
    print(f"   Text: {match.group(1)[:100]}...")
    print(f"   Full length: {len(match.group(1))}")
