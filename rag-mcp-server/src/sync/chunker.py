"""Document Chunker - Split documents into searchable chunks.

Supports chunking strategies:
- Header-based: Split on markdown headers (##, ###)
- Paragraph-based: Split on double newlines
- Fixed-size: Split by character/token count with overlap
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.sync.loader import Document

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Represents a document chunk."""

    content: str
    source: str  # Original document source
    chunk_index: int  # Position in document
    title: str = ""  # Section title or document title
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        """Return character count."""
        return len(self.content)

    @property
    def word_count(self) -> int:
        """Return approximate word count."""
        return len(self.content.split())


class DocumentChunker:
    """Split documents into chunks for vector indexing.

    Strategies:
    - "header": Split on markdown headers, preserving hierarchy
    - "paragraph": Split on paragraph breaks (double newlines)
    - "fixed": Split by character count with overlap

    Example:
        chunker = DocumentChunker(strategy="header", max_chunk_size=1000)
        chunks = chunker.chunk_document(document)
    """

    def __init__(
        self,
        strategy: str = "header",
        max_chunk_size: int = 1000,
        min_chunk_size: int = 100,
        overlap: int = 100,
        preserve_sentences: bool = True,
    ):
        """Initialize chunker.

        Args:
            strategy: Chunking strategy ("header", "paragraph", "fixed")
            max_chunk_size: Maximum chunk size in characters
            min_chunk_size: Minimum chunk size (smaller chunks merged)
            overlap: Character overlap between chunks (for fixed strategy)
            preserve_sentences: Try to break at sentence boundaries
        """
        self.strategy = strategy
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self.overlap = overlap
        self.preserve_sentences = preserve_sentences

    def chunk_document(self, document: Document) -> List[Chunk]:
        """Split a document into chunks.

        Args:
            document: Document to chunk

        Returns:
            List of Chunk objects
        """
        if not document.content.strip():
            return []

        if self.strategy == "header":
            chunks = self._chunk_by_headers(document)
        elif self.strategy == "paragraph":
            chunks = self._chunk_by_paragraphs(document)
        elif self.strategy == "fixed":
            chunks = self._chunk_fixed_size(document)
        else:
            logger.warning(f"Unknown strategy {self.strategy}, using header")
            chunks = self._chunk_by_headers(document)

        # Post-process: merge small chunks, split large ones
        chunks = self._post_process_chunks(chunks, document)

        logger.debug(
            f"Chunked '{document.source}': {len(chunks)} chunks, "
            f"avg size: {sum(c.char_count for c in chunks) // max(len(chunks), 1)} chars"
        )

        return chunks

    def chunk_documents(self, documents: List[Document]) -> List[Chunk]:
        """Chunk multiple documents.

        Args:
            documents: List of documents to chunk

        Returns:
            List of all chunks from all documents
        """
        all_chunks = []
        for doc in documents:
            chunks = self.chunk_document(doc)
            all_chunks.extend(chunks)

        logger.info(f"Chunked {len(documents)} documents into {len(all_chunks)} chunks")
        return all_chunks

    def _chunk_by_headers(self, document: Document) -> List[Chunk]:
        """Split on markdown headers.

        Preserves header hierarchy by keeping parent headers in context.
        """
        content = document.content
        chunks = []

        # Regex to match markdown headers (## or ###)
        header_pattern = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)

        # Find all headers
        headers = list(header_pattern.finditer(content))

        if not headers:
            # No headers, treat as single chunk
            return [
                Chunk(
                    content=content.strip(),
                    source=document.source,
                    chunk_index=0,
                    title=document.title,
                    metadata=document.metadata.copy(),
                )
            ]

        # Split content by headers
        for i, match in enumerate(headers):
            header_level = len(match.group(1))
            header_text = match.group(2).strip()

            # Get content between this header and next
            start = match.end()
            end = headers[i + 1].start() if i + 1 < len(headers) else len(content)

            section_content = content[start:end].strip()

            if section_content:
                # Include header in content for context
                full_content = f"## {header_text}\n\n{section_content}"

                chunks.append(
                    Chunk(
                        content=full_content,
                        source=document.source,
                        chunk_index=i,
                        title=header_text,
                        metadata={
                            **document.metadata,
                            "header_level": header_level,
                            "section": header_text,
                        },
                    )
                )

        # Handle content before first header
        first_header_start = headers[0].start() if headers else len(content)
        preamble = content[:first_header_start].strip()

        if preamble and len(preamble) > self.min_chunk_size:
            chunks.insert(
                0,
                Chunk(
                    content=preamble,
                    source=document.source,
                    chunk_index=0,
                    title=document.title or "Introduction",
                    metadata={**document.metadata, "section": "preamble"},
                ),
            )
            # Reindex remaining chunks
            for i, chunk in enumerate(chunks[1:], 1):
                chunk.chunk_index = i

        return chunks

    def _chunk_by_paragraphs(self, document: Document) -> List[Chunk]:
        """Split on paragraph breaks (double newlines)."""
        paragraphs = re.split(r"\n\s*\n", document.content)
        chunks = []

        current_chunk = []
        current_size = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_size = len(para)

            # If adding this paragraph exceeds max size, save current chunk
            if current_size + para_size > self.max_chunk_size and current_chunk:
                chunks.append(
                    Chunk(
                        content="\n\n".join(current_chunk),
                        source=document.source,
                        chunk_index=len(chunks),
                        title=document.title,
                        metadata=document.metadata.copy(),
                    )
                )
                current_chunk = []
                current_size = 0

            current_chunk.append(para)
            current_size += para_size

        # Don't forget last chunk
        if current_chunk:
            chunks.append(
                Chunk(
                    content="\n\n".join(current_chunk),
                    source=document.source,
                    chunk_index=len(chunks),
                    title=document.title,
                    metadata=document.metadata.copy(),
                )
            )

        return chunks

    def _chunk_fixed_size(self, document: Document) -> List[Chunk]:
        """Split by fixed character count with overlap."""
        content = document.content
        chunks = []

        start = 0
        chunk_index = 0

        while start < len(content):
            end = start + self.max_chunk_size

            # Try to find sentence boundary
            if self.preserve_sentences and end < len(content):
                # Look for sentence ending near the boundary
                search_start = max(start + self.max_chunk_size - 200, start)
                search_end = min(start + self.max_chunk_size + 100, len(content))
                search_text = content[search_start:search_end]

                # Find last sentence boundary
                for pattern in [". ", ".\n", "? ", "!\n"]:
                    last_idx = search_text.rfind(pattern)
                    if last_idx != -1:
                        end = search_start + last_idx + len(pattern)
                        break

            chunk_content = content[start:end].strip()

            if chunk_content:
                chunks.append(
                    Chunk(
                        content=chunk_content,
                        source=document.source,
                        chunk_index=chunk_index,
                        title=document.title,
                        metadata=document.metadata.copy(),
                    )
                )
                chunk_index += 1

            # Move start with overlap
            start = end - self.overlap if end < len(content) else len(content)

        return chunks

    def _post_process_chunks(
        self,
        chunks: List[Chunk],
        document: Document,
    ) -> List[Chunk]:
        """Merge small chunks, split large ones."""
        if not chunks:
            return chunks

        processed = []

        for chunk in chunks:
            # Split oversized chunks
            if chunk.char_count > self.max_chunk_size * 1.5:
                # Create temporary document and use fixed chunking
                temp_doc = Document(
                    content=chunk.content,
                    source=chunk.source,
                    title=chunk.title,
                    metadata=chunk.metadata,
                )
                sub_chunks = self._chunk_fixed_size(temp_doc)

                # Update indices
                base_idx = chunk.chunk_index
                for i, sub in enumerate(sub_chunks):
                    sub.chunk_index = base_idx + i
                    sub.metadata["sub_chunk"] = i
                    processed.append(sub)
            else:
                processed.append(chunk)

        # Merge very small consecutive chunks
        merged = []
        buffer_chunk = None

        for chunk in processed:
            if buffer_chunk is None:
                buffer_chunk = chunk
            elif buffer_chunk.char_count + chunk.char_count < self.min_chunk_size * 2:
                # Merge chunks
                buffer_chunk = Chunk(
                    content=f"{buffer_chunk.content}\n\n{chunk.content}",
                    source=buffer_chunk.source,
                    chunk_index=buffer_chunk.chunk_index,
                    title=buffer_chunk.title,
                    metadata=buffer_chunk.metadata,
                )
            else:
                merged.append(buffer_chunk)
                buffer_chunk = chunk

        if buffer_chunk:
            merged.append(buffer_chunk)

        # Reindex
        for i, chunk in enumerate(merged):
            chunk.chunk_index = i

        return merged
