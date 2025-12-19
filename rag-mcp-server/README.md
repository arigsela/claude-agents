# RAG MCP Server

Custom MCP server providing semantic search with dual vector database backend support.

---

## Skills Demonstrated

| Skill | Implementation |
|-------|----------------|
| **MCP Protocol** | Server implementation supporting stdio and SSE transports |
| **Vector Database Architecture** | Factory pattern abstracting Qdrant vs PostgreSQL+pgvector |
| **Semantic Search** | Embedding-based document retrieval with configurable thresholds |
| **FastEmbed Integration** | Local embedding generation (BAAI/bge-small-en-v1.5) |
| **Content Deduplication** | Hash-based duplicate detection preventing redundant storage |
| **Backend Abstraction** | Clean interface allowing backend swaps without code changes |
| **Kubernetes Deployment** | ConfigMaps, Secrets, RBAC for production deployment |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude Code / MCP Client                  │
└─────────────────────────────────────────────────────────────┘
                              │ MCP Protocol
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       RAG MCP Server                         │
│  ┌───────────┐  ┌────────────┐  ┌────────────────────────┐  │
│  │ MCP Tools │  │ Embeddings │  │   Vector Store Layer   │  │
│  │ - search  │  │ (FastEmbed)│  │ ┌────────┐ ┌────────┐  │  │
│  │ - store   │  └────────────┘  │ │ Qdrant │ │pgvector│  │  │
│  │ - batch   │                  │ └────────┘ └────────┘  │  │
│  │ - list    │                  └────────────────────────┘  │
│  └───────────┘                                               │
└─────────────────────────────────────────────────────────────┘
                    │                         │
                    ▼                         ▼
          ┌─────────────────┐       ┌─────────────────┐
          │     Qdrant      │       │   PostgreSQL    │
          │  (Local Dev)    │       │   + pgvector    │
          └─────────────────┘       └─────────────────┘
```

---

## Project Structure

```
src/
├── server.py              # MCP server entry point
├── config.py              # Configuration management
├── tools/                 # MCP tool implementations
│   ├── search.py          # rag_search
│   ├── store.py           # rag_store, rag_store_batch
│   └── collections.py     # Collection management
├── vectorstore/           # Backend abstraction
│   ├── base.py            # Abstract interface
│   ├── qdrant_store.py    # Qdrant implementation
│   ├── pgvector_store.py  # PostgreSQL implementation
│   └── factory.py         # Backend factory
└── embeddings/            # Embedding generation
```

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `rag_search` | Semantic similarity search with score threshold |
| `rag_store` | Store document with automatic embedding |
| `rag_store_batch` | Efficient bulk document storage |
| `rag_list_collections` | List available collections |
| `rag_collection_stats` | Collection metrics and status |
| `rag_delete_collection` | Remove collection with confirmation |

---

## Quick Start

```bash
# Local development with Qdrant
docker compose up -d
curl http://localhost:8003/health

# Add to Claude Code
claude mcp add-json rag-mcp-server '{"type":"sse","url":"http://localhost:8003/sse"}'
```

---

## Backend Selection

**Qdrant** (default - local development):
```bash
RAG_VECTOR_BACKEND=qdrant
RAG_QDRANT_URL=http://qdrant:6333
```

**PostgreSQL + pgvector** (Kubernetes/RDS):
```bash
RAG_VECTOR_BACKEND=pgvector
RAG_DATABASE_URL=postgresql://user:password@host:5432/database
```

| Aspect | Qdrant | PostgreSQL + pgvector |
|--------|--------|----------------------|
| **Use Case** | Local dev, dedicated vector DB | Kubernetes, existing RDS |
| **Setup** | Single container | Requires PostgreSQL |
| **Scaling** | Horizontal (sharding) | Vertical + replicas |

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_VECTOR_BACKEND` | `qdrant` | `qdrant` or `pgvector` |
| `RAG_MCP_MODE` | `stdio` | `stdio` or `http` |
| `RAG_MCP_PORT` | `8003` | HTTP server port |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Embedding model |
| `RAG_SCORE_THRESHOLD` | `0.7` | Minimum similarity (0.0-1.0) |

---

## Technologies

`MCP Protocol` `Qdrant` `PostgreSQL pgvector` `FastEmbed` `Python` `Docker` `Kubernetes`

---

MIT License
