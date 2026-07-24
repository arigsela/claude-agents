# ==============================================================================
# Knowledge Sources — Auto-Discovery & Embedding Configuration
# ==============================================================================
#
# WHAT THIS FILE DOES:
# Scans config/knowledge/ for supported files (.txt, .json, .csv, .pdf) and
# creates the appropriate CrewAI KnowledgeSource objects for RAG. Also provides
# the embedder configuration needed by CrewAI to generate vector embeddings.
#
# WHY AUTO-DISCOVERY?
# Instead of hardcoding file lists, we scan the directory at startup. This
# means you can add knowledge files and rebuild without touching Python code.
#
# HOW CREWAI RAG WORKS:
# 1. You create KnowledgeSource objects pointing to your files
# 2. You pass them to Agent(knowledge_sources=[...], embedder={...})
# 3. CrewAI automatically chunks, embeds, and indexes the content
# 4. During execution, the agent's context is enriched with relevant chunks
#
# EMBEDDER REQUIREMENT:
# CrewAI uses vector embeddings for RAG retrieval. Anthropic does not provide
# an embeddings API, so we use OpenAI's text-embedding-3-small by default.
# Set OPENAI_API_KEY in your environment for this to work.
#
# CONFIGURATION VIA ENV VARS:
#   KNOWLEDGE_DIR      — Path to knowledge files (default: config/knowledge)
#   EMBEDDER_PROVIDER  — Embedding provider (default: openai)
#   EMBEDDER_MODEL     — Embedding model name (default: text-embedding-3-small)
# ==============================================================================

import os
from pathlib import Path
from typing import Any

from shared.logging_config import setup_logging

logger = setup_logging("shared.knowledge")

# Supported file extensions mapped to their CrewAI KnowledgeSource classes.
# We import lazily inside load_knowledge_sources() to avoid import errors
# if optional dependencies (like pdfplumber) are not installed.
SUPPORTED_EXTENSIONS = {".txt", ".json", ".csv", ".pdf"}


def get_embedder_config() -> dict[str, Any]:
    """
    Return the embedder configuration dict for CrewAI.

    CrewAI requires an embedder to generate vector embeddings for RAG.
    This is passed to Agent(embedder=...) or Crew(embedder=...).

    Returns:
        Dict with 'provider' and 'config' keys, e.g.:
        {"provider": "openai", "config": {"model": "text-embedding-3-small"}}
    """
    provider = os.environ.get("EMBEDDER_PROVIDER", "openai")
    model = os.environ.get("EMBEDDER_MODEL", "text-embedding-3-small")

    return {
        "provider": provider,
        "config": {
            "model": model,
        },
    }


def load_knowledge_sources() -> list:
    """
    Scan the knowledge directory and create CrewAI KnowledgeSource objects.

    Auto-discovers files in KNOWLEDGE_DIR (default: config/knowledge/) and
    groups them by extension. Each group gets the appropriate KnowledgeSource:
      - .txt  -> TextFileKnowledgeSource
      - .json -> JSONKnowledgeSource
      - .csv  -> CSVKnowledgeSource
      - .pdf  -> PDFKnowledgeSource (requires pdfplumber)

    Returns:
        List of CrewAI KnowledgeSource objects. Empty list if no files found
        or if the knowledge directory does not exist.
    """
    knowledge_dir = os.environ.get("KNOWLEDGE_DIR", "config/knowledge")
    knowledge_path = Path(knowledge_dir)

    if not knowledge_path.exists():
        logger.info(f"Knowledge directory not found: {knowledge_path} — skipping RAG")
        return []

    # Group discovered files by extension
    files_by_ext: dict[str, list[str]] = {}
    for file_path in sorted(knowledge_path.iterdir()):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            ext = file_path.suffix.lower()
            files_by_ext.setdefault(ext, []).append(str(file_path))

    if not files_by_ext:
        logger.info(f"No supported files found in {knowledge_path} — skipping RAG")
        return []

    # Build knowledge source objects for each file type
    sources: list = []

    if ".txt" in files_by_ext:
        from crewai.knowledge.source.text_file_knowledge_source import (
            TextFileKnowledgeSource,
        )
        sources.append(TextFileKnowledgeSource(file_paths=files_by_ext[".txt"]))
        logger.info(f"Loaded {len(files_by_ext['.txt'])} .txt knowledge file(s)")

    if ".json" in files_by_ext:
        from crewai.knowledge.source.json_knowledge_source import (
            JSONKnowledgeSource,
        )
        sources.append(JSONKnowledgeSource(file_paths=files_by_ext[".json"]))
        logger.info(f"Loaded {len(files_by_ext['.json'])} .json knowledge file(s)")

    if ".csv" in files_by_ext:
        from crewai.knowledge.source.csv_knowledge_source import (
            CSVKnowledgeSource,
        )
        sources.append(CSVKnowledgeSource(file_paths=files_by_ext[".csv"]))
        logger.info(f"Loaded {len(files_by_ext['.csv'])} .csv knowledge file(s)")

    if ".pdf" in files_by_ext:
        try:
            from crewai.knowledge.source.pdf_knowledge_source import (
                PDFKnowledgeSource,
            )
            sources.append(PDFKnowledgeSource(file_paths=files_by_ext[".pdf"]))
            logger.info(f"Loaded {len(files_by_ext['.pdf'])} .pdf knowledge file(s)")
        except ImportError:
            logger.warning(
                "pdfplumber not installed — skipping .pdf files. "
                "Install with: pip install pdfplumber"
            )

    logger.info(f"Total knowledge sources created: {len(sources)}")
    return sources

