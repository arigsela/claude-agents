# ==============================================================================
# Test Configuration & Fixtures
# ==============================================================================
# pytest automatically loads this file before running tests.
# Fixtures defined here are available to ALL test files.
# ==============================================================================

import pytest
import os

# Set test environment variables BEFORE importing any project modules.
# This ensures config.py reads test values instead of real ones.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("API_KEYS", "test-api-key-1,test-api-key-2")
os.environ.setdefault("LOG_FORMAT", "text")
os.environ.setdefault("LOG_LEVEL", "WARNING")  # Reduce log noise in tests


@pytest.fixture(autouse=True)
def reset_singletons():
    """
    Reset any cached singletons between tests.

    The autouse=True means this runs before EVERY test automatically.
    This prevents state from leaking between tests (a common source of
    flaky tests in agent systems).
    """
    yield
    # Add singleton resets here as needed, e.g.:
    # from some_module import _cached_client
    # _cached_client = None

