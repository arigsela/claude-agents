# RAG MCP Server

A Model Context Protocol (MCP) server providing semantic search and document storage capabilities using vector embeddings. Supports dual backends: **Qdrant** for local development and **PostgreSQL + pgvector** for Kubernetes/RDS deployments.

## Features

- **Semantic Search**: Find documents using natural language queries
- **Document Storage**: Store and index documents with automatic embedding generation
- **Batch Operations**: Efficiently store multiple documents at once
- **Collection Management**: Organize documents into separate collections
- **Deduplication**: Content-hash based deduplication prevents duplicate storage
- **Dual Backend Support**:
  - **Qdrant**: Purpose-built vector database for local development
  - **PostgreSQL + pgvector**: Use existing RDS infrastructure for Kubernetes deployments

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Claude Code / MCP Client                  │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    │ MCP Protocol (stdio/SSE)
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                         RAG MCP Server                           │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  MCP Tools  │  │  Embeddings  │  │   Vector Store Layer   │  │
│  │  - search   │  │  (FastEmbed) │  │  ┌────────┐ ┌────────┐ │  │
│  │  - store    │  │  BAAI/bge-   │  │  │ Qdrant │ │pgvector│ │  │
│  │  - batch    │  │  small-en    │  │  └────────┘ └────────┘ │  │
│  │  - list     │  └──────────────┘  └────────────────────────┘  │
│  │  - stats    │                                                 │
│  │  - delete   │                                                 │
│  └─────────────┘                                                 │
└─────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
          ┌─────────────────┐             ┌─────────────────┐
          │     Qdrant      │             │   PostgreSQL    │
          │  (Local/Docker) │             │   + pgvector    │
          │                 │             │   (RDS/K8s)     │
          └─────────────────┘             └─────────────────┘
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development without Docker)

### Local Development with Qdrant (Default)

```bash
# Start Qdrant + RAG MCP Server
docker compose up -d

# Check health
curl http://localhost:8003/health

# View logs
docker compose logs -f rag-mcp-server
```

### Local Development with PostgreSQL + pgvector

```bash
# Start PostgreSQL + RAG MCP Server (pgvector mode)
docker compose --profile pgvector up postgres rag-mcp-server-pgvector -d

# Check health
curl http://localhost:8003/health

# Connect to PostgreSQL (port 5433 to avoid conflicts)
psql -h localhost -p 5433 -U ragmcp -d ragmcp
```

### Claude Code Integration

Add the MCP server to Claude Code:

```bash
claude mcp add-json rag-mcp-server '{"type":"sse","url":"http://localhost:8003/sse"}'
```

Then restart Claude Code to enable the tools.

## MCP Tools

| Tool | Description |
|------|-------------|
| `rag_search` | Search for documents using semantic similarity |
| `rag_store` | Store a single document with embeddings |
| `rag_store_batch` | Store multiple documents efficiently |
| `rag_list_collections` | List all available collections |
| `rag_collection_stats` | Get statistics for a collection |
| `rag_delete_collection` | Delete a collection and all its documents |

### Example Usage (via Claude Code)

```
# Search for relevant documents
Use rag_search to find documents about "kubernetes pod restarts"

# Store a new document
Use rag_store to save this troubleshooting guide to the "runbooks" collection

# List collections
Use rag_list_collections to see what's available
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_VECTOR_BACKEND` | `qdrant` | Vector store: `qdrant` or `pgvector` |
| `RAG_QDRANT_URL` | `http://localhost:6333` | Qdrant server URL |
| `RAG_DATABASE_URL` | - | PostgreSQL connection string (pgvector) |
| `RAG_MCP_MODE` | `stdio` | MCP transport: `stdio` or `http` |
| `RAG_MCP_HOST` | `0.0.0.0` | HTTP server bind address |
| `RAG_MCP_PORT` | `8003` | HTTP server port |
| `RAG_DEFAULT_COLLECTION` | `default` | Default collection name |
| `RAG_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Embedding model |
| `RAG_VECTOR_SIZE` | `384` | Embedding vector dimensions |
| `RAG_SEARCH_LIMIT` | `10` | Default search result limit |
| `RAG_SCORE_THRESHOLD` | `0.7` | Minimum similarity score (0.0-1.0) |
| `RAG_LOG_LEVEL` | `INFO` | Logging level |

### Backend Selection

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

## Kubernetes Deployment

### With RDS PostgreSQL + pgvector

1. **Enable pgvector extension on RDS:**
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

2. **Create Kubernetes resources:**
   ```bash
   # Create namespace
   kubectl apply -f k8s/namespace.yaml

   # Create ConfigMap (set RAG_VECTOR_BACKEND=pgvector)
   kubectl apply -f k8s/configmap.yaml

   # Create Secret with database credentials
   kubectl create secret generic rag-mcp-secrets \
     --from-literal=RAG_DATABASE_URL="postgresql://user:pass@rds-host:5432/db" \
     -n rag-mcp

   # Deploy
   kubectl apply -f k8s/rag-mcp-deployment.yaml
   kubectl apply -f k8s/rbac.yaml
   ```

3. **Verify deployment:**
   ```bash
   kubectl get pods -n rag-mcp
   kubectl logs -f deployment/rag-mcp-server -n rag-mcp
   ```

### With Qdrant (StatefulSet)

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/qdrant-statefulset.yaml
kubectl apply -f k8s/configmap.yaml  # Set RAG_VECTOR_BACKEND=qdrant
kubectl apply -f k8s/rag-mcp-deployment.yaml
```

