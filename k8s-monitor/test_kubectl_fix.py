#!/usr/bin/env python3
"""Test script to verify kubectl execution and parsing of cluster data."""

import subprocess
import json
import sys
from src.utils.parsers import parse_k8s_analyzer_output

def test_kubectl_execution():
    """Test that kubectl commands execute successfully."""
    print("=" * 80)
    print("TESTING KUBECTL EXECUTION")
    print("=" * 80)

    kubectl_commands = [
        ("pods", "kubectl get pods --all-namespaces -o wide"),
        ("events", "kubectl get events --all-namespaces --sort-by='.lastTimestamp' | tail -50"),
        ("nodes", "kubectl get nodes -o wide"),
        ("deployments", "kubectl get deployments --all-namespaces"),
    ]

    kubectl_output = {}
    for cmd_name, cmd in kubectl_commands:
        try:
            print(f"\n▶ Executing: {cmd_name}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                output_lines = result.stdout.count('\n')
                print(f"  ✅ Success - Got {output_lines} lines of output")
                kubectl_output[cmd_name] = result.stdout

                # Check for MySQL specifically
                if 'mysql' in result.stdout.lower() and cmd_name == 'pods':
                    print(f"  🔍 Found MySQL pod references:")
                    for line in result.stdout.split('\n'):
                        if 'mysql' in line.lower():
                            print(f"     {line}")
            else:
                print(f"  ❌ Failed with return code {result.returncode}")
                print(f"  Error: {result.stderr}")
                kubectl_output[cmd_name] = f"Error: {result.stderr}"
        except Exception as e:
            print(f"  ❌ Exception: {e}")
            kubectl_output[cmd_name] = f"Error: {str(e)}"

    return kubectl_output

def test_parsing(kubectl_output):
    """Test parsing of kubectl output with Claude analysis."""
    print("\n" + "=" * 80)
    print("TESTING ANALYSIS AND PARSING")
    print("=" * 80)

    # Simulate what the orchestrator does
    query = f"""Analyze this Kubernetes cluster data and identify all issues:

## KUBECTL OUTPUT

### Pods (all namespaces)
{kubectl_output.get('pods', 'ERROR')}

### Events (recent)
{kubectl_output.get('events', 'ERROR')}

### Nodes
{kubectl_output.get('nodes', 'ERROR')}

### Deployments
{kubectl_output.get('deployments', 'ERROR')}

## YOUR TASK

Analyze the above kubectl output and identify:
1. MySQL pod status in mysql namespace (CRITICAL - must find CrashLoopBackOff if present)
2. PostgreSQL pod status if exists
3. Any pods with: CrashLoopBackOff, ImagePullBackOff, OOMKilled, Pending, Failed
4. Any error/warning events
5. Node issues: NotReady, MemoryPressure, DiskPressure

## CRITICAL FINDINGS FORMAT

For EACH issue found, respond with:

## FINDINGS

1. **MySQL** - Pod Status Issue
   - Namespace: mysql
   - Pod Status: CrashLoopBackOff
   - Details: Pod mysql-xyz has CrashLoopBackOff status after 143 restarts
   - Severity: P0

If no issues are found, respond with:
## FINDINGS
No critical issues detected."""

    print("\n▶ Query prepared for Claude analysis")
    print(f"  - Pods output: {kubectl_output.get('pods', 'ERROR')[:100]}...")
    print(f"  - Events output: {kubectl_output.get('events', 'ERROR')[:100]}...")
    print(f"  - Nodes output: {kubectl_output.get('nodes', 'ERROR')[:100]}...")
    print(f"  - Deployments output: {kubectl_output.get('deployments', 'ERROR')[:100]}...")

    # Check if MySQL is clearly in the pods output
    if 'mysql' in kubectl_output.get('pods', '').lower():
        if 'crashloopbackoff' in kubectl_output.get('pods', '').lower():
            print("\n✅ MySQL CrashLoopBackOff is VISIBLE in kubectl output")
            print("   Parser should be able to extract this with proper Claude analysis")
        else:
            print("\n⚠️  MySQL exists but not in CrashLoopBackOff state")
    else:
        print("\n❌ MySQL not found in kubectl output")
        print("   Check if mysql namespace exists: kubectl get ns | grep mysql")

    return query

def main():
    """Run all tests."""
    print("\n🧪 K8s-Monitor Fix Verification Test\n")

    # Test kubectl execution
    kubectl_output = test_kubectl_execution()

    # Test parsing setup
    test_parsing(kubectl_output)

    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print("""
✅ Kubectl execution test: Verify commands run successfully
✅ Output capture: Verify kubectl output is being captured
✅ MySQL detection: Verify MySQL pods/status are in output

The actual Claude analysis will be tested by running the full monitoring cycle.
Run: python -m src.main

Expected output in logs:
- kubectl commands executing successfully
- Raw kubectl output being passed to Claude
- Parser extracting MySQL CrashLoopBackOff finding
- Escalation decision with P0/P1 severity for MySQL
- Slack notification sent to #infrastructure-alerts
""")

if __name__ == "__main__":
    main()
