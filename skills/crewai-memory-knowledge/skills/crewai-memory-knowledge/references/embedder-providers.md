# Embedder Provider Reference

Quick-reference for all supported embedding providers in CrewAI Memory and Knowledge.

## Provider Table

| Provider | Key | Typical Model | Notes |
|----------|-----|---------------|-------|
| OpenAI | `openai` | `text-embedding-3-small` | Default. Set `OPENAI_API_KEY`. |
| Ollama | `ollama` | `mxbai-embed-large` | Local, no API key needed. |
| Azure OpenAI | `azure` | `text-embedding-ada-002` | Requires `deployment_id`. |
| Google AI | `google-generativeai` | `gemini-embedding-001` | Set `GOOGLE_API_KEY`. |
| Google Vertex | `google-vertex` | `gemini-embedding-001` | Requires `project_id`. |
| Cohere | `cohere` | `embed-english-v3.0` | Strong multilingual support. |
| VoyageAI | `voyageai` | `voyage-3` | Optimized for retrieval. Recommended for Claude users. |
| AWS Bedrock | `amazon-bedrock` | `amazon.titan-embed-text-v1` | Uses boto3 credentials. |
| Hugging Face | `huggingface` | `all-MiniLM-L6-v2` | Local sentence-transformers. |
| Jina | `jina` | `jina-embeddings-v2-base-en` | Set `JINA_API_KEY`. |
| IBM WatsonX | `watsonx` | `ibm/slate-30m-english-rtrvr` | Requires `project_id`. |
| Sentence Transformer | `sentence-transformer` | `all-MiniLM-L6-v2` | Local, no API key. |
| Custom | `custom` | -- | Requires `embedding_callable`. |

## Configuration Examples

### OpenAI (default)

```python
embedder = {
    "provider": "openai",
    "config": {
        "model_name": "text-embedding-3-small",
        # "api_key": "sk-...",  # or set OPENAI_API_KEY env var
    },
}
```

### Ollama (local, private)

```python
embedder = {
    "provider": "ollama",
    "config": {
        "model_name": "mxbai-embed-large",
        "url": "http://localhost:11434/api/embeddings",
    },
}
```

### Azure OpenAI

```python
embedder = {
    "provider": "azure",
    "config": {
        "deployment_id": "your-embedding-deployment",
        "api_key": "your-azure-api-key",
        "api_base": "https://your-resource.openai.azure.com",
        "api_version": "2024-02-01",
    },
}
```

### Google AI

```python
embedder = {
    "provider": "google-generativeai",
    "config": {
        "model_name": "gemini-embedding-001",
        # "api_key": "...",  # or set GOOGLE_API_KEY env var
    },
}
```

### Google Vertex AI

```python
embedder = {
    "provider": "google-vertex",
    "config": {
        "model_name": "gemini-embedding-001",
        "project_id": "your-gcp-project-id",
        "location": "us-central1",
    },
}
```

### Cohere

```python
embedder = {
    "provider": "cohere",
    "config": {
        "model_name": "embed-english-v3.0",
        # "api_key": "...",  # or set COHERE_API_KEY env var
    },
}
```

### VoyageAI

```python
embedder = {
    "provider": "voyageai",
    "config": {
        "model": "voyage-3",
        # "api_key": "...",  # or set VOYAGE_API_KEY env var
    },
}
```

### AWS Bedrock

```python
embedder = {
    "provider": "amazon-bedrock",
    "config": {
        "model_name": "amazon.titan-embed-text-v1",
        # Uses default AWS credentials (boto3 session)
    },
}
```

### Hugging Face

```python
embedder = {
    "provider": "huggingface",
    "config": {
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
    },
}
```

### Jina

```python
embedder = {
    "provider": "jina",
    "config": {
        "model_name": "jina-embeddings-v2-base-en",
        # "api_key": "...",  # or set JINA_API_KEY env var
    },
}
```

### IBM WatsonX

