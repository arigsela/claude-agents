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
import os
from pathlib import Path
from crewai.tools import tool

from shared.logging_config import setup_logging

logger = setup_logging("character_creation_agent.tools")


@tool("search_knowledge")
def search_knowledge(query: str) -> str:
    """
    Search the knowledge base for information related to the query.

    Performs keyword-based search across .txt and .json files in the knowledge
    directory. This complements CrewAI's built-in RAG (which uses vector
    similarity) by providing direct keyword matching for precise lookups.

    Use this tool when you need to find specific information about the system,
    its architecture, configuration, APIs, or troubleshooting procedures.

    Args:
        query: The search query describing what information you need.

    Returns:
        Matching excerpts from knowledge files, or a message if nothing was found.
    """
    logger.info(f"Searching knowledge base for: {query[:100]}")

    knowledge_dir = Path(os.environ.get("KNOWLEDGE_DIR", "config/knowledge"))

    if not knowledge_dir.exists():
        return json.dumps({
            "status": "no_knowledge_dir",
            "query": query,
            "message": (
                f"Knowledge directory '{knowledge_dir}' not found. "
                "Add .txt or .json files to this directory to enable search."
            ),
        })

    # Collect searchable files (.txt and .json — these are readable as text)
    searchable_files = sorted(
        f for f in knowledge_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".txt", ".json"}
    )

    if not searchable_files:
        return json.dumps({
            "status": "no_files",
            "query": query,
            "message": (
                f"No .txt or .json files found in '{knowledge_dir}'. "
                "Add knowledge files and rebuild to enable search."
            ),
        })

    # Case-insensitive keyword search across all files
    query_lower = query.lower()
    keywords = query_lower.split()
    matches = []

    for file_path in searchable_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            content_lower = content.lower()

            # Check if any keyword appears in the file
            if any(kw in content_lower for kw in keywords):
                # Extract matching lines for context
                matching_lines = [
                    line.strip()
                    for line in content.splitlines()
                    if any(kw in line.lower() for kw in keywords)
                ]
                # Limit to first 10 matching lines per file
                excerpt = "\n".join(matching_lines[:10])
                matches.append({
                    "file": file_path.name,
                    "excerpt": excerpt,
                    "total_matches": len(matching_lines),
                })
        except Exception as e:
            logger.warning(f"Error reading {file_path}: {e}")

    if not matches:
        return json.dumps({
            "status": "no_matches",
            "query": query,
            "message": f"No matches found for '{query}' across {len(searchable_files)} file(s).",
        })

    return json.dumps({
        "status": "found",
        "query": query,
        "result_count": len(matches),
        "results": matches,
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

