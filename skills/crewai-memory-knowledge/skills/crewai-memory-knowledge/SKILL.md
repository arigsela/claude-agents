---
name: crewai-memory-knowledge
description: >
  Give CrewAI agents persistent context with the unified Memory API (hierarchical scopes,
  memory slices, composite scoring, LLM analysis, consolidation, non-blocking saves) and
  domain knowledge via RAG sources (string, text, PDF, CSV, Excel, JSON, Docling, custom).
  Covers agent vs crew knowledge, embedder configuration for 12+ providers, KnowledgeConfig
  tuning, query rewriting, knowledge events, and storage management.
triggers:
  - crewai memory
  - crewai knowledge
  - agent memory
  - crew knowledge
  - remember recall
  - knowledge source
  - rag crewai
  - embedder
  - memory scope
  - memory slice
  - vector store crewai
  - chromadb crewai
  - persistent context
  - composite scoring
  - recall depth
version: "1.0.0"
author:
  name: "Arisela"
tags: [crewai, memory, knowledge, rag, embeddings, vector-store, scopes, recall, chromadb]
category: learning
repository: "https://github.com/arigsela/claude-agents"
license: "MIT"
---

# CrewAI Memory & Knowledge Expert

This skill teaches you how to give CrewAI agents two complementary forms of persistent context:

- **Memory** -- runtime recall of facts, decisions, and observations that accumulate as agents work. Built on vector search with composite scoring.
- **Knowledge** -- pre-loaded domain information (documents, databases, APIs) that agents consult during task execution. Built on RAG with ChromaDB or Qdrant.

Use memory when agents need to learn and remember during execution. Use knowledge when agents need reference material that already exists.

## Decision Workflow

When a user asks about giving agents persistent context, classify the request:

