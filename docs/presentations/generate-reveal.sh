#!/bin/bash

# Generate reveal.js presentation using reveal-md

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🎬 Generating reveal.js presentation..."

# Check if reveal-md is installed
if ! command -v reveal-md &> /dev/null; then
    echo "📦 Installing reveal-md..."
    npm install -g reveal-md
fi

# Clean up any previous builds
rm -rf /tmp/reveal-build
mkdir -p /tmp/reveal-build

# Generate static HTML presentation in temp directory
echo "🔨 Building presentation with reveal.js..."
reveal-md ai-agents-devops-demo.md \
    --theme night \
    --static /tmp/reveal-build \
    --highlight-theme monokai \
    --css reveal-theme.css

# Move the generated file
cp /tmp/reveal-build/ai-agents-devops-demo.html ./ai-agents-devops-demo-reveal.html

# Clean up
rm -rf /tmp/reveal-build

echo "✅ Presentation generated successfully!"
echo "📂 Location: $SCRIPT_DIR/ai-agents-devops-demo-reveal.html"
echo ""
echo "🌐 To view the presentation:"
echo "   open ai-agents-devops-demo-reveal.html"
echo ""
echo "💡 Navigation:"
echo "   - Arrow keys or Space: Next/previous slide"
echo "   - F: Fullscreen mode"
echo "   - O: Overview mode"
echo "   - Esc: Exit fullscreen/overview"
