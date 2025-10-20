#!/bin/bash
# Safe daemon startup script - ensures correct cluster context

set -e

# Load .env to get KUBECONFIG
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep KUBECONFIG | xargs)
    export $(grep -v '^#' .env | grep CLUSTER_NAME | xargs)
fi

KUBECONFIG=${KUBECONFIG:-~/.kube/config}
CLUSTER_NAME=${CLUSTER_NAME:-unknown}

echo "=================================================="
echo "EKS Monitoring Daemon - Safe Startup"
echo "=================================================="
echo "Target cluster: $CLUSTER_NAME"
echo "Kubeconfig: $KUBECONFIG"
echo ""

# Check if kubeconfig exists
if [ ! -f "$KUBECONFIG" ]; then
    echo "ERROR: Kubeconfig not found at $KUBECONFIG"
    exit 1
fi

# Get current context
CURRENT_CONTEXT=$(kubectl --kubeconfig="$KUBECONFIG" config current-context 2>/dev/null || echo "none")
echo "Current context in kubeconfig: $CURRENT_CONTEXT"

# If cluster name is set and doesn't match current context, switch
if [ "$CLUSTER_NAME" != "unknown" ] && [ "$CURRENT_CONTEXT" != "$CLUSTER_NAME" ]; then
    echo ""
    echo "⚠️  WARNING: Current context ($CURRENT_CONTEXT) != Target cluster ($CLUSTER_NAME)"
    echo "Switching to $CLUSTER_NAME..."

    if kubectl --kubeconfig="$KUBECONFIG" config use-context "$CLUSTER_NAME" 2>&1; then
        echo "✓ Successfully switched to $CLUSTER_NAME"
    else
        echo "ERROR: Failed to switch to $CLUSTER_NAME"
        echo "Available contexts:"
        kubectl --kubeconfig="$KUBECONFIG" config get-contexts
        exit 1
    fi
else
    echo "✓ Context matches target cluster: $CLUSTER_NAME"
fi

# Verify context one more time
FINAL_CONTEXT=$(kubectl --kubeconfig="$KUBECONFIG" config current-context)
echo ""
echo "Final verification:"
echo "  Kubeconfig current-context: $FINAL_CONTEXT"
echo "  Daemon will monitor: $CLUSTER_NAME"

if [ "$FINAL_CONTEXT" != "$CLUSTER_NAME" ]; then
    echo ""
    echo "ERROR: Context mismatch detected!"
    echo "  Expected: $CLUSTER_NAME"
    echo "  Actual: $FINAL_CONTEXT"
    echo ""
    echo "This will cause the daemon to monitor the wrong cluster."
    echo "Please fix the context and try again."
    exit 1
fi

echo ""
echo "✓ All checks passed - starting daemon..."
echo "=================================================="
echo ""

# Start the daemon
exec python3 monitor_daemon.py
