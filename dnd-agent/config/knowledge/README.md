# Knowledge Sources

This directory contains knowledge files that the agent uses for RAG
(Retrieval-Augmented Generation). When the agent receives a query, it
searches these files for relevant context and includes it in its reasoning.

## Supported File Types

- `.txt` — Plain text (architecture docs, runbooks, guides)
- `.json` — Structured data (API specs, config references)
- `.csv` — Tabular data (service catalogs, metrics)
- `.pdf` — Documents (design docs, RFCs)

## How to Add Knowledge

1. Place your files in this directory
2. Update the agent's tool in `src/dnd_character_agent/tools.py` to read from these files
3. Rebuild the Docker image (`docker-compose up --build`)

## Example Knowledge Files

For a service knowledge agent, you might add:

- `api-docs.json` — OpenAPI spec or endpoint documentation
- `architecture.txt` — System architecture description
- `deployment-guide.txt` — How the service is deployed
- `troubleshooting.txt` — Common issues and solutions
- `data-model.txt` — Database schema and relationships

## Using CrewAI Knowledge Sources

```python
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource

knowledge_source = TextFileKnowledgeSource(
    file_paths=["config/knowledge/architecture.txt"]
)

agent = Agent(
    role="...",
    knowledge_sources=[knowledge_source],
    ...
)
```
