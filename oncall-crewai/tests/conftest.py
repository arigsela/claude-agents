"""Shared test fixtures for oncall-crewai."""

import pytest


@pytest.fixture(autouse=True)
def reset_client_singletons():
    """Reset cached K8s and GitHub client singletons between tests.

    Both tools modules use module-level singletons for client caching.
    Without resetting, test mocks from one test leak into the next.
    """
    yield

    # Reset after each test
    try:
        import k8s_agent.tools
        k8s_agent.tools._k8s_clients = None
    except (ImportError, AttributeError):
        pass

    try:
        import github_agent.tools
        github_agent.tools._github_client = None
    except (ImportError, AttributeError):
        pass
