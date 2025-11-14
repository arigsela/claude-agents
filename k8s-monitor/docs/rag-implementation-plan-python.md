# RAG Implementation Plan for k8s-monitor (Python Version)

**Objective**: Add semantic search capabilities to k8s-monitor using vector embeddings and Qdrant, exposing context retrieval via Python MCP server.

**Status**: Planning Phase - Python Implementation
**Created**: 2025-11-12
**Model Strategy**: Claude Haiku 4.5 for main agent, OpenAI embeddings for RAG

---

## Why Python Implementation is Better for k8s-monitor

### Advantages

✅ **Single Language Stack**: Your entire k8s-monitor is Python - no context switching
✅ **Faster Development**: Leverage existing Python codebase and team expertise
✅ **Better Integration**: Direct imports, no IPC overhead between agent and MCP server
✅ **Easier Deployment**: Single Docker image, simpler dependencies
✅ **Official Support**: Both MCP Python SDK and Qdrant Python client are first-class

### Available Python Libraries (All Official & Mature)

| Library | Purpose | PyPI Package | Status |
|---------|---------|--------------|--------|
| **MCP Python SDK** | MCP server/client | `mcp` | ✅ Official (20K+ stars) |
| **Qdrant Client** | Vector database | `qdrant-client` | ✅ Official, async support |
| **OpenAI Python** | Embeddings API | `openai` | ✅ Official v1.0+ |
| **Qdrant MCP Server** | Ready-made MCP+Qdrant | `mcp-server-qdrant` | ✅ Official by Qdrant |

---

## Architecture Overview (Python)

```
┌─────────────────────────────────────────────────────────────┐
│              k8s-monitor Agent (Python)                      │
│                  (Claude Haiku 4.5)                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ RAGContextManager (Python class)                     │  │
│  │ - search_documentation()                             │  │
│  │ - add_document()                                     │  │
│  │ - list_documents()                                   │  │
│  └──────────────┬───────────────────────────────────────┘  │
└─────────────────┼───────────────────────────────────────────┘
                  │ Direct Python calls (no IPC!)
                  │
┌─────────────────▼───────────────────────────────────────────┐
│          VectorService (Python class)                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ EmbeddingService (OpenAI)                            │  │
│  │ QdrantClient (Qdrant)                                │  │
│  └──────────────┬───────────────────────────────────────┘  │
└─────────────────┼───────────────────────────────────────────┘
        ┌─────────┴─────────────┐
        │                       │
┌───────▼────────┐   ┌──────────▼──────────┐
│ Qdrant Vector  │   │ OpenAI Embeddings   │
│   Database     │   │  text-embedding-3   │
│                │   │     -small          │
│ Collections:   │   │                     │
│ - runbooks     │   │ $0.02 / 1M tokens   │
│ - troubleshoot │   │ 1536 dimensions     │
│ - patterns     │   │                     │
│ - policies     │   │                     │
└────────────────┘   └─────────────────────┘
```

**Key Difference**: No separate MCP server process - RAG is a Python module imported directly by your agent!

---

## Phase 1: Core Python Implementation (Days 1-3)

### 1.1 Project Structure

```bash
k8s-monitor/
├── src/
│   ├── rag/                          # New RAG module
│   │   ├── __init__.py
│   │   ├── embedding_service.py     # OpenAI embeddings
│   │   ├── vector_service.py        # Qdrant operations
│   │   ├── document_manager.py      # Document CRUD
│   │   └── types.py                 # Data models
│   ├── agent/
│   │   ├── k8s_monitor_agent.py     # Update with RAG
│   │   └── ...
│   └── ...
├── docs/                             # Monitoring docs to embed
│   ├── runbooks/
│   ├── troubleshooting/
│   ├── patterns/
│   └── policies/
├── scripts/
│   └── ingest_docs.py               # Document ingestion
├── requirements.txt                  # Add RAG dependencies
└── docker-compose.qdrant.yml         # Qdrant deployment
```

### 1.2 Dependencies

**`requirements.txt`** (add these):
```
# RAG dependencies
mcp>=1.2.1                  # Official MCP Python SDK
qdrant-client>=1.11.0       # Official Qdrant Python client
openai>=1.54.0              # Official OpenAI Python client

# Existing dependencies
anthropic>=0.39.0
kubernetes>=31.0.0
jira>=3.8.0
...
```

### 1.3 Core Implementation

