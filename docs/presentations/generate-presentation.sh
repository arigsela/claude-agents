#!/bin/bash

# Script to generate reveal.js presentation from markdown

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🎬 Generating AI Agents DevOps Demo Presentation..."

# Check if marp is installed
if ! command -v marp &> /dev/null; then
    echo "📦 Installing Marp CLI..."
    npm install -g @marp-team/marp-cli
fi

# Generate the presentation
echo "🔨 Building presentation..."
marp ai-agents-devops-demo.md \
    --theme default \
    --html \
    --allow-local-files \
    -o ai-agents-devops-demo.html

echo "✅ Presentation generated successfully!"
echo "📂 Location: $SCRIPT_DIR/ai-agents-devops-demo.html"
echo ""
echo "🌐 To view the presentation:"
echo "   open ai-agents-devops-demo.html"
echo ""
echo "💡 Pro tip: Use arrow keys or space to navigate slides"
echo "   Press 'f' for fullscreen, 'o' for overview mode"
