"""Content Hasher - Detect changes for incremental sync.

Provides content hashing for deduplication and change detection.
Tracks document hashes to enable efficient incremental indexing.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.sync.chunker import Chunk

logger = logging.getLogger(__name__)


@dataclass
class HashRecord:
    """Record of a hashed document/chunk."""

    content_hash: str
    source: str
    chunk_index: int = 0
    indexed_at: Optional[str] = None


class ContentHasher:
    """Hash content for change detection and deduplication.

    Supports:
    - Content hashing (MD5/SHA256)
    - Hash persistence to file
    - Change detection between syncs
    - Incremental sync support

    Example:
        hasher = ContentHasher(cache_file="hashes.json")

        # Check for changes
        if hasher.has_changed(chunk):
            # Index the chunk
            store_result = await rag_store(chunk.content, ...)

            # Update hash cache
            hasher.update(chunk)

        # Save cache
        hasher.save()
    """

    def __init__(
        self,
        algorithm: str = "md5",
        cache_file: Optional[str] = None,
        normalize_whitespace: bool = True,
    ):
        """Initialize hasher.

        Args:
            algorithm: Hash algorithm ("md5" or "sha256")
            cache_file: Path to persist hash cache (optional)
            normalize_whitespace: Normalize whitespace before hashing
        """
        self.algorithm = algorithm
        self.cache_file = Path(cache_file) if cache_file else None
        self.normalize_whitespace = normalize_whitespace

        # Hash cache: source+chunk_index -> content_hash
        self._cache: Dict[str, str] = {}

        # Load existing cache
        if self.cache_file and self.cache_file.exists():
            self._load_cache()

    def hash_content(self, content: str) -> str:
        """Generate hash for content.

        Args:
            content: Text content to hash

        Returns:
            Hash string (hex digest)
        """
        if self.normalize_whitespace:
            # Normalize: strip, collapse whitespace, lowercase for comparison
            content = " ".join(content.split())

        if self.algorithm == "sha256":
            return hashlib.sha256(content.encode("utf-8")).hexdigest()
        else:
            return hashlib.md5(content.encode("utf-8")).hexdigest()

    def hash_chunk(self, chunk: Chunk) -> str:
        """Generate hash for a chunk.

        Args:
            chunk: Chunk object

        Returns:
            Hash string
        """
        return self.hash_content(chunk.content)

    def get_cache_key(self, source: str, chunk_index: int = 0) -> str:
        """Generate cache key for source+chunk.

        Args:
            source: Document source path
            chunk_index: Chunk index in document

        Returns:
            Cache key string
        """
        return f"{source}:{chunk_index}"

    def has_changed(self, chunk: Chunk) -> bool:
        """Check if chunk content has changed since last sync.

        Args:
            chunk: Chunk to check

        Returns:
            True if content is new or changed
        """
        cache_key = self.get_cache_key(chunk.source, chunk.chunk_index)
        current_hash = self.hash_chunk(chunk)

        cached_hash = self._cache.get(cache_key)

        if cached_hash is None:
            logger.debug(f"New content: {chunk.source}:{chunk.chunk_index}")
            return True

        if cached_hash != current_hash:
            logger.debug(f"Changed content: {chunk.source}:{chunk.chunk_index}")
            return True

        logger.debug(f"Unchanged: {chunk.source}:{chunk.chunk_index}")
        return False

    def update(self, chunk: Chunk) -> str:
        """Update hash cache for a chunk.

        Args:
            chunk: Chunk that was indexed

        Returns:
            Content hash
        """
        cache_key = self.get_cache_key(chunk.source, chunk.chunk_index)
        content_hash = self.hash_chunk(chunk)
        self._cache[cache_key] = content_hash
        return content_hash

    def get_changed_chunks(self, chunks: List[Chunk]) -> List[Chunk]:
        """Filter chunks to only those that changed.

        Args:
            chunks: List of chunks to check

        Returns:
            List of chunks that are new or changed
        """
        changed = [c for c in chunks if self.has_changed(c)]
        logger.info(f"Found {len(changed)}/{len(chunks)} changed chunks")
        return changed

    def get_removed_sources(self, current_sources: Set[str]) -> List[str]:
        """Find sources that were removed (exist in cache but not current).

        Args:
            current_sources: Set of current source paths

        Returns:
            List of removed source paths
        """
        cached_sources = set()
        for cache_key in self._cache.keys():
            source = cache_key.rsplit(":", 1)[0]
            cached_sources.add(source)

        removed = list(cached_sources - current_sources)
        if removed:
            logger.info(f"Found {len(removed)} removed sources")
        return removed

    def remove_source(self, source: str) -> int:
        """Remove all cache entries for a source.

        Args:
            source: Source path to remove

        Returns:
            Number of entries removed
        """
        keys_to_remove = [
            k for k in self._cache.keys()
            if k.startswith(f"{source}:")
        ]

        for key in keys_to_remove:
            del self._cache[key]

        return len(keys_to_remove)

    def save(self) -> None:
        """Save hash cache to file."""
        if not self.cache_file:
            return

        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w") as f:
                json.dump(self._cache, f, indent=2)
            logger.info(f"Saved {len(self._cache)} hashes to {self.cache_file}")
        except Exception as e:
            logger.error(f"Failed to save hash cache: {e}")

    def _load_cache(self) -> None:
        """Load hash cache from file."""
        try:
            with open(self.cache_file, "r") as f:
                self._cache = json.load(f)
            logger.info(f"Loaded {len(self._cache)} hashes from {self.cache_file}")
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid cache file, starting fresh: {e}")
            self._cache = {}
        except Exception as e:
            logger.error(f"Failed to load hash cache: {e}")
            self._cache = {}

    def clear(self) -> None:
        """Clear the hash cache."""
        self._cache.clear()
        logger.info("Cleared hash cache")

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        sources = set()
        for cache_key in self._cache.keys():
            source = cache_key.rsplit(":", 1)[0]
            sources.add(source)

        return {
            "total_entries": len(self._cache),
            "unique_sources": len(sources),
            "algorithm": self.algorithm,
            "cache_file": str(self.cache_file) if self.cache_file else None,
        }