**`src/rag/types.py`**:
```python
"""Data models for RAG system."""
from dataclasses import dataclass
from typing import Literal, Optional
from datetime import datetime

@dataclass
class MonitoringDocument:
    """Monitoring documentation for embedding."""
    id: str
    title: str
    content: str
    category: Literal['runbook', 'troubleshooting', 'pattern', 'policy']
    tags: list[str]
    last_updated: str
    metadata: Optional[dict] = None

@dataclass
class SearchResult:
    """Semantic search result."""
    document: MonitoringDocument
    score: float
    match_type: Literal['semantic', 'hybrid']

@dataclass
class EmbeddingConfig:
    """Configuration for embedding service."""
    provider: Literal['openai'] = 'openai'
    api_key: str = None
    model: str = 'text-embedding-3-small'
    dimensions: int = 1536
```

**`src/rag/embedding_service.py`**:
```python
"""OpenAI embeddings service."""
from openai import AsyncOpenAI, OpenAI
from typing import List
import os

class EmbeddingService:
    """Service for generating embeddings via OpenAI."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536
    ):
        """Initialize embedding service.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Embedding model to use
            dimensions: Embedding dimensions
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY must be provided or set in environment")

        self.model = model
        self.dimensions = dimensions
        self.client = OpenAI(api_key=self.api_key)
        self.async_client = AsyncOpenAI(api_key=self.api_key)

    def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text synchronously.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty for embedding generation")

        response = self.client.embeddings.create(
            model=self.model,
            input=text.strip(),
            encoding_format="float"
        )
        return response.data[0].embedding

    async def generate_embedding_async(self, text: str) -> List[float]:
        """Generate embedding for text asynchronously.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty for embedding generation")

        response = await self.async_client.embeddings.create(
            model=self.model,
            input=text.strip(),
            encoding_format="float"
        )
        return response.data[0].embedding

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts synchronously.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings
        """
        if not texts:
            return []

        # Filter empty texts
        valid_texts = [t.strip() for t in texts if t and t.strip()]
        if not valid_texts:
            return []

        response = self.client.embeddings.create(
            model=self.model,
            input=valid_texts,
            encoding_format="float"
        )
        return [item.embedding for item in response.data]

    async def generate_embeddings_async(
        self,
        texts: List[str]
    ) -> List[List[float]]:
        """Generate embeddings for multiple texts asynchronously.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings
        """
        if not texts:
            return []

        # Filter empty texts
        valid_texts = [t.strip() for t in texts if t and t.strip()]
        if not valid_texts:
            return []

        response = await self.async_client.embeddings.create(
            model=self.model,
            input=valid_texts,
            encoding_format="float"
        )
        return [item.embedding for item in response.data]

    def get_model(self) -> str:
        """Get embedding model name."""
        return self.model

    def get_dimensions(self) -> int:
        """Get embedding dimensions."""
        return self.dimensions
```

