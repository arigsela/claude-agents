#!/bin/bash
# Build both MCP servers from source
# This script builds the Kubernetes and GitHub MCP servers and creates wrapper scripts

set -e  # Exit on error

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=== Building MCP Servers ==="
echo "Project root: $PROJECT_ROOT"
echo ""

# Create bin directory
mkdir -p bin

# Build Kubernetes MCP Server
echo "================================================"
echo "Building Kubernetes MCP Server..."
echo "================================================"
cd docs/kubernetes-mcp-server

if [ ! -f "go.mod" ]; then
    echo "Error: kubernetes-mcp-server source not found in docs/kubernetes-mcp-server/"
    exit 1
fi

make build
if [ -f "kubernetes-mcp-server" ]; then
    cp kubernetes-mcp-server ../../bin/
    echo "✅ Kubernetes MCP Server built successfully"
else
    echo "❌ Failed to build kubernetes-mcp-server"
    exit 1
fi

cd "$PROJECT_ROOT"
echo ""

# Build GitHub MCP Server
echo "================================================"
echo "Building GitHub MCP Server..."
echo "================================================"
cd docs/github-mcp-server

if [ ! -f "go.mod" ]; then
    echo "Error: github-mcp-server source not found in docs/github-mcp-server/"
    exit 1
fi

go build -o github-mcp-server ./cmd/github-mcp-server
if [ -f "github-mcp-server" ]; then
    cp github-mcp-server ../../bin/
    echo "✅ GitHub MCP Server built successfully"
else
    echo "❌ Failed to build github-mcp-server"
    exit 1
fi

cd "$PROJECT_ROOT"
echo ""

# Create wrapper scripts
echo "================================================"
echo "Creating wrapper scripts..."
echo "================================================"

# Kubernetes MCP wrapper
cat > bin/run-kubernetes-mcp.sh << 'EOF'
#!/bin/bash
# Kubernetes MCP Server wrapper with configuration

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${SCRIPT_DIR}/kubernetes-mcp-server"

# Load environment variables if .env exists
if [ -f "${SCRIPT_DIR}/../.env" ]; then
    set -a
    source "${SCRIPT_DIR}/../.env"
    set +a
fi

# Build configuration flags
FLAGS=""

# Log level (0-9, similar to kubectl -v)
FLAGS="$FLAGS --log-level ${K8S_MCP_LOG_LEVEL:-2}"

# Limit to core and config toolsets (exclude helm for simplicity)
FLAGS="$FLAGS --toolsets config,core"

# Disable multi-cluster for safety (single cluster only)
FLAGS="$FLAGS --disable-multi-cluster"

# Optional: Read-only mode for testing
if [ "$K8S_MCP_READ_ONLY" = "true" ]; then
    FLAGS="$FLAGS --read-only"
fi

# Optional: Disable destructive operations
if [ "$K8S_MCP_DISABLE_DESTRUCTIVE" = "true" ]; then
    FLAGS="$FLAGS --disable-destructive"
fi

# Optional: Custom kubeconfig
if [ -n "$KUBECONFIG" ]; then
    FLAGS="$FLAGS --kubeconfig $KUBECONFIG"
fi

# Run the server
exec "$BIN" $FLAGS "$@"
EOF

# GitHub MCP wrapper
cat > bin/run-github-mcp.sh << 'EOF'
#!/bin/bash
# GitHub MCP Server wrapper with configuration

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${SCRIPT_DIR}/github-mcp-server"

# Load environment variables if .env exists
if [ -f "${SCRIPT_DIR}/../.env" ]; then
    set -a
    source "${SCRIPT_DIR}/../.env"
    set +a
fi

# Verify GitHub token is set
if [ -z "$GITHUB_PERSONAL_ACCESS_TOKEN" ]; then
    echo "Error: GITHUB_PERSONAL_ACCESS_TOKEN not set in environment" >&2
    echo "Please set it in .env file or export it" >&2
    exit 1
fi

# Build configuration flags
# stdio is required for MCP protocol communication
FLAGS="stdio"

# Limit to necessary toolsets (reduces context size, improves tool selection)
TOOLSETS="${GITHUB_TOOLSETS:-context,repos,issues,pull_requests}"
FLAGS="$FLAGS --toolsets $TOOLSETS"

# Optional: Read-only mode for testing
if [ "$GITHUB_READ_ONLY" = "true" ]; then
    FLAGS="$FLAGS --read-only"
fi

# Run the server
exec "$BIN" $FLAGS "$@"
EOF

# Make wrappers executable
chmod +x bin/run-kubernetes-mcp.sh
chmod +x bin/run-github-mcp.sh

echo "✅ Wrapper scripts created and made executable"
echo ""

# Summary
echo "================================================"
echo "=== Build Complete ==="
echo "================================================"
echo ""
echo "Binaries created in bin/:"
echo "  - kubernetes-mcp-server"
echo "  - github-mcp-server"
echo ""
echo "Wrapper scripts created in bin/:"
echo "  - run-kubernetes-mcp.sh"
echo "  - run-github-mcp.sh"
echo ""
echo "Verify installation:"
echo "  ./bin/kubernetes-mcp-server --help"
echo "  ./bin/github-mcp-server --help"
echo ""
echo "Next steps:"
echo "  1. Copy .env.example to .env"
echo "  2. Edit .env with your API keys:"
echo "     - ANTHROPIC_API_KEY"
echo "     - GITHUB_PERSONAL_ACCESS_TOKEN"
echo "  3. Run: python monitor_daemon.py"
echo ""
