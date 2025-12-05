"""Configuration module for RAG MCP Server."""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """RAG MCP Server configuration settings."""

    # Vector Store Backend Selection
    vector_backend: str = Field(
        default="qdrant",
        description="Vector store backend: 'qdrant' or 'pgvector'",
    )

    # Qdrant Configuration (used when vector_backend='qdrant')
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant server URL",
    )
    qdrant_api_key: Optional[str] = Field(
        default=None,
        description="Qdrant API key (optional, for cloud deployments)",
    )
    qdrant_timeout: int = Field(
        default=30,
        description="Qdrant client timeout in seconds",
    )

    # PostgreSQL + pgvector Configuration (used when vector_backend='pgvector')
    database_url: Optional[str] = Field(
        default=None,
        description="PostgreSQL connection string for pgvector backend",
    )

    # Embedding Configuration
    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="FastEmbed model name (384 dimensions)",
    )
    embedding_batch_size: int = Field(
        default=32,
        description="Batch size for embedding generation",
    )

    # MCP Server Configuration
    mcp_mode: str = Field(
        default="stdio",
        description="MCP transport mode: 'stdio' or 'http'",
    )
    mcp_host: str = Field(
        default="0.0.0.0",
        description="MCP HTTP server host (only for http mode)",
    )
    mcp_port: int = Field(
        default=8003,
        description="MCP HTTP server port (only for http mode)",
    )

    # Collection Defaults
    default_collection: str = Field(
        default="default",
        description="Default collection name for operations",
    )
    vector_size: int = Field(
        default=384,
        description="Vector dimension size (matches embedding model)",
    )
    distance_metric: str = Field(
        default="Cosine",
        description="Distance metric for similarity search",
    )

    # Search Configuration
    default_search_limit: int = Field(
        default=5,
        description="Default number of results to return",
    )
    score_threshold: float = Field(
        default=0.0,
        description="Minimum similarity score threshold",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )

    class Config:
        env_prefix = "RAG_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment."""
    global _settings
    _settings = Settings()
    return _settings