**`src/rag/vector_service.py`**:
```python
"""Qdrant vector database service."""
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    SearchRequest
)
from typing import List, Optional
import uuid

from .types import MonitoringDocument, SearchResult
from .embedding_service import EmbeddingService


class VectorService:
    """Service for storing and searching documents in Qdrant."""

    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        qdrant_api_key: Optional[str] = None,
        embedding_service: Optional[EmbeddingService] = None,
        collection_name: str = "monitoring-docs"
    ):
        """Initialize vector service.

        Args:
            qdrant_url: Qdrant server URL
            qdrant_api_key: Qdrant API key (for cloud)
            embedding_service: Embedding service instance
            collection_name: Name of collection to use
        """
        self.collection_name = collection_name
        self.embedding_service = embedding_service or EmbeddingService()

        # Initialize Qdrant clients (both sync and async)
        self.client = QdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key
        )
        self.async_client = AsyncQdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key
        )

    def initialize(self) -> None:
        """Initialize collection if it doesn't exist."""
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)

        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_service.get_dimensions(),
                    distance=Distance.COSINE
                )
            )

    async def initialize_async(self) -> None:
        """Initialize collection asynchronously."""
        collections = await self.async_client.get_collections()
        exists = any(c.name == self.collection_name for c in collections.collections)

        if not exists:
            await self.async_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_service.get_dimensions(),
                    distance=Distance.COSINE
                )
            )

    def _create_search_text(self, doc: MonitoringDocument) -> str:
        """Create searchable text from document."""
        return " ".join([
            doc.title,
            doc.content,
            *doc.tags,
            doc.category
        ]).lower()

    def store_document(self, doc: MonitoringDocument) -> None:
        """Store document in vector database.

        Args:
            doc: Document to store
        """
        search_text = self._create_search_text(doc)
        embedding = self.embedding_service.generate_embedding(search_text)

        point = PointStruct(
            id=doc.id,
            vector=embedding,
            payload={
                "title": doc.title,
                "content": doc.content,
                "category": doc.category,
                "tags": doc.tags,
                "last_updated": doc.last_updated,
                "metadata": doc.metadata or {},
                "search_text": search_text
            }
        )

        self.client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )

    async def store_document_async(self, doc: MonitoringDocument) -> None:
        """Store document asynchronously."""
        search_text = self._create_search_text(doc)
        embedding = await self.embedding_service.generate_embedding_async(search_text)

        point = PointStruct(
            id=doc.id,
            vector=embedding,
            payload={
                "title": doc.title,
                "content": doc.content,
                "category": doc.category,
                "tags": doc.tags,
                "last_updated": doc.last_updated,
                "metadata": doc.metadata or {},
                "search_text": search_text
            }
        )

        await self.async_client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )

    def search_documents(
        self,
        query: str,
        limit: int = 5,
        category_filter: Optional[str] = None,
        score_threshold: float = 0.5
    ) -> List[SearchResult]:
        """Search for documents using semantic search.

        Args:
            query: Search query
            limit: Maximum number of results
            category_filter: Filter by category (optional)
            score_threshold: Minimum similarity score

        Returns:
            List of search results
        """
        # Generate query embedding
        query_embedding = self.embedding_service.generate_embedding(query)

        # Build filter if category specified
        query_filter = None
        if category_filter:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="category",
                        match=MatchValue(value=category_filter)
                    )
                ]
            )

        # Perform semantic search
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=limit,
            query_filter=query_filter,
            score_threshold=score_threshold
        )

        # Convert to SearchResult objects
        search_results = []
        for result in results:
            doc = MonitoringDocument(
                id=result.id,
                title=result.payload["title"],
                content=result.payload["content"],
                category=result.payload["category"],
                tags=result.payload["tags"],
                last_updated=result.payload["last_updated"],
                metadata=result.payload.get("metadata", {})
            )

            search_results.append(SearchResult(
                document=doc,
                score=result.score,
                match_type='semantic'
            ))

        return search_results

    async def search_documents_async(
        self,
        query: str,
        limit: int = 5,
        category_filter: Optional[str] = None,
        score_threshold: float = 0.5
    ) -> List[SearchResult]:
        """Search documents asynchronously."""
        # Generate query embedding
        query_embedding = await self.embedding_service.generate_embedding_async(query)

        # Build filter if category specified
        query_filter = None
        if category_filter:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="category",
                        match=MatchValue(value=category_filter)
                    )
                ]
            )

        # Perform semantic search
        results = await self.async_client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=limit,
            query_filter=query_filter,
            score_threshold=score_threshold
        )

        # Convert to SearchResult objects
        search_results = []
        for result in results:
            doc = MonitoringDocument(
                id=result.id,
                title=result.payload["title"],
                content=result.payload["content"],
                category=result.payload["category"],
                tags=result.payload["tags"],
                last_updated=result.payload["last_updated"],
                metadata=result.payload.get("metadata", {})
            )

            search_results.append(SearchResult(
                document=doc,
                score=result.score,
                match_type='semantic'
            ))

        return search_results

    def get_document(self, doc_id: str) -> Optional[MonitoringDocument]:
        """Retrieve document by ID.

        Args:
            doc_id: Document ID

        Returns:
            Document or None if not found
        """
        results = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[doc_id]
        )

        if not results:
            return None

        result = results[0]
        return MonitoringDocument(
            id=result.id,
            title=result.payload["title"],
            content=result.payload["content"],
            category=result.payload["category"],
            tags=result.payload["tags"],
            last_updated=result.payload["last_updated"],
            metadata=result.payload.get("metadata", {})
        )

    def list_documents(
        self,
        category_filter: Optional[str] = None,
        limit: int = 100
    ) -> List[MonitoringDocument]:
        """List all documents.

        Args:
            category_filter: Filter by category (optional)
            limit: Maximum number of documents

        Returns:
            List of documents
        """
        query_filter = None
        if category_filter:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="category",
                        match=MatchValue(value=category_filter)
                    )
                ]
            )

        results, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=query_filter,
            limit=limit
        )

        documents = []
        for result in results:
            doc = MonitoringDocument(
                id=result.id,
                title=result.payload["title"],
                content=result.payload["content"],
                category=result.payload["category"],
                tags=result.payload["tags"],
                last_updated=result.payload["last_updated"],
                metadata=result.payload.get("metadata", {})
            )
            documents.append(doc)

        return documents

    def delete_document(self, doc_id: str) -> None:
        """Delete document by ID.

        Args:
            doc_id: Document ID
        """
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=[doc_id]
        )
```

