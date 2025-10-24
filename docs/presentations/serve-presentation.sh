#!/bin/bash

# Serve presentation using reveal-md server (better than static)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🎬 Starting reveal.js presentation server..."
echo ""
echo "📂 Serving from: $SCRIPT_DIR"
echo "🌐 Open in browser: http://localhost:1948"
echo ""
echo "💡 Press Ctrl+C to stop the server"
echo ""

# Check if reveal-md is installed
if ! command -v reveal-md &> /dev/null; then
    echo "📦 Installing reveal-md..."
    npm install -g reveal-md
fi

# Serve the presentation
reveal-md ai-agents-devops-demo.md \
    --theme night \
    --css reveal-theme.css \
    --highlight-theme monokai \
    --port 1948 \
    --watch
