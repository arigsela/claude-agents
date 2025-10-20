#!/bin/bash
# Generate Kubernetes ConfigMaps from .claude/ configuration files
# This script creates ConfigMaps that can be managed via GitOps

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$PROJECT_ROOT/k8s/configmaps"

echo "=========================================="
echo "Generating ConfigMaps from .claude/"
echo "=========================================="
echo ""

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Function to escape and indent YAML content for ConfigMap
indent_yaml() {
    sed 's/^/    /'
}

# 1. Generate cluster-context ConfigMap
echo "1. Generating cluster-context.yaml..."
cat > "$OUTPUT_DIR/cluster-context.yaml" <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: eks-agent-cluster-context
  namespace: eks-monitoring
  labels:
    app: eks-monitoring-agent
    component: configuration
  annotations:
    description: "Cluster-specific context loaded on EVERY monitoring cycle (no restart needed)"
data:
  CLAUDE.md: |
EOF

# Append the CLAUDE.md content with proper indentation
cat "$PROJECT_ROOT/.claude/CLAUDE.md" | indent_yaml >> "$OUTPUT_DIR/cluster-context.yaml"

echo "✅ Created: cluster-context.yaml"

# 2. Generate subagents ConfigMap (all 6 subagents)
echo "2. Generating subagents.yaml (all 6 subagents)..."
cat > "$OUTPUT_DIR/subagents.yaml" <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: eks-agent-subagents
  namespace: eks-monitoring
  labels:
    app: eks-monitoring-agent
    component: configuration
  annotations:
    description: "Subagent definitions - REQUIRES POD RESTART to apply changes"
data:
EOF

# Add each subagent file
for agent_file in "$PROJECT_ROOT/.claude/agents"/*.md; do
    agent_name=$(basename "$agent_file")
    echo "   Adding: $agent_name"
    echo "  $agent_name: |" >> "$OUTPUT_DIR/subagents.yaml"
    cat "$agent_file" | indent_yaml >> "$OUTPUT_DIR/subagents.yaml"
done

echo "✅ Created: subagents.yaml (6 subagents)"

# 3. Generate settings ConfigMap
echo "3. Generating settings.yaml..."
cat > "$OUTPUT_DIR/settings.yaml" <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: eks-agent-settings
  namespace: eks-monitoring
  labels:
    app: eks-monitoring-agent
    component: configuration
  annotations:
    description: "Safety hooks configuration - REQUIRES POD RESTART to apply changes"
data:
  settings.json: |
EOF

# Append the settings.json content with proper indentation
cat "$PROJECT_ROOT/.claude/settings.json" | indent_yaml >> "$OUTPUT_DIR/settings.yaml"

echo "✅ Created: settings.yaml"

echo ""
echo "=========================================="
echo "ConfigMaps Generated Successfully!"
echo "=========================================="
echo ""
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Files created:"
echo "  - cluster-context.yaml  (CLAUDE.md - reloaded every cycle)"
echo "  - subagents.yaml        (6 subagent definitions)"
echo "  - settings.yaml         (hooks configuration)"
echo ""
echo "Next steps:"
echo "  1. Review generated ConfigMaps"
echo "  2. Apply to cluster: kubectl apply -f k8s/configmaps/"
echo "  3. Verify: kubectl get configmaps -n eks-monitoring"
echo "  4. Update these via GitOps (ArgoCD will sync automatically)"
echo ""
echo "GitOps Workflow:"
echo "  - Edit k8s/configmaps/cluster-context.yaml in Git"
echo "  - Commit and push changes"
echo "  - ArgoCD syncs ConfigMap"
echo "  - For CLAUDE.md: Changes apply on next cycle (no restart)"
echo "  - For subagents/settings: Restart pod to apply changes"
echo ""