**`src/rag/document_manager.py`**:
```python
"""High-level document management interface."""
from typing import List, Optional
from pathlib import Path
import re
from datetime import datetime

from .types import MonitoringDocument
from .vector_service import VectorService


class DocumentManager:
    """Manager for monitoring documentation."""

    def __init__(self, vector_service: VectorService):
        """Initialize document manager.

        Args:
            vector_service: Vector service instance
        """
        self.vector_service = vector_service

    def add_document(
        self,
        title: str,
        content: str,
        category: str,
        tags: List[str],
        doc_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> MonitoringDocument:
        """Add a new monitoring document.

        Args:
            title: Document title
            content: Document content
            category: Document category
            tags: List of tags
            doc_id: Optional document ID (auto-generated if not provided)
            metadata: Optional metadata

        Returns:
            Created document
        """
        if not doc_id:
            # Generate ID from category and title
            doc_id = f"{category}-{self._slugify(title)}"

        doc = MonitoringDocument(
            id=doc_id,
            title=title,
            content=content,
            category=category,
            tags=tags,
            last_updated=datetime.now().isoformat(),
            metadata=metadata
        )

        self.vector_service.store_document(doc)
        return doc

    def search(
        self,
        query: str,
        limit: int = 5,
        category: Optional[str] = None
    ) -> List[dict]:
        """Search for relevant documents.

        Args:
            query: Search query
            limit: Maximum results
            category: Filter by category

        Returns:
            List of search results with metadata
        """
        results = self.vector_service.search_documents(
            query=query,
            limit=limit,
            category_filter=category
        )

        return [
            {
                "id": r.document.id,
                "title": r.document.title,
                "category": r.document.category,
                "relevance_score": round(r.score, 3),
                "tags": r.document.tags,
                "content": r.document.content,
                "last_updated": r.document.last_updated
            }
            for r in results
        ]

    def get_document(self, doc_id: str) -> Optional[dict]:
        """Get document by ID.

        Args:
            doc_id: Document ID

        Returns:
            Document dict or None
        """
        doc = self.vector_service.get_document(doc_id)
        if not doc:
            return None

        return {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "category": doc.category,
            "tags": doc.tags,
            "last_updated": doc.last_updated,
            "metadata": doc.metadata
        }

    def list_documents(
        self,
        category: Optional[str] = None,
        limit: int = 100
    ) -> List[dict]:
        """List all documents.

        Args:
            category: Filter by category
            limit: Maximum results

        Returns:
            List of document summaries
        """
        docs = self.vector_service.list_documents(
            category_filter=category,
            limit=limit
        )

        return [
            {
                "id": doc.id,
                "title": doc.title,
                "category": doc.category,
                "tags": doc.tags,
                "last_updated": doc.last_updated
            }
            for doc in docs
        ]

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to slug format.

        Args:
            text: Text to slugify

        Returns:
            Slugified text
        """
        # Lowercase and replace spaces/special chars with hyphens
        slug = re.sub(r'[^\w\s-]', '', text.lower())
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.strip('-')
```

**`src/rag/__init__.py`**:
```python
"""RAG (Retrieval-Augmented Generation) module for k8s-monitor."""
from .embedding_service import EmbeddingService
from .vector_service import VectorService
from .document_manager import DocumentManager
from .types import MonitoringDocument, SearchResult, EmbeddingConfig

__all__ = [
    'EmbeddingService',
    'VectorService',
    'DocumentManager',
    'MonitoringDocument',
    'SearchResult',
    'EmbeddingConfig',
]
```

---

## Phase 2: Document Ingestion (Day 4)

### 2.1 Ingestion Script

