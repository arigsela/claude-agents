# ==============================================================================
# Sub-Agent Tools — Domain-Specific Capabilities
# ==============================================================================
#
# WHAT ARE TOOLS?
# Tools are Python functions that CrewAI agents can call during execution.
# They give agents the ability to interact with the real world: read files,
# call APIs, query databases, search the web, etc.
#
# HOW THE @tool DECORATOR WORKS:
# The @tool decorator from CrewAI registers a function as an agent tool.
# The function's docstring becomes the tool's description — the LLM reads
# this to decide WHEN to use the tool and WHAT arguments to pass.
#
# BEST PRACTICES:
# 1. Write clear, specific docstrings — the LLM uses these to decide when to call the tool
# 2. Return strings (not objects) — the LLM reads the return value as text
# 3. Handle errors gracefully — return error messages instead of raising exceptions
# 4. Keep tools focused — one tool per capability, not one mega-tool
# 5. Include parameter descriptions — helps the LLM pass correct arguments
#
# TODO: Replace these placeholder tools with your domain-specific tools.
# For a knowledge agent, you might add:
#   - query_knowledge_base(question) — RAG query against knowledge files
#   - get_api_docs(endpoint) — look up API endpoint documentation
#   - search_runbooks(issue) — find troubleshooting guides
# ==============================================================================

import json
from crewai import tool

from shared.logging_config import setup_logging

logger = setup_logging("backend-agent.tools")


@tool("search_knowledge")
def search_knowledge(query: str) -> str:
    """
    Search the knowledge base for information related to the query.

    Use this tool when you need to find specific information about the system,
    its architecture, configuration, APIs, or troubleshooting procedures.

    Args:
        query: The search query describing what information you need.

    Returns:
        Relevant information from the knowledge base, or a message if nothing was found.
    """
    logger.info(f"Searching knowledge base for: {query[:100]}")

    # TODO: Implement actual knowledge search.
    # Options:
    # 1. CrewAI Knowledge sources (built-in RAG)
    # 2. File-based search through config/knowledge/ files
    # 3. External vector DB (Chroma, Pinecone, etc.)
    #
    # For now, return a placeholder that explains what to implement.
    return json.dumps({
        "status": "placeholder",
        "query": query,
        "message": (
            "Knowledge search not yet implemented. "
            "Add your knowledge sources to config/knowledge/ and implement "
            "the search logic in this function. See the README for details."
        ),
    })


@tool("get_system_info")
def get_system_info(component: str = "") -> str:
    """
    Get information about a system component.

    Use this tool to look up details about specific parts of the system:
    architecture, services, APIs, database schema, deployment configuration, etc.

    Args:
        component: Name of the component to get info about (e.g., "api", "database", "deployment").
                   Leave empty to get a general system overview.

    Returns:
        JSON string with component information.
    """
    logger.info(f"Getting system info for component: {component or 'overview'}")

    # TODO: Implement actual system info lookup.
    # This could read from:
    # - Static knowledge files in config/knowledge/
    # - API documentation (OpenAPI spec)
    # - Kubernetes API (for deployment status)
    # - Database schema introspection
    return json.dumps({
        "status": "placeholder",
        "component": component or "overview",
        "message": (
            "System info not yet implemented. "
            "Customize this tool for your specific domain."
        ),
    })


@tool("check_health")
def check_health(service_name: str = "") -> str:
    """
    Check the health status of a service or the overall system.

    Use this tool when the user asks about service health, uptime,
    or wants to diagnose if something is running correctly.

    Args:
        service_name: Name of the service to check. Leave empty for all services.

    Returns:
        JSON string with health status information.
    """
    logger.info(f"Checking health for: {service_name or 'all services'}")

    # TODO: Implement actual health checks.
    # This could:
    # - Call health endpoints of known services
    # - Query Kubernetes pod status
    # - Check database connectivity
    return json.dumps({
        "status": "placeholder",
        "service": service_name or "all",
        "message": (
            "Health check not yet implemented. "
            "Add HTTP calls to your service health endpoints here."
        ),
    })