## Project Structure

```
rag-mcp-server/
├── src/
│   ├── server.py              # MCP server entry point
│   ├── config.py              # Configuration settings
│   ├── tools/                 # MCP tool implementations
│   │   ├── search.py          # rag_search tool
│   │   ├── store.py           # rag_store, rag_store_batch tools
│   │   └── collections.py     # Collection management tools
│   ├── vectorstore/           # Vector store abstraction
│   │   ├── base.py            # Abstract interface
│   │   ├── qdrant_store.py    # Qdrant implementation
│   │   ├── pgvector_store.py  # PostgreSQL + pgvector implementation
│   │   └── factory.py         # Backend factory
│   ├── embeddings/            # Embedding generation
│   └── sync/                  # Content sync engine
├── k8s/                       # Kubernetes manifests
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secrets.yaml           # Template (don't commit real credentials!)
│   ├── rag-mcp-deployment.yaml
│   ├── qdrant-statefulset.yaml
│   └── rbac.yaml
├── config/                    # Configuration files
├── sample-playbooks/          # Example content for testing
├── docker-compose.yml         # Local development stack
├── Dockerfile                 # Multi-stage production image
└── requirements.txt           # Python dependencies
```

## Development

### Running Locally (without Docker)

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start Qdrant
docker run -d -p 6333:6333 qdrant/qdrant:v1.16.2

# Run MCP server (stdio mode for claude-code)
python -m src.server

# Or HTTP mode
RAG_MCP_MODE=http python -m src.server
```

### Testing

```bash
# Health check
curl http://localhost:8003/health

# List available tools
curl http://localhost:8003/tools
```

### Building Docker Image

```bash
docker compose build rag-mcp-server
```

## Backend Comparison

| Feature | Qdrant | PostgreSQL + pgvector |
|---------|--------|----------------------|
| **Use Case** | Local dev, dedicated vector DB | Kubernetes, existing RDS |
| **Setup** | Simple (single container) | Requires PostgreSQL setup |
| **Scaling** | Horizontal (sharding) | Vertical + read replicas |
| **Index Type** | HNSW (native) | HNSW (pgvector extension) |
| **Filtering** | Rich payload filtering | SQL WHERE clauses |
| **Maintenance** | Minimal | Standard PostgreSQL ops |
| **Cost** | Separate infrastructure | Leverage existing RDS |

### When to Use Each

**Use Qdrant when:**
- Local development and testing
- Dedicated vector search infrastructure
- High-volume vector operations
- Need Qdrant-specific features (filtering, payload indexing)

**Use PostgreSQL + pgvector when:**
- Deploying to Kubernetes with existing RDS
- Want to minimize infrastructure complexity
- Already have PostgreSQL expertise
- Moderate vector search volume

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs rag-mcp-server

# Verify vector store is healthy
docker compose logs qdrant     # or postgres
```

### Port conflicts

The pgvector profile uses port 5433 for PostgreSQL to avoid conflicts with other PostgreSQL instances:

```bash
# If port 5433 is also in use, modify docker-compose.yml
ports:
  - "5434:5432"  # Change external port
```

### MCP tools not appearing in Claude Code

1. Verify server is running: `curl http://localhost:8003/health`
2. Check MCP configuration: `claude mcp list`
3. Restart Claude Code after adding MCP server

### pgvector tables not created

Tables are created on first tool call. Trigger initialization:
```bash
# Store a test document via Claude Code
Use rag_store to save "test content" to the "test" collection
```

## License

MIT