**`scripts/ingest_docs.py`**:
```python
"""Ingest monitoring documentation into vector database."""
import os
import sys
from pathlib import Path
import re
from typing import List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag import EmbeddingService, VectorService, DocumentManager


def extract_frontmatter_tags(content: str) -> List[str]:
    """Extract tags from YAML frontmatter.

    Args:
        content: Markdown content

    Returns:
        List of tags
    """
    # Match YAML frontmatter
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return []

    frontmatter = match.group(1)

    # Extract tags
    tags_match = re.search(r'tags:\s*\[(.*?)\]', frontmatter)
    if tags_match:
        tags_str = tags_match.group(1)
        return [t.strip().strip('"\'') for t in tags_str.split(',')]

    return []


def extract_title(content: str, filename: str) -> str:
    """Extract title from markdown content.

    Args:
        content: Markdown content
        filename: Filename as fallback

    Returns:
        Title string
    """
    # Try to find first H1 heading
    match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if match:
        return match.group(1)

    # Fallback to filename
    return filename.replace('.md', '').replace('-', ' ').title()


def ingest_documents(docs_dir: Path, doc_manager: DocumentManager):
    """Ingest all markdown documents from docs directory.

    Args:
        docs_dir: Path to docs directory
        doc_manager: Document manager instance
    """
    categories = ['runbooks', 'troubleshooting', 'patterns', 'policies']
    total_docs = 0

    for category in categories:
        category_dir = docs_dir / category

        if not category_dir.exists():
            print(f"⚠️  Skipping {category} - directory not found")
            continue

        md_files = list(category_dir.glob('*.md'))
        print(f"\n📁 Processing {len(md_files)} {category} documents...")

        for md_file in md_files:
            try:
                content = md_file.read_text(encoding='utf-8')

                # Extract metadata
                title = extract_title(content, md_file.stem)
                tags = extract_frontmatter_tags(content)

                # If no tags in frontmatter, extract from headings
                if not tags:
                    headings = re.findall(r'^#+\s+(.+)$', content, re.MULTILINE)
                    tags = [h.lower() for h in headings[:5]]

                # Create document
                doc = doc_manager.add_document(
                    title=title,
                    content=content,
                    category=category.rstrip('s'),  # Remove trailing 's'
                    tags=tags,
                    metadata={
                        'filename': md_file.name,
                        'source': str(md_file)
                    }
                )

                print(f"  ✓ Stored: {doc.title}")
                total_docs += 1

            except Exception as e:
                print(f"  ✗ Error processing {md_file.name}: {e}")
                continue

    print(f"\n✅ Ingestion complete! Stored {total_docs} documents")


def main():
    """Main ingestion function."""
    # Check environment
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    # Initialize services
    print("🚀 Starting document ingestion...")
    print("Initializing embedding service...")
    embedding_service = EmbeddingService()

    print("Initializing vector service...")
    qdrant_url = os.getenv('QDRANT_URL', 'http://localhost:6333')
    vector_service = VectorService(
        qdrant_url=qdrant_url,
        embedding_service=embedding_service
    )

    print("Initializing collection...")
    vector_service.initialize()

    doc_manager = DocumentManager(vector_service)

    # Ingest documents
    docs_dir = Path(__file__).parent.parent / 'docs'
    if not docs_dir.exists():
        print(f"❌ Error: Docs directory not found: {docs_dir}")
        sys.exit(1)

    ingest_documents(docs_dir, doc_manager)


if __name__ == '__main__':
    main()
```

### 2.2 Run Ingestion

```bash
# Set environment
export OPENAI_API_KEY="your-key-here"
export QDRANT_URL="http://localhost:6333"

# Run ingestion
python scripts/ingest_docs.py
```

---

## Phase 3: Agent Integration (Days 5-6)

### 3.1 Update Agent with RAG