```python
embedder = {
    "provider": "watsonx",
    "config": {
        "model_id": "ibm/slate-30m-english-rtrvr",
        "api_key": "your-watsonx-api-key",
        "project_id": "your-project-id",
        "url": "https://us-south.ml.cloud.ibm.com",
    },
}
```

### Custom Embedder

```python
def my_embedder(texts: list[str]) -> list[list[float]]:
    # Your embedding logic here
    return [[0.1, 0.2, ...] for _ in texts]

# Pass as a callable
memory = Memory(embedder=my_embedder)
```

### Pre-built Callable

```python
from crewai.rag.embeddings.factory import build_embedder

embedder = build_embedder({"provider": "ollama", "config": {"model_name": "mxbai-embed-large"}})
memory = Memory(embedder=embedder)
```

---

## Memory Configuration Reference

All parameters passed as keyword arguments to `Memory(...)`. Every parameter has a sensible default.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `llm` | `"gpt-4o-mini"` | LLM for analysis (model name or `BaseLLM` instance). |
| `storage` | `"lancedb"` | Storage backend (`"lancedb"`, a path string, or `StorageBackend` instance). |
| `embedder` | `None` (OpenAI default) | Embedder config dict, callable, or `None` for default OpenAI. |
| `recency_weight` | `0.3` | Weight for recency in composite score. |
| `semantic_weight` | `0.5` | Weight for semantic similarity in composite score. |
| `importance_weight` | `0.2` | Weight for importance in composite score. |
| `recency_half_life_days` | `30` | Days for recency score to halve (exponential decay). |
| `consolidation_threshold` | `0.85` | Similarity above which consolidation is triggered. Set to `1.0` to disable. |
| `consolidation_limit` | `5` | Max existing records to compare during consolidation. |
| `default_importance` | `0.5` | Importance when not provided and LLM analysis is skipped. |
| `batch_dedup_threshold` | `0.98` | Cosine similarity for dropping near-duplicates in `remember_many()`. |
| `confidence_threshold_high` | `0.8` | Recall confidence above which results are returned directly. |
| `confidence_threshold_low` | `0.5` | Recall confidence below which deeper exploration is triggered. |
| `complex_query_threshold` | `0.7` | For complex queries, explore deeper below this confidence. |
| `exploration_budget` | `1` | Number of LLM-driven exploration rounds during deep recall. |
| `query_analysis_threshold` | `200` | Queries shorter than this (chars) skip LLM analysis in deep recall. |

### LLM Configuration for Memory

```python
from crewai import Memory, LLM

memory = Memory()                                          # Default: gpt-4o-mini
memory = Memory(llm="gpt-4o")                             # Different OpenAI model
memory = Memory(llm="anthropic/claude-3-haiku-20240307")   # Anthropic
memory = Memory(llm="ollama/llama3.2")                     # Local (fully private)
memory = Memory(llm="gemini/gemini-2.0-flash")             # Google Gemini
memory = Memory(llm=LLM(model="gpt-4o", temperature=0))   # Pre-configured instance
```

The LLM is initialized lazily -- only created when first needed. `Memory()` never fails at construction time even without API keys.

### Memory Events

| Event | Description | Key Properties |
|-------|-------------|----------------|
| `MemoryQueryStartedEvent` | Query begins | `query`, `limit` |
| `MemoryQueryCompletedEvent` | Query succeeds | `query`, `results`, `query_time_ms` |
| `MemoryQueryFailedEvent` | Query fails | `query`, `error` |
| `MemorySaveStartedEvent` | Save begins | `value`, `metadata` |
| `MemorySaveCompletedEvent` | Save succeeds | `value`, `save_time_ms` |
| `MemorySaveFailedEvent` | Save fails | `value`, `error` |
| `MemoryRetrievalStartedEvent` | Agent retrieval starts | `task_id` |
| `MemoryRetrievalCompletedEvent` | Agent retrieval done | `task_id`, `memory_content`, `retrieval_time_ms` |
