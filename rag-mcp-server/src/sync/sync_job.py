"""Sync Job - Main entry point for content synchronization.

Orchestrates the full sync process:
1. Load configuration
2. Fetch documents from sources
3. Chunk documents
4. Index changed chunks to Qdrant

Usage:
    # Using config file
    python -m src.sync.sync_job --config config/sync.yaml

    # Using environment variables
    RAG_SYNC_CONFIG=/path/to/sync.yaml python -m src.sync.sync_job

    # Dry run (no actual indexing)
    python -m src.sync.sync_job --config config/sync.yaml --dry-run
"""

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.sync.loader import DocumentLoader
from src.sync.chunker import DocumentChunker
from src.sync.hasher import ContentHasher
from src.tools import rag_store, rag_delete_collection

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics from a sync run."""

    sources_processed: int = 0
    documents_loaded: int = 0
    chunks_created: int = 0
    chunks_indexed: int = 0
    chunks_skipped: int = 0
    chunks_failed: int = 0
    duration_seconds: float = 0.0

    def __str__(self) -> str:
        return (
            f"Sync completed: "
            f"{self.sources_processed} sources, "
            f"{self.documents_loaded} docs, "
            f"{self.chunks_created} chunks, "
            f"{self.chunks_indexed} indexed, "
            f"{self.chunks_skipped} skipped, "
            f"{self.chunks_failed} failed, "
            f"{self.duration_seconds:.1f}s"
        )


class SyncJob:
    """Orchestrates content synchronization to Qdrant.

    Example:
        job = SyncJob(config_path="config/sync.yaml")
        stats = await job.run()
        print(f"Indexed {stats.chunks_indexed} chunks")
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        force_full: bool = False,
    ):
        """Initialize sync job.

        Args:
            config_path: Path to sync configuration YAML
            config: Config dict (alternative to config_path)
            dry_run: If True, don't actually index (log only)
            force_full: If True, ignore cache and reindex everything
        """
        self.dry_run = dry_run
        self.force_full = force_full

        # Load configuration
        if config:
            self.config = config
        elif config_path:
            self.config = self._load_config(config_path)
        else:
            # Try environment variable
            env_config = os.getenv("RAG_SYNC_CONFIG")
            if env_config:
                self.config = self._load_config(env_config)
            else:
                raise ValueError("No config provided. Use --config or RAG_SYNC_CONFIG")

        # Initialize components
        self.loader = DocumentLoader()
        self.chunker = DocumentChunker(
            strategy=self.config.get("chunking", {}).get("strategy", "header"),
            max_chunk_size=self.config.get("chunking", {}).get("max_chunk_size", 1000),
            min_chunk_size=self.config.get("chunking", {}).get("min_chunk_size", 100),
            overlap=self.config.get("chunking", {}).get("overlap", 100),
        )

        # Hash cache for incremental sync
        cache_file = self.config.get("cache_file", ".rag-sync-cache.json")
        self.hasher = ContentHasher(cache_file=cache_file)

        if force_full:
            self.hasher.clear()

    def _load_config(self, path: str) -> Dict[str, Any]:
        """Load sync configuration from YAML file.

        Args:
            path: Path to config file

        Returns:
            Configuration dictionary
        """
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        logger.info(f"Loaded config from {path}")
        return config

    async def run(self) -> SyncStats:
        """Execute the sync job.

        Returns:
            SyncStats with counts and timing
        """
        start_time = datetime.now()
        stats = SyncStats()

        sources = self.config.get("sources", [])
        if not sources:
            logger.warning("No sources configured")
            return stats

        logger.info(f"Starting sync with {len(sources)} sources")
        if self.dry_run:
            logger.info("DRY RUN MODE - no actual indexing will occur")

        for source in sources:
            source_name = source.get("name", "unnamed")
            collection = source.get("collection", "default")

            try:
                logger.info(f"Processing source: {source_name} -> {collection}")

                # Load documents
                documents = self.loader.load_from_config(source)
                stats.documents_loaded += len(documents)
                stats.sources_processed += 1

                if not documents:
                    logger.warning(f"No documents found for source: {source_name}")
                    continue

                # Chunk documents
                chunks = self.chunker.chunk_documents(documents)
                stats.chunks_created += len(chunks)

                # Filter to changed chunks only
                if not self.force_full:
                    chunks = self.hasher.get_changed_chunks(chunks)

                if not chunks:
                    logger.info(f"No changed chunks for source: {source_name}")
                    continue

                # Index chunks
                for chunk in chunks:
                    if self.dry_run:
                        logger.info(
                            f"[DRY RUN] Would index: {chunk.source}:{chunk.chunk_index} "
                            f"({chunk.char_count} chars)"
                        )
                        stats.chunks_skipped += 1
                        continue

                    try:
                        result = await rag_store(
                            content=chunk.content,
                            collection=collection,
                            source=chunk.source,
                            title=chunk.title,
                            chunk_index=chunk.chunk_index,
                            metadata=chunk.metadata,
                            deduplicate=True,
                        )

                        if result.get("success"):
                            if result.get("created"):
                                stats.chunks_indexed += 1
                            else:
                                stats.chunks_skipped += 1  # Deduplicated

                            # Update hash cache
                            self.hasher.update(chunk)
                        else:
                            logger.error(f"Store failed: {result.get('error')}")
                            stats.chunks_failed += 1

                    except Exception as e:
                        logger.error(f"Error indexing chunk: {e}")
                        stats.chunks_failed += 1

            except Exception as e:
                logger.error(f"Error processing source {source_name}: {e}")
                continue

        # Save hash cache
        if not self.dry_run:
            self.hasher.save()

        stats.duration_seconds = (datetime.now() - start_time).total_seconds()
        logger.info(str(stats))

        return stats

    async def clear_collection(self, collection: str) -> bool:
        """Clear a collection (delete and recreate).

        Args:
            collection: Collection name to clear

        Returns:
            True if successful
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would clear collection: {collection}")
            return True

        result = await rag_delete_collection(collection=collection, confirm=True)
        if result.get("success"):
            logger.info(f"Cleared collection: {collection}")
            return True
        else:
            logger.error(f"Failed to clear collection: {result.get('error')}")
            return False


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Sync documents to RAG vector database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Sync using config file
    python -m src.sync.sync_job --config config/sync.yaml

    # Dry run (no indexing)
    python -m src.sync.sync_job --config config/sync.yaml --dry-run

    # Force full reindex
    python -m src.sync.sync_job --config config/sync.yaml --force

    # Set log level
    python -m src.sync.sync_job --config config/sync.yaml --log-level DEBUG
        """,
    )

    parser.add_argument(
        "--config", "-c",
        type=str,
        help="Path to sync configuration YAML file",
    )

    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Don't actually index, just show what would happen",
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force full reindex, ignoring cache",
    )

    parser.add_argument(
        "--log-level", "-l",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    return parser.parse_args()


async def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        job = SyncJob(
            config_path=args.config,
            dry_run=args.dry_run,
            force_full=args.force,
        )

        stats = await job.run()

        if stats.chunks_failed > 0:
            return 1
        return 0

    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