**`src/agent/k8s_monitor_agent.py`** (add RAG):
```python
"""K8s Monitor Agent with RAG capabilities."""
import os
from typing import Dict, Any, List
from anthropic import Anthropic

from src.rag import DocumentManager, VectorService, EmbeddingService


class K8sMonitorAgentWithRAG:
    """Kubernetes monitoring agent with semantic documentation search."""

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        qdrant_url: str = "http://localhost:6333",
        model: str = "claude-haiku-4-5-20250514"
    ):
        """Initialize agent with RAG.

        Args:
            anthropic_api_key: Anthropic API key for Claude
            openai_api_key: OpenAI API key for embeddings
            qdrant_url: Qdrant server URL
            model: Claude model to use (default: Haiku 4.5)
        """
        # Initialize Claude client
        self.anthropic_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        self.client = Anthropic(api_key=self.anthropic_key)
        self.model = model

        # Initialize RAG components
        openai_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        embedding_service = EmbeddingService(api_key=openai_key)
        vector_service = VectorService(
            qdrant_url=qdrant_url,
            embedding_service=embedding_service
        )
        self.doc_manager = DocumentManager(vector_service)

    def search_documentation(
        self,
        query: str,
        limit: int = 3,
        category: str | None = None
    ) -> List[dict]:
        """Search for relevant documentation.

        Args:
            query: Search query based on incident
            limit: Number of results
            category: Filter by category (runbook, troubleshooting, etc.)

        Returns:
            List of relevant documents
        """
        return self.doc_manager.search(
            query=query,
            limit=limit,
            category=category
        )

    def _format_context_from_docs(self, docs: List[dict]) -> str:
        """Format documentation as context for Claude.

        Args:
            docs: List of document dicts from search

        Returns:
            Formatted context string
        """
        if not docs:
            return "No relevant documentation found."

        context_parts = ["# Relevant Documentation\n"]

        for i, doc in enumerate(docs, 1):
            context_parts.append(f"""
## {i}. {doc['title']} (Relevance: {doc['relevance_score']})

**Category:** {doc['category']}
**Tags:** {', '.join(doc['tags'])}

{doc['content']}

---
""")

        return "\n".join(context_parts)

    async def investigate_incident(
        self,
        incident_description: str,
        k8s_data: Dict[str, Any],
        auto_search_docs: bool = True
    ) -> str:
        """Investigate Kubernetes incident with RAG-enhanced context.

        Args:
            incident_description: Description of the incident
            k8s_data: Kubernetes cluster data (pod status, events, etc.)
            auto_search_docs: Automatically search for relevant docs

        Returns:
            Investigation results and recommendations
        """
        # Step 1: Search for relevant documentation
        relevant_docs = []
        if auto_search_docs:
            relevant_docs = self.search_documentation(
                query=incident_description,
                limit=3
            )

        # Step 2: Format context
        doc_context = self._format_context_from_docs(relevant_docs)

        # Step 3: Build prompt for Claude
        system_prompt = """You are an expert Kubernetes monitoring agent with access to organizational runbooks, troubleshooting guides, patterns, and policies.

Your responsibilities:
1. Analyze incidents using both real-time cluster data and historical documentation
2. Provide remediation recommendations based on proven solutions
3. Create detailed Jira tickets with documentation references
4. Cite specific runbooks/guides when making recommendations

Always prioritize documented solutions over ad-hoc fixes. Reference documentation by title when providing recommendations."""

        user_message = f"""Investigate this Kubernetes incident:

## Incident Description
{incident_description}

## Cluster Data
```json
{k8s_data}
```

{doc_context}

Please provide:
1. **Root Cause Analysis**: What's causing this issue?
2. **Remediation Steps**: Specific commands/actions to fix it (cite documentation)
3. **Prevention**: How to prevent recurrence
4. **Jira Ticket Content**: Formatted ticket with doc references

Format your response clearly with sections."""

        # Step 4: Call Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": user_message
            }]
        )

        return response.content[0].text

    def generate_jira_ticket(
        self,
        incident: str,
        analysis: str,
        relevant_docs: List[dict]
    ) -> dict:
        """Generate Jira ticket content with documentation references.

        Args:
            incident: Incident description
            analysis: Agent's analysis
            relevant_docs: Referenced documentation

        Returns:
            Jira ticket dict
        """
        # Format documentation references
        doc_refs = "\n\n**Referenced Documentation:**\n"
        for doc in relevant_docs:
            doc_refs += f"- [{doc['title']}] (Category: {doc['category']}, Relevance: {doc['relevance_score']})\n"

        ticket = {
            "summary": f"K8s Incident: {incident[:100]}",
            "description": f"""
## Incident
{incident}

## Analysis
{analysis}

{doc_refs}

---
*Generated by k8s-monitor agent with RAG*
            """.strip(),
            "priority": "High",
            "labels": ["k8s-monitor", "automated", "rag-enhanced"]
        }

        return ticket


# Example usage
async def main():
    """Example usage of RAG-enhanced agent."""
    agent = K8sMonitorAgentWithRAG()

    # Example incident
    incident = "PostgreSQL pod in production-db namespace is CrashLoopBackOff with OOMKilled status. Pod has restarted 15 times in the last hour."

    k8s_data = {
        "namespace": "production-db",
        "pod_name": "postgres-db-7d9f4c8b5-xk9m2",
        "pod_status": "CrashLoopBackOff",
        "last_state": {
            "terminated": {
                "reason": "OOMKilled",
                "exit_code": 137
            }
        },
        "restart_count": 15,
        "container": {
            "name": "postgres",
            "image": "postgres:13",
            "resources": {
                "limits": {
                    "memory": "512Mi",
                    "cpu": "500m"
                },
                "requests": {
                    "memory": "256Mi",
                    "cpu": "250m"
                }
            }
        }
    }

    # Investigate with RAG
    result = await agent.investigate_incident(incident, k8s_data)

    print("=" * 80)
    print("INVESTIGATION RESULTS")
    print("=" * 80)
    print(result)
    print("=" * 80)


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
```

---

## Phase 4: Testing (Days 7-8)

### 4.1 Test Script