| Need | Solution | Jump to |
|------|----------|---------|
| Agents should remember what happened in previous tasks/runs | Unified Memory | [Memory System](#unified-memory-system) |
| An agent needs its own private working notes | Scoped Memory | [Hierarchical Scopes](#hierarchical-scopes) |
| An agent needs to read from multiple memory branches | Memory Slices | [Memory Slices](#memory-slices) |
| Agents need access to existing documents (PDF, CSV, etc.) | Knowledge Sources | [Knowledge System](#knowledge-system) |
| Only one agent needs specific reference data | Agent Knowledge | [Agent vs Crew Knowledge](#agent-vs-crew-knowledge) |
| All agents in a crew need shared reference data | Crew Knowledge | [Agent vs Crew Knowledge](#agent-vs-crew-knowledge) |
| Need to load data from a custom API or database | Custom Knowledge Source | [Custom Knowledge Sources](#custom-knowledge-sources) |
| Need to control which embedding model is used | Embedder Config | [Embedder Configuration](#embedder-configuration) |
| Need both runtime learning AND reference data | Memory + Knowledge | [Memory vs Knowledge](#memory-vs-knowledge-when-to-use-which) |

---

## Unified Memory System

### Quick Start

```python
from crewai import Memory

memory = Memory()

# Store -- LLM infers scope, categories, and importance automatically
memory.remember("We decided to use PostgreSQL for the user database.")

# Retrieve -- results ranked by composite score (semantic + recency + importance)
matches = memory.recall("What database did we choose?")
for m in matches:
    print(f"[{m.score:.2f}] {m.record.content}")

# Tune scoring weights for a fast-moving project
memory = Memory(recency_weight=0.5, recency_half_life_days=7)

# Forget an entire scope subtree
memory.forget(scope="/project/old")

# Explore the self-organized scope tree
print(memory.tree())
print(memory.info("/"))
```

### Four Ways to Use Memory

**1. Standalone** -- scripts, notebooks, CLI tools. No agents required.

```python
from crewai import Memory

memory = Memory()
memory.remember("The API rate limit is 1000 requests per minute.")
memory.remember("Our staging environment uses port 8080.")

matches = memory.recall("What are our API limits?", limit=5)

# Extract atomic facts from longer text
raw = """Meeting notes: We decided to migrate from MySQL to PostgreSQL
next quarter. The budget is $50k. Sarah will lead the migration."""
facts = memory.extract_memories(raw)
for fact in facts:
    memory.remember(fact)
```

**2. With Crews** -- pass `memory=True` for defaults, or a configured `Memory` instance.

```python
from crewai import Crew, Agent, Task, Process, Memory

# Default memory
crew = Crew(agents=[researcher, writer], tasks=[...], memory=True)

# Custom-tuned memory
memory = Memory(
    recency_weight=0.4,
    semantic_weight=0.4,
    importance_weight=0.2,
    recency_half_life_days=14,
)
crew = Crew(agents=[researcher, writer], tasks=[...], memory=memory)
```

When `memory=True`, the crew creates a default `Memory()` and passes the crew's `embedder` config through. After each task, the crew auto-extracts discrete facts from the output and stores them. Before each task, the agent recalls relevant context and injects it into the prompt.

**3. With Agents** -- give an agent a scoped view for private context.

```python
from crewai import Agent, Memory

memory = Memory()

# Researcher gets private scope -- only sees /agent/researcher
researcher = Agent(
    role="Researcher",
    goal="Find and analyze information",
    backstory="Expert researcher",
    memory=memory.scope("/agent/researcher"),
)

# Writer uses crew shared memory (no agent-level memory set)
writer = Agent(
    role="Writer",
    goal="Produce clear content",
    backstory="Technical writer",
)
```

**4. With Flows** -- built-in `self.remember()`, `self.recall()`, `self.extract_memories()`.

```python
from crewai.flow.flow import Flow, listen, start

class ResearchFlow(Flow):
    @start()
    def gather_data(self):
        findings = "PostgreSQL handles 10k concurrent connections."
        self.remember(findings, scope="/research/databases")
        return findings

    @listen(gather_data)
    def write_report(self, findings):
        past = self.recall("database performance benchmarks")
        context = "\n".join(f"- {m.record.content}" for m in past)
        return f"New: {findings}\nPast:\n{context}"
```

### Hierarchical Scopes

Memories are organized in a tree structure similar to a filesystem:

```
/
  /company
    /company/engineering
    /company/product
  /project
    /project/alpha
    /project/beta
  /agent
    /agent/researcher
    /agent/writer
```

**Scope inference**: When you omit the `scope` parameter, the LLM analyzes the content and the existing tree, then places the memory where it fits best. Over time the tree grows organically -- no upfront schema needed.

```python
# LLM infers scope from content
memory.remember("We chose PostgreSQL for the user database.")
# -> placed under /project/decisions or /engineering/database

# Or specify explicitly when you know
memory.remember("Sprint velocity is 42 points", scope="/team/metrics")
```

**MemoryScope** restricts all operations to a subtree:

```python
agent_memory = memory.scope("/agent/researcher")
agent_memory.remember("Found three relevant papers on LLM memory.")
# -> stored under /agent/researcher

agent_memory.recall("relevant papers")
# -> searches only /agent/researcher

# Narrow further with subscope
project_memory = agent_memory.subscope("project-alpha")
# -> /agent/researcher/project-alpha
```

**Scope design best practices**:
- Start flat, let the LLM organize. Do not over-engineer upfront.
- Use `/{entity_type}/{identifier}` patterns: `/project/alpha`, `/agent/researcher`, `/customer/acme`.
- Scope by concern, not data type: `/project/alpha/decisions` not `/decisions/project/alpha`.
- Keep depth at 2-3 levels. Deeper scopes become too sparse.

### Memory Slices

A `MemorySlice` is a view across multiple, possibly disjoint scopes. Use slices when you need to combine context from several branches.

| Use Case | Tool |
|----------|------|
| Restrict to one subtree | `memory.scope("/agent/researcher")` |
| Combine multiple branches | `memory.slice(scopes=[...])` |

**Read-only slice** (most common pattern):

```python
agent_view = memory.slice(
    scopes=["/agent/researcher", "/company/knowledge"],
    read_only=True,
)
matches = agent_view.recall("company security policies", limit=5)
# Searches both scopes, merges and ranks results

agent_view.remember("new finding")  # Raises PermissionError
```

**Read-write slice** (must specify target scope):

```python
view = memory.slice(scopes=["/team/alpha", "/team/beta"], read_only=False)
view.remember("Cross-team decision", scope="/team/alpha", categories=["decisions"])
```

### Composite Scoring

Recall results are ranked by a weighted combination:

```
composite = semantic_weight * similarity + recency_weight * decay + importance_weight * importance
```

Where:
- **similarity** = `1 / (1 + distance)` from the vector index (0 to 1)
- **decay** = `0.5 ^ (age_days / half_life_days)` -- exponential decay
- **importance** = the record's importance score (0 to 1), set at encoding time

**Tuning profiles**:

```python
# Sprint retrospective: favor recent memories, short half-life
memory = Memory(recency_weight=0.5, semantic_weight=0.3, importance_weight=0.2, recency_half_life_days=7)

# Architecture knowledge base: favor important memories, long half-life
memory = Memory(recency_weight=0.1, semantic_weight=0.5, importance_weight=0.4, recency_half_life_days=180)
```

Each `MemoryMatch` includes a `match_reasons` list (e.g. `["semantic", "recency", "importance"]`).

### LLM Analysis Layer

Memory uses the LLM in three ways:

1. **On save** -- Infers scope, categories, importance, and metadata when you omit them.
2. **On recall** -- For deep recall, analyzes the query to guide retrieval (keywords, time hints, scopes).
3. **Extract memories** -- `extract_memories(content)` breaks raw text into atomic fact statements before storing.

All analysis degrades gracefully: if the LLM fails, memory still stores/recalls with safe defaults (scope `/`, empty categories, importance `0.5`).

### Memory Consolidation and Dedup

**Cross-record consolidation**: On save, the pipeline checks for similar existing records (similarity > `consolidation_threshold`, default 0.85). The LLM decides to keep, update, delete, or insert_new. This prevents duplicates from accumulating.

**Intra-batch dedup**: `remember_many()` compares items within the same batch using pure vector math (cosine similarity >= `batch_dedup_threshold`, default 0.98). Near-duplicates are dropped without LLM calls.

### Non-blocking Saves and Read Barriers

`remember_many()` is non-blocking -- it submits to a background thread and returns immediately. Every `recall()` automatically calls `drain_writes()` first, so queries always see the latest records.

For standalone scripts without a crew lifecycle:

```python
memory = Memory()
memory.remember_many(["Fact A.", "Fact B."])
memory.drain_writes()   # Wait for pending saves
memory.close()          # Drain and shut down the background pool
```

### Source and Privacy

Tag memories with provenance and restrict access:

```python
memory.remember("User prefers dark mode", source="user:alice")
memory.remember("Alice's API key is sk-...", source="user:alice", private=True)

# Source-matched recall sees private memories
memory.recall("API key", source="user:alice")   # sees the key

# Different source does NOT
memory.recall("API key", source="user:bob")     # does not see it

# Admin override
memory.recall("API key", include_private=True)  # sees all
```

### RecallFlow (Shallow vs Deep Recall)

- **`depth="shallow"`** -- Direct vector search. Fast (~200ms), no LLM calls.
- **`depth="deep"` (default)** -- Multi-step RecallFlow: query analysis, scope selection, parallel vector search, confidence routing, optional recursive exploration.

**Smart LLM skip**: Queries shorter than `query_analysis_threshold` (default 200 chars) skip LLM analysis even in deep mode. Short queries are already good search phrases.

```python
# Shallow: pure vector search
matches = memory.recall("What did we decide?", limit=10, depth="shallow")

# Deep: LLM-guided retrieval for complex queries
matches = memory.recall(
    "Summarize all architecture decisions from this quarter",
    limit=10, depth="deep",
)
```

### Discovery Commands

```python
memory.tree()                          # Full scope tree with record counts
memory.tree("/project", max_depth=2)   # Subtree view
memory.info("/project")                # ScopeInfo: record_count, categories, dates
memory.list_scopes("/")                # Immediate child scopes
memory.list_categories()               # Category names and counts
memory.list_records(scope="/project/alpha", limit=20)  # Records, newest first
```

CLI browser:

```bash
crewai memory                              # Opens TUI browser
crewai memory --storage-path ./my_memory   # Point to a specific directory
```

### Memory Reset

```python
memory.reset()                       # All scopes
memory.reset(scope="/project/old")   # Only that subtree

# Via crew
crew.reset_memories(command_type="memory")
```

---

## Knowledge System

Knowledge gives agents pre-loaded reference material via RAG. Files are chunked, embedded, and stored in ChromaDB (default) or Qdrant for semantic retrieval at task time.

### Supported Knowledge Sources

| Source | Class | Import Path |
|--------|-------|-------------|
| Raw strings | `StringKnowledgeSource` | `crewai.knowledge.source.string_knowledge_source` |
| Text files | `TextFileKnowledgeSource` | `crewai.knowledge.source.text_file_knowledge_source` |
| PDFs | `PDFKnowledgeSource` | `crewai.knowledge.source.pdf_knowledge_source` |
| CSVs | `CSVKnowledgeSource` | `crewai.knowledge.source.csv_knowledge_source` |
| Excel | `ExcelKnowledgeSource` | `crewai.knowledge.source.excel_knowledge_source` |
| JSON | `JSONKnowledgeSource` | `crewai.knowledge.source.json_knowledge_source` |
| Web/docs (Docling) | `CrewDoclingSource` | `crewai.knowledge.source.crew_docling_source` |

Place source files in a `knowledge/` directory at the project root. Use relative paths from that directory.

```python
from crewai.knowledge.source.string_knowledge_source import StringKnowledgeSource
from crewai.knowledge.source.pdf_knowledge_source import PDFKnowledgeSource
from crewai.knowledge.source.csv_knowledge_source import CSVKnowledgeSource

string_src = StringKnowledgeSource(content="Users name is John. He is 30.")
pdf_src    = PDFKnowledgeSource(file_paths=["report.pdf"])
csv_src    = CSVKnowledgeSource(file_paths=["data.csv"])
```

### Agent vs Crew Knowledge

**Agent-level knowledge** -- only that agent sees it. Stored in a collection named after the agent's role.

```python
specialist_knowledge = StringKnowledgeSource(content="Technical specs for this agent only")

specialist = Agent(
    role="Technical Specialist",
    goal="Provide technical expertise",
    backstory="Domain expert",
    knowledge_sources=[specialist_knowledge],
)

crew = Crew(agents=[specialist], tasks=[...])  # No crew knowledge needed
```

**Crew-level knowledge** -- shared by all agents. Stored in a collection named `"crew"`.

```python
crew_knowledge = StringKnowledgeSource(content="Company policies for all agents")
specialist_knowledge = StringKnowledgeSource(content="Tech specs for specialist only")

specialist = Agent(role="Specialist", ..., knowledge_sources=[specialist_knowledge])
generalist = Agent(role="Generalist", ...)

crew = Crew(
    agents=[specialist, generalist],
    tasks=[...],
    knowledge_sources=[crew_knowledge],
)
# specialist sees: crew_knowledge + specialist_knowledge
# generalist sees: crew_knowledge only
```

**Storage independence**: Each level uses separate ChromaDB collections. Agent collections are named by role, crew collection is named `"crew"`. Both live under `~/.local/share/CrewAI/{project}/knowledge/` (Linux) or the platform equivalent.

### KnowledgeConfig

Tune retrieval parameters per agent or crew:

```python
from crewai.knowledge.knowledge_config import KnowledgeConfig

config = KnowledgeConfig(
    results_limit=10,     # Number of chunks to return (default: 3)
    score_threshold=0.5,  # Minimum relevance score (default: 0.35)
)

agent = Agent(..., knowledge_config=config)
```

### Custom Knowledge Sources

Extend `BaseKnowledgeSource` to load data from any API, database, or service:

```python
from crewai.knowledge.source.base_knowledge_source import BaseKnowledgeSource
from pydantic import Field
import requests

class APIKnowledgeSource(BaseKnowledgeSource):
    """Fetch and chunk data from a REST API."""

    api_url: str = Field(description="API endpoint URL")
    limit: int = Field(default=10)

    def load_content(self) -> dict:
        resp = requests.get(f"{self.api_url}?limit={self.limit}")
        resp.raise_for_status()
        articles = resp.json().get("results", [])
        text = "\n---\n".join(
            f"Title: {a['title']}\nSummary: {a['summary']}" for a in articles
        )
        return {self.api_url: text}

    def validate_content(self, data) -> str:
        return data  # Already formatted in load_content

    def add(self) -> None:
        content = self.load_content()
        for _, text in content.items():
            chunks = self._chunk_text(text)
            self.chunks.extend(chunks)
        self._save_documents()
```

### Query Rewriting

When an agent executes a task with knowledge sources, CrewAI automatically rewrites the raw task prompt into an optimized search query using the agent's LLM. This is fully automatic -- no configuration needed. A more capable LLM produces better rewrites.

Example: `"Answer questions about the user's movies: What did John watch? Format as JSON."` becomes `"What movies did John watch?"`.

### Knowledge Events

Monitor knowledge retrieval with the event system:

```python
from crewai.events import BaseEventListener, KnowledgeRetrievalCompletedEvent

class KnowledgeMonitor(BaseEventListener):
    def setup_listeners(self, crewai_event_bus):
        @crewai_event_bus.on(KnowledgeRetrievalCompletedEvent)
        def on_done(source, event):
            print(f"Agent '{event.agent.role}' retrieved {len(event.retrieved_knowledge)} chunks")
            print(f"Query: {event.query}")
```

Available events: `KnowledgeRetrievalStartedEvent`, `KnowledgeRetrievalCompletedEvent`, `KnowledgeQueryStartedEvent`, `KnowledgeQueryCompletedEvent`, `KnowledgeQueryFailedEvent`, `KnowledgeSearchQueryFailedEvent`.

### Storage Locations by Platform

| Platform | Default Path |
|----------|-------------|
| macOS | `~/Library/Application Support/CrewAI/{project}/knowledge/` |
| Linux | `~/.local/share/CrewAI/{project}/knowledge/` |
| Windows | `C:\Users\{user}\AppData\Local\CrewAI\{project}\knowledge\` |

Override with environment variable:

```python
import os
os.environ["CREWAI_STORAGE_DIR"] = "./my_project_storage"
# All knowledge stored in ./my_project_storage/knowledge/
```

### RAG Client Configuration

CrewAI exposes a provider-neutral RAG client for direct vector store control:

```python
from crewai.rag.config.utils import set_rag_config, get_rag_client

# ChromaDB (default)
from crewai.rag.chromadb.config import ChromaDBConfig
set_rag_config(ChromaDBConfig())
client = get_rag_client()

# Qdrant
from crewai.rag.qdrant.config import QdrantConfig
set_rag_config(QdrantConfig())
client = get_rag_client()

# Same API for any provider
client.create_collection(collection_name="docs")
client.add_documents(collection_name="docs", documents=[{"id": "1", "content": "..."}])
results = client.search(collection_name="docs", query="search term", limit=3)
```

---

## Embedder Configuration

Both Memory and Knowledge need an embedding model. The default is OpenAI `text-embedding-3-small`. You can configure it at the Memory, Crew, or Agent level.

**Memory-level**:

```python
memory = Memory(embedder={"provider": "openai", "config": {"model_name": "text-embedding-3-small"}})
```

**Crew-level** (applies to both memory and knowledge):

```python
crew = Crew(
    agents=[...], tasks=[...],
    memory=True,
    knowledge_sources=[...],
    embedder={"provider": "openai", "config": {"model_name": "text-embedding-3-small"}},
)
```

**Agent-level** (for agent-specific knowledge):

```python
agent = Agent(
    role="Specialist", ...,
    knowledge_sources=[...],
    embedder={"provider": "ollama", "config": {"model": "mxbai-embed-large"}},
)
```

See **references/embedder-providers.md** for the full provider reference table with config examples for OpenAI, Ollama, Azure, Google AI, Google Vertex, Cohere, VoyageAI, AWS Bedrock, HuggingFace, Jina, WatsonX, and custom callables.

---

## Memory vs Knowledge: When to Use Which

| Dimension | Memory | Knowledge |
|-----------|--------|-----------|
| **When data arrives** | At runtime, during agent execution | Before execution, pre-loaded |
| **What it stores** | Facts, decisions, observations agents learn | Documents, datasets, reference material |
| **Persistence** | Across tasks and runs (LanceDB) | Across runs (ChromaDB/Qdrant) |
| **Retrieval** | `recall()` with composite scoring | Automatic RAG at task start |
| **Scope control** | Hierarchical scopes and slices | Agent-level or crew-level collections |
| **Primary use** | Agent learns from experience | Agent consults reference library |

**How they complement each other**: Knowledge provides the baseline reference data. Memory captures what agents learn while working. Over time, an agent with both can consult its knowledge base AND remember what it discovered in previous runs.

```python
from crewai import Crew, Memory
from crewai.knowledge.source.pdf_knowledge_source import PDFKnowledgeSource

# Knowledge: pre-loaded reference docs
docs = PDFKnowledgeSource(file_paths=["architecture-guide.pdf", "runbook.pdf"])

# Memory: runtime learning with custom scoring
memory = Memory(recency_weight=0.4, semantic_weight=0.4, importance_weight=0.2)

crew = Crew(
    agents=[...], tasks=[...],
    knowledge_sources=[docs],     # Pre-loaded reference
    memory=memory,                # Runtime learning
)
```

---

## Pattern Catalog

### Multi-Project Team

```python
memory = Memory()
memory.remember("Using microservices architecture", scope="/project/alpha/architecture")
memory.remember("GraphQL API for client apps", scope="/project/beta/api")

# Recall across all projects
memory.recall("API design decisions")

# Or within a specific project
memory.recall("API design", scope="/project/beta")
```

### Per-Agent Private Context with Shared Knowledge

```python
memory = Memory()

# Researcher has private findings
researcher_memory = memory.scope("/agent/researcher")

# Writer reads from its own scope AND shared company knowledge (read-only)
writer_view = memory.slice(
    scopes=["/agent/writer", "/company/knowledge"],
    read_only=True,
)
```

### Customer Support Isolation

```python
memory = Memory()

# Per-customer context
memory.remember("Prefers email communication", scope="/customer/acme-corp")
memory.remember("On enterprise plan, 50 seats", scope="/customer/acme-corp")

# Shared product docs accessible to all
memory.remember("Rate limit is 1000 req/min on enterprise plan", scope="/product/docs")
```

### Multi-Agent Knowledge Specialization

```python
sales_knowledge = StringKnowledgeSource(content="Sales procedures and pricing")
tech_knowledge = StringKnowledgeSource(content="Technical documentation")

sales_agent = Agent(role="Sales Rep", ..., knowledge_sources=[sales_knowledge],
    embedder={"provider": "openai", "config": {"model": "text-embedding-3-small"}})

tech_agent = Agent(role="Tech Expert", ..., knowledge_sources=[tech_knowledge],
    embedder={"provider": "ollama", "config": {"model": "mxbai-embed-large"}})

crew = Crew(
    agents=[sales_agent, tech_agent], tasks=[...],
    embedder={"provider": "openai", "config": {"model": "text-embedding-3-small"}},
)
# Each agent gets only their specific knowledge; each can use different embedders
```

### Fully Local / Private Operation

```python
memory = Memory(
    llm="ollama/llama3.2",
    embedder={"provider": "ollama", "config": {"model_name": "mxbai-embed-large"}},
)
# No data leaves your machine
```

---

## Best Practices

### Memory Best Practices

1. **Start flat, let the LLM organize scope** -- do not pre-design a deep hierarchy.
2. **Use `depth="shallow"` for routine context** -- reserve `depth="deep"` for complex multi-scope queries.
3. **Tune scoring weights to your use case** -- sprint work needs high `recency_weight`; a knowledge base needs high `importance_weight`.
4. **Call `close()` in standalone scripts** -- crews handle this automatically, but scripts need explicit cleanup.
5. **Use `extract_memories()` before `remember()`** -- store atomic facts, not large blobs.
6. **Monitor via events** -- listen for `MemoryQueryCompletedEvent` to track recall latency.

### Knowledge Best Practices

1. **Place files in `knowledge/` at the project root** with relative paths.
2. **Use agent-level knowledge for role-specific info** and crew-level for shared info.
3. **Set `CREWAI_STORAGE_DIR`** in production for predictable storage locations.
4. **Match embedder to LLM provider** when possible (e.g., VoyageAI with Claude).
5. **Initialize knowledge directly** for large sources to avoid re-embedding on every `kickoff()` (see `knowledge` param instead of `knowledge_sources`).
6. **Reset knowledge after changing embedders** -- dimension mismatches cause errors: `crew.reset_memories(command_type='knowledge')`.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Memory not persisting | Storage path not writable | Pass `storage="./your_path"` or set `CREWAI_STORAGE_DIR` |
| Slow recall | Using `depth="deep"` for simple queries | Use `depth="shallow"` or increase `query_analysis_threshold` |
| LLM analysis errors in logs | API key / rate limit issues | Memory still works with defaults; fix keys for full analysis |
| Background save errors | LLM or embedder connection issues | Check logs; errors emitted as `MemorySaveFailedEvent` |
| Knowledge "file not found" | File not in `knowledge/` directory | Move files to `./knowledge/` and use relative paths |
| "Embedding dimension mismatch" | Switched embedder providers | Reset: `crew.reset_memories(command_type='knowledge')` |
| ChromaDB permission denied | Storage directory permissions | `chmod -R 755 ~/.local/share/CrewAI/` |
| Knowledge not persisting between runs | Inconsistent `CREWAI_STORAGE_DIR` | Verify with `db_storage_path()` |

---

## Resources

- **references/embedder-providers.md**: Full provider reference table with config examples and Memory configuration reference
- CrewAI Memory docs: https://docs.crewai.com/concepts/memory
- CrewAI Knowledge docs: https://docs.crewai.com/concepts/knowledge
