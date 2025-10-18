#!/usr/bin/env python3
"""Comprehensive cluster health check for dev-eks"""
import json
import subprocess
import sys
from datetime import datetime
from collections import defaultdict

# Critical namespaces from CLAUDE.md
INFRASTRUCTURE_NAMESPACES = [
    "kube-system", "karpenter", "datadog-operator-dev",
    "actions-runner-controller-dev", "crossplane-system", "cert-manager-dev",
    "keda-controller-dev", "karpenter-controller-dev", "kyverno-dev",
    "kyverno-policies-dev", "n8n-dev", "nginx-ingress-dev", "versprite-security"
]

APPLICATION_NAMESPACES = [
    "artemis-app-preprod", "artemis-auth-kafka-consumer-preprod",
    "artemis-auth-keycloak-preprod", "artemis-auth-preprod", "artemis-preprod",
    "chronos-preprod", "delivery-preprod", "excel-writer-preprod",
    "export-manager-kafka-preprod", "export-manager-preprod",
    "metric-usage-service-preprod", "plutus-celery-worker-preprod",
    "plutus-kafka-worker-preprod", "powerpoint-writer-preprod"
]

def run_kubectl(args):
    """Run kubectl command and return JSON output"""
    try:
        result = subprocess.run(
            ["kubectl"] + args,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
        return None
    except Exception as e:
        print(f"Error running kubectl {' '.join(args)}: {e}", file=sys.stderr)
        return None

def analyze_pod(pod):
    """Analyze a single pod's health"""
    name = pod['metadata']['name']
    namespace = pod['metadata']['namespace']
    phase = pod['status'].get('phase', 'Unknown')

    issues = []
    restart_count = 0
    status = "HEALTHY"

    # Check container statuses
    for container in pod['status'].get('containerStatuses', []):
        restart_count += container.get('restartCount', 0)
        state = container.get('state', {})

        if 'waiting' in state:
            reason = state['waiting'].get('reason', '')
            if reason == 'CrashLoopBackOff':
                status = "CRITICAL"
                issues.append(f"{container['name']}: CrashLoopBackOff ({restart_count} restarts)")
            elif reason in ['ImagePullBackOff', 'ErrImagePull']:
                status = "CRITICAL"
                issues.append(f"{container['name']}: {reason}")
            elif reason:
                if status == "HEALTHY":
                    status = "DEGRADED"
                issues.append(f"{container['name']}: {reason}")

        elif 'terminated' in state:
            reason = state['terminated'].get('reason', '')
            if reason in ['OOMKilled', 'Error']:
                status = "CRITICAL"
                issues.append(f"{container['name']}: {reason}")

        elif 'running' in state:
            if restart_count > 0:
                if status == "HEALTHY":
                    status = "DEGRADED"
                issues.append(f"{container['name']}: {restart_count} restarts")

    # Check if pod is pending
    if phase == "Pending":
        status = "DEGRADED"
        issues.append("Pod stuck in Pending state")
    elif phase in ["Failed", "Unknown"]:
        status = "CRITICAL"
        issues.append(f"Pod in {phase} state")

    return {
        'name': name,
        'namespace': namespace,
        'phase': phase,
        'restart_count': restart_count,
        'status': status,
        'issues': issues
    }

def check_namespace(namespace):
    """Check all pods in a namespace"""
    pods_data = run_kubectl([
        "get", "pods", "-n", namespace,
        "--field-selector=status.phase!=Succeeded",
        "-o", "json"
    ])

    if not pods_data or not pods_data.get('items'):
        return {
            'status': 'HEALTHY',
            'total_pods': 0,
            'running_pods': 0,
            'issues': []
        }

    pods = pods_data['items']
    results = [analyze_pod(pod) for pod in pods]

    critical_count = sum(1 for r in results if r['status'] == 'CRITICAL')
    degraded_count = sum(1 for r in results if r['status'] == 'DEGRADED')
    running_count = sum(1 for r in results if r['phase'] == 'Running')

    if critical_count > 0:
        ns_status = 'CRITICAL'
    elif degraded_count > 0:
        ns_status = 'DEGRADED'
    else:
        ns_status = 'HEALTHY'

    issues = [item for r in results for item in r['issues'] if r['issues']]

    return {
        'status': ns_status,
        'total_pods': len(pods),
        'running_pods': running_count,
        'issues': issues,
        'problem_pods': [r for r in results if r['status'] != 'HEALTHY']
    }

def get_proteus_namespaces():
    """Find all proteus-* namespaces"""
    ns_data = run_kubectl(["get", "namespaces", "-o", "json"])
    if not ns_data:
        return []

    return [
        ns['metadata']['name']
        for ns in ns_data['items']
        if ns['metadata']['name'].startswith('proteus-')
    ]

def get_node_status():
    """Get node health summary"""
    nodes_data = run_kubectl(["get", "nodes", "-o", "json"])
    if not nodes_data:
        return {"total": 0, "ready": 0, "not_ready": 0}

    total = len(nodes_data['items'])
    ready = 0

    for node in nodes_data['items']:
        for condition in node['status']['conditions']:
            if condition['type'] == 'Ready' and condition['status'] == 'True':
                ready += 1
                break

    return {
        "total": total,
        "ready": ready,
        "not_ready": total - ready
    }

def main():
    print("=" * 80)
    print(f"DEV-EKS CLUSTER HEALTH CHECK")
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z")
    print("=" * 80)
    print()

    # Check cluster context
    try:
        context = subprocess.check_output(
            ["kubectl", "config", "current-context"],
            text=True
        ).strip()
        if context != "dev-eks":
            print(f"WARNING: Current context is '{context}', expected 'dev-eks'")
            print()
    except:
        pass

    # Node status
    print("NODE STATUS:")
    node_status = get_node_status()
    print(f"  Total: {node_status['total']}")
    print(f"  Ready: {node_status['ready']}")
    print(f"  Not Ready: {node_status['not_ready']}")
    print()

    # Infrastructure namespaces
    print("INFRASTRUCTURE NAMESPACES:")
    print("-" * 80)
    infra_results = {}
    for ns in INFRASTRUCTURE_NAMESPACES:
        result = check_namespace(ns)
        infra_results[ns] = result
        icon = {"HEALTHY": "✓", "DEGRADED": "⚠", "CRITICAL": "✗"}.get(result['status'], "?")
        print(f"{icon} {ns:40} {result['status']:10} {result['running_pods']}/{result['total_pods']} pods")
        if result['issues']:
            for issue in result['issues'][:3]:  # Show first 3 issues
                print(f"    - {issue}")
    print()

    # Application namespaces
    print("APPLICATION NAMESPACES:")
    print("-" * 80)
    app_results = {}
    for ns in APPLICATION_NAMESPACES:
        result = check_namespace(ns)
        app_results[ns] = result
        icon = {"HEALTHY": "✓", "DEGRADED": "⚠", "CRITICAL": "✗"}.get(result['status'], "?")
        print(f"{icon} {ns:40} {result['status']:10} {result['running_pods']}/{result['total_pods']} pods")
        if result['issues']:
            for issue in result['issues'][:3]:
                print(f"    - {issue}")
    print()

    # Proteus namespaces
    print("PROTEUS-* NAMESPACES:")
    print("-" * 80)
    proteus_ns = get_proteus_namespaces()
    proteus_results = {}
    for ns in proteus_ns:
        result = check_namespace(ns)
        proteus_results[ns] = result
        icon = {"HEALTHY": "✓", "DEGRADED": "⚠", "CRITICAL": "✗"}.get(result['status'], "?")
        print(f"{icon} {ns:40} {result['status']:10} {result['running_pods']}/{result['total_pods']} pods")
        if result['issues']:
            for issue in result['issues'][:2]:
                print(f"    - {issue}")
    print()

    # Overall summary
    all_results = {**infra_results, **app_results, **proteus_results}
    critical_ns = [ns for ns, r in all_results.items() if r['status'] == 'CRITICAL']
    degraded_ns = [ns for ns, r in all_results.items() if r['status'] == 'DEGRADED']

    print("=" * 80)
    print("OVERALL HEALTH SUMMARY:")
    print("-" * 80)

    if critical_ns:
        overall_status = "CRITICAL"
        print(f"Status: CRITICAL ({len(critical_ns)} critical namespaces)")
        print(f"Critical namespaces: {', '.join(critical_ns)}")
    elif degraded_ns:
        overall_status = "DEGRADED"
        print(f"Status: DEGRADED ({len(degraded_ns)} degraded namespaces)")
        print(f"Degraded namespaces: {', '.join(degraded_ns)}")
    else:
        overall_status = "HEALTHY"
        print("Status: HEALTHY - All systems operational")

    print()
    print(f"Infrastructure: {len(INFRASTRUCTURE_NAMESPACES)} namespaces checked")
    print(f"Applications: {len(APPLICATION_NAMESPACES)} namespaces checked")
    print(f"Proteus: {len(proteus_ns)} namespaces checked")
    print()

    # Critical issues detail
    if critical_ns:
        print("=" * 80)
        print("CRITICAL ISSUES DETAIL:")
        print("-" * 80)
        for ns in critical_ns:
            result = all_results[ns]
            print(f"\n{ns}:")
            for pod in result.get('problem_pods', []):
                if pod['status'] == 'CRITICAL':
                    print(f"  Pod: {pod['name']}")
                    print(f"  Phase: {pod['phase']}")
                    print(f"  Restart Count: {pod['restart_count']}")
                    for issue in pod['issues']:
                        print(f"    - {issue}")

    print("=" * 80)

    # Exit code based on health
    if overall_status == "CRITICAL":
        sys.exit(2)
    elif overall_status == "DEGRADED":
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