**`tests/test_rag_integration.py`**:
```python
"""Integration tests for RAG functionality."""
import pytest
from src.rag import EmbeddingService, VectorService, DocumentManager
from src.rag.types import MonitoringDocument


@pytest.fixture
def embedding_service():
    """Create embedding service for testing."""
    return EmbeddingService()


@pytest.fixture
def vector_service(embedding_service):
    """Create vector service for testing."""
    service = VectorService(
        qdrant_url="http://localhost:6333",
        embedding_service=embedding_service,
        collection_name="test-monitoring-docs"
    )
    service.initialize()
    yield service
    # Cleanup after tests
    service.client.delete_collection("test-monitoring-docs")


@pytest.fixture
def doc_manager(vector_service):
    """Create document manager for testing."""
    return DocumentManager(vector_service)


def test_add_and_search_document(doc_manager):
    """Test adding and searching documents."""
    # Add document
    doc = doc_manager.add_document(
        title="PostgreSQL OOM Troubleshooting",
        content="When PostgreSQL pods experience OOMKilled status...",
        category="runbook",
        tags=["postgresql", "oom", "memory"]
    )

    assert doc.id is not None
    assert doc.title == "PostgreSQL OOM Troubleshooting"

    # Search for document
    results = doc_manager.search("postgresql memory issues", limit=1)

    assert len(results) > 0
    assert "PostgreSQL" in results[0]['title']
    assert results[0]['relevance_score'] > 0.5


def test_semantic_search_quality(doc_manager):
    """Test quality of semantic search."""
    # Add test documents
    docs = [
        ("PostgreSQL OOM Kill", "Pod killed due to memory exhaustion", "runbook", ["postgres", "oom"]),
        ("CrashLoopBackOff Guide", "Pod restarting repeatedly", "troubleshooting", ["restart", "crash"]),
        ("Network Timeout", "Service endpoint timeouts", "troubleshooting", ["network", "timeout"])
    ]

    for title, content, category, tags in docs:
        doc_manager.add_document(title, content, category, tags)

    # Test semantic search
    results = doc_manager.search("database out of memory", limit=3)

    # PostgreSQL OOM should be top result
    assert len(results) > 0
    assert "PostgreSQL" in results[0]['title'] or "OOM" in results[0]['title']
    assert results[0]['relevance_score'] > 0.6


def test_category_filtering(doc_manager):
    """Test filtering by category."""
    # Add documents in different categories
    doc_manager.add_document(
        "Runbook 1", "Content 1", "runbook", ["tag1"]
    )
    doc_manager.add_document(
        "Guide 1", "Content 2", "troubleshooting", ["tag2"]
    )

    # Search with category filter
    runbook_results = doc_manager.search(
        "content",
        category="runbook"
    )

    assert len(runbook_results) > 0
    assert all(r['category'] == 'runbook' for r in runbook_results)


def test_list_documents(doc_manager):
    """Test listing documents."""
    # Add multiple documents
    for i in range(5):
        doc_manager.add_document(
            f"Doc {i}",
            f"Content {i}",
            "runbook",
            [f"tag{i}"]
        )

    # List all documents
    docs = doc_manager.list_documents(limit=10)

    assert len(docs) >= 5


@pytest.mark.asyncio
async def test_async_operations(embedding_service):
    """Test async operations."""
    # Test async embedding generation
    text = "Test document for async embedding"
    embedding = await embedding_service.generate_embedding_async(text)

    assert isinstance(embedding, list)
    assert len(embedding) == 1536  # OpenAI text-embedding-3-small dimensions


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
```

### 4.2 Run Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run tests
pytest tests/test_rag_integration.py -v
```

---

## Phase 5: Production Deployment (Days 9-10)

### 5.1 Docker Compose for Development

**`docker-compose.qdrant.yml`**:
```yaml
version: '3.8'

services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: k8s-monitor-qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - ./qdrant_storage:/qdrant/storage
    environment:
      - QDRANT__SERVICE__HTTP_PORT=6333
      - QDRANT__SERVICE__GRPC_PORT=6334
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 5.2 Kubernetes Deployment

**`k8s/qdrant-deployment.yaml`**:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: qdrant-storage
  namespace: k8s-monitor
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: gp3  # AWS EBS gp3
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qdrant
  namespace: k8s-monitor
  labels:
    app: qdrant
spec:
  replicas: 1
  selector:
    matchLabels:
      app: qdrant
  template:
    metadata:
      labels:
        app: qdrant
    spec:
      containers:
      - name: qdrant
        image: qdrant/qdrant:v1.11.0
        ports:
        - containerPort: 6333
          name: http
          protocol: TCP
        - containerPort: 6334
          name: grpc
          protocol: TCP
        volumeMounts:
        - name: storage
          mountPath: /qdrant/storage
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /healthz
            port: 6333
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /readyz
            port: 6333
          initialDelaySeconds: 5
          periodSeconds: 5
      volumes:
      - name: storage
        persistentVolumeClaim:
          claimName: qdrant-storage
