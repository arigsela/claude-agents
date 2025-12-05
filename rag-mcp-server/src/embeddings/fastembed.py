"""FastEmbed-based embedding service for RAG MCP Server.

Uses ONNX runtime for fast, CPU-based embedding generation.
No GPU required - suitable for serverless and containerized deployments.
"""

import logging
from typing import List, Optional
from functools import lru_cache

from fastembed import TextEmbedding

from src.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating text embeddings using FastEmbed.

    Features:
    - Lazy model loading (loads on first use)
    - Batch processing support
    - Thread-safe singleton pattern
    - ONNX-based (CPU-optimized, no GPU required)
    """

    _instance: Optional["EmbeddingService"] = None
    _model: Optional[TextEmbedding] = None

    def __new__(cls) -> "EmbeddingService":
        """Singleton pattern - only one instance per process."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize embedding service (lazy model loading)."""
        self.settings = get_settings()
        self.model_name = self.settings.embedding_model
        self.batch_size = self.settings.embedding_batch_size

    def _ensure_model_loaded(self) -> TextEmbedding:
        """Lazy load the embedding model on first use."""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = TextEmbedding(model_name=self.model_name)
            logger.info(f"Embedding model loaded successfully")
        return self._model

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding vector
        """
        model = self._ensure_model_loaded()
        embeddings = list(model.embed([text]))
        return embeddings[0].tolist()

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        model = self._ensure_model_loaded()
        logger.debug(f"Generating embeddings for {len(texts)} texts")

        # Process in batches
        all_embeddings = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            batch_embeddings = list(model.embed(batch))
            all_embeddings.extend([e.tolist() for e in batch_embeddings])

        return all_embeddings

    def get_dimension(self) -> int:
        """Get the embedding dimension for the current model.

        Returns:
            Integer dimension size (384 for bge-small-en-v1.5)
        """
        return self.settings.vector_size

    def get_model_name(self) -> str:
        """Get the current model name.

        Returns:
            Model name string
        """
        return self.model_name


# Module-level convenience function
@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """Get the singleton embedding service instance.

    Returns:
        EmbeddingService instance
    """
    return EmbeddingService()
