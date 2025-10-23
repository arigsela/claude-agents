#!/bin/bash
# Quick skills integration test - no API calls needed
# Just verifies skills are loaded correctly

cd "$(dirname "$0")"

echo "=================================================="
echo "  Quick Skills Integration Test"
echo "=================================================="
echo ""

# Activate venv if exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "⚠️  No venv found, using system Python"
fi

# Run the test
echo ""
echo "Running skills verification..."
echo ""
python test_skills.py

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "=================================================="
    echo "  ✅ Skills Integration Test PASSED"
    echo "=================================================="
    echo ""
    echo "Next steps:"
    echo "  1. Start API server: ./run_api_server.sh"
    echo "  2. Test with queries: see docs/testing-skills-locally.md"
    echo "  3. Or use Swagger UI: open http://localhost:8000/docs"
else
    echo ""
    echo "=================================================="
    echo "  ❌ Skills Integration Test FAILED"
    echo "=================================================="
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check that .claude/skills/ directory exists"
    echo "  2. Verify k8s-failure-patterns.md and homelab-runbooks.md are present"
    echo "  3. See docs/testing-skills-locally.md for more help"
fi

exit $EXIT_CODE