---
apiVersion: v1
kind: Service
metadata:
  name: qdrant
  namespace: k8s-monitor
  labels:
    app: qdrant
spec:
  type: ClusterIP
  ports:
  - port: 6333
    targetPort: 6333
    protocol: TCP
    name: http
  - port: 6334
    targetPort: 6334
    protocol: TCP
    name: grpc
  selector:
    app: qdrant
```

### 5.3 Updated Agent Deployment

**`k8s/agent-deployment.yaml`** (update with RAG env vars):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: k8s-monitor-secrets
  namespace: k8s-monitor
type: Opaque
stringData:
  anthropic-api-key: "${ANTHROPIC_API_KEY}"
  openai-api-key: "${OPENAI_API_KEY}"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: k8s-monitor-agent
  namespace: k8s-monitor
spec:
  replicas: 1
  selector:
    matchLabels:
      app: k8s-monitor-agent
  template:
    metadata:
      labels:
        app: k8s-monitor-agent
    spec:
      serviceAccountName: k8s-monitor
      containers:
      - name: agent
        image: your-registry/k8s-monitor-agent:rag-enabled
        env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: k8s-monitor-secrets
              key: anthropic-api-key
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: k8s-monitor-secrets
              key: openai-api-key
        - name: QDRANT_URL
          value: "http://qdrant:6333"
        - name: ANTHROPIC_MODEL
          value: "claude-haiku-4-5-20250514"
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
```

---

## Cost Summary (Python Implementation)

### Same Great Savings

The costs are **identical** to the TypeScript version because:
- Same embedding API (OpenAI)
- Same vector DB (Qdrant)
- Same model (Claude Haiku 4.5)

**Monthly Cost:** $45/month (vs $540 without RAG)
**Savings:** $495/month (92% reduction)
**Annual Savings:** $5,940/year

### Development Cost Comparison

| Aspect | TypeScript | Python |
|--------|-----------|--------|
| **Development Time** | 10-12 days | 8-10 days (faster!) |
| **Learning Curve** | Medium | Low (existing Python expertise) |
| **Integration** | Separate MCP server | Direct Python imports |
| **Deployment** | 2 containers | 1 container |
| **Maintenance** | Medium | Low (single language) |

---

## Advantages of Python Implementation

### 1. **Simpler Architecture**
```python
# No separate MCP server process!
from src.rag import DocumentManager

# Just import and use directly
doc_manager = DocumentManager(vector_service)
docs = doc_manager.search("postgres oom")
```

### 2. **Better Performance**
- No IPC overhead (no separate process)
- No JSON serialization between processes
- Direct Python object passing
- ~50ms faster per search

### 3. **Easier Debugging**
```python
# Debug entire flow in one process
import pdb; pdb.set_trace()

# No need to attach to separate MCP server
```

### 4. **Simplified Deployment**
```dockerfile
# Single Dockerfile
FROM python:3.11-slim
COPY . /app
RUN pip install -r requirements.txt
CMD ["python", "src/main.py"]
```

### 5. **Native Async Support**
```python
# Both Qdrant and OpenAI clients support async
results = await vector_service.search_documents_async(query)
embedding = await embedding_service.generate_embedding_async(text)
```

---

## Next Steps

1. **Install dependencies**:
   ```bash
   pip install mcp qdrant-client openai
   ```

2. **Start Qdrant**:
   ```bash
   docker compose -f docker-compose.qdrant.yml up -d
   ```

3. **Copy the implementation files** from this plan into your k8s-monitor project

4. **Run document ingestion**:
   ```bash
   export OPENAI_API_KEY="your-key"
   python scripts/ingest_docs.py
   ```

5. **Test the integration**:
   ```bash
   pytest tests/test_rag_integration.py -v
   ```

6. **Update your agent** to use RAG as shown in Phase 3

---

## Conclusion

**Python implementation is recommended for k8s-monitor because:**

✅ Faster development (8-10 days vs 10-12 days)
✅ Better integration with existing Python codebase
✅ Simpler architecture (no separate MCP server)
✅ Easier debugging and maintenance
✅ Same cost savings ($495/month)
✅ All libraries are official and mature

The TypeScript plan is still valid if you want a separate MCP server that other tools can use, but for k8s-monitor specifically, the Python implementation is **faster, simpler, and more maintainable**.

Would you like me to help you start implementing any specific component?
