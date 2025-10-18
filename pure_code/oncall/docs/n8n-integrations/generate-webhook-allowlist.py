#!/usr/bin/env python3
"""
Generate combined IP allowlist for n8n webhook ingress.
Merges Power Automate IPs with Microsoft Graph API IPs.

Usage:
    python3 generate-webhook-allowlist.py > combined-webhook-ips.txt
"""

import re
from pathlib import Path

def extract_ips_from_file(filepath):
    """Extract IP addresses/ranges from a file, ignoring comments and blank lines."""
    ips = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and blank lines
                if not line or line.startswith('#'):
                    continue
                # Extract IP/CIDR (handle arrows from numbered lists)
                if '→' in line:
                    ip = line.split('→')[1].strip()
                else:
                    ip = line.strip()

                # Basic validation: should contain digits and dots or colons
                if ('.' in ip or ':' in ip) and any(c.isdigit() for c in ip):
                    ips.append(ip)
    except FileNotFoundError:
        print(f"# Warning: {filepath} not found", file=sys.stderr)
    return ips

def main():
    script_dir = Path(__file__).parent

    # File paths
    power_automate_file = script_dir / "combined_power_automate_ips.txt"
    graph_api_file = script_dir / "microsoft-graph-webhook-ips.txt"

    print("# Combined IP Allowlist for n8n Webhook Ingress")
    print("# Includes: Power Automate + Microsoft Graph API webhook IPs")
    print("# Generated: 2025-10-10")
    print("# For: n8n-dev-webhook.artemishealth.com")
    print()

    # Extract and combine IPs
    power_automate_ips = extract_ips_from_file(power_automate_file)
    graph_api_ips = extract_ips_from_file(graph_api_file)

    # Remove duplicates while preserving order
    all_ips = list(dict.fromkeys(power_automate_ips + graph_api_ips))

    # Separate IPv4 and IPv6
    ipv4_ips = [ip for ip in all_ips if '.' in ip]
    ipv6_ips = [ip for ip in all_ips if ':' in ip]

    print(f"# Total IPv4 ranges: {len(ipv4_ips)}")
    print(f"# Total IPv6 ranges: {len(ipv6_ips)}")
    print()

    print("# ============================================")
    print("# IPv4 Addresses/Ranges")
    print("# ============================================")
    for ip in ipv4_ips:
        print(ip)

    print()
    print("# ============================================")
    print("# IPv6 Addresses/Ranges (Optional)")
    print("# ============================================")
    for ip in ipv6_ips:
        print(ip)

    print()
    print("# ============================================")
    print("# Kubernetes Ingress Annotation Format")
    print("# ============================================")
    print("# For NGINX Ingress Controller:")
    print(f"# nginx.ingress.kubernetes.io/whitelist-source-range: \"{','.join(ipv4_ips[:10])},...\"")
    print()
    print("# Note: NGINX has a limit on annotation size.")
    print("# Consider using external ConfigMap for large lists.")

if __name__ == "__main__":
    import sys
    main()
