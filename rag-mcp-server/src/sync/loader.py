"""Document Loader - Load documents from various sources.

Supports loading from:
- Git repositories (clone/pull)
- Local file paths
- File formats: Markdown, YAML, JSON, plain text
"""

import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from fnmatch import fnmatch

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Document:
    """Represents a loaded document."""

    content: str
    source: str  # File path or URL
    title: str = ""
    file_type: str = ""  # md, yaml, json, txt
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_modified: Optional[datetime] = None

    def __post_init__(self):
        """Set defaults after init."""
        if not self.title and self.source:
            # Extract title from filename
            self.title = Path(self.source).stem.replace("-", " ").replace("_", " ").title()

        if not self.file_type and self.source:
            # Extract file type from extension
            ext = Path(self.source).suffix.lower()
            self.file_type = ext.lstrip(".")


class DocumentLoader:
    """Load documents from git repos or local paths.

    Example:
        loader = DocumentLoader()

        # Load from git repo
        docs = loader.load_git_repo(
            url="https://github.com/org/playbooks.git",
            branch="main",
            patterns=["docs/**/*.md"]
        )

        # Load from local path
        docs = loader.load_local_path(
            path="/path/to/docs",
            patterns=["**/*.md", "**/*.yaml"]
        )
    """

    SUPPORTED_EXTENSIONS = {".md", ".markdown", ".yaml", ".yml", ".json", ".txt", ".rst"}

    def __init__(self, temp_dir: Optional[str] = None):
        """Initialize loader.

        Args:
            temp_dir: Directory for git clones (default: system temp)
        """
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self._git_cache: Dict[str, Path] = {}

    def load_git_repo(
        self,
        url: str,
        branch: str = "main",
        patterns: Optional[List[str]] = None,
        shallow: bool = True,
    ) -> List[Document]:
        """Load documents from a git repository.

        Args:
            url: Git repository URL
            branch: Branch to checkout
            patterns: Glob patterns to match files (e.g., ["docs/**/*.md"])
            shallow: Use shallow clone for speed (default: True)

        Returns:
            List of Document objects
        """
        try:
            import git
        except ImportError:
            raise ImportError("GitPython required: pip install gitpython")

        patterns = patterns or ["**/*.md"]

        # Generate cache key from URL
        cache_key = url.replace("/", "_").replace(":", "_")
        clone_path = Path(self.temp_dir) / "rag-mcp-repos" / cache_key

        try:
            if clone_path.exists():
                # Pull latest changes
                logger.info(f"Updating existing clone: {url}")
                repo = git.Repo(clone_path)
                repo.remotes.origin.fetch()
                repo.git.checkout(branch)
                repo.git.pull("origin", branch)
            else:
                # Fresh clone
                logger.info(f"Cloning repository: {url}")
                clone_path.parent.mkdir(parents=True, exist_ok=True)
                clone_kwargs = {"branch": branch}
                if shallow:
                    clone_kwargs["depth"] = 1
                repo = git.Repo.clone_from(url, clone_path, **clone_kwargs)

            self._git_cache[url] = clone_path

            # Load matching files
            return self.load_local_path(str(clone_path), patterns)

        except git.GitCommandError as e:
            logger.error(f"Git error for {url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load git repo {url}: {e}")
            raise

    def load_local_path(
        self,
        path: str,
        patterns: Optional[List[str]] = None,
        recursive: bool = True,
    ) -> List[Document]:
        """Load documents from a local directory.

        Args:
            path: Local directory path
            patterns: Glob patterns to match (e.g., ["**/*.md"])
            recursive: Search subdirectories (default: True)

        Returns:
            List of Document objects
        """
        patterns = patterns or ["**/*"]
        base_path = Path(path)

        if not base_path.exists():
            logger.warning(f"Path does not exist: {path}")
            return []

        if base_path.is_file():
            # Single file
            doc = self._load_file(base_path)
            return [doc] if doc else []

        documents = []
        seen_files = set()

        for pattern in patterns:
            if recursive and "**" not in pattern:
                pattern = f"**/{pattern}"

            for file_path in base_path.glob(pattern):
                if file_path.is_file() and file_path not in seen_files:
                    seen_files.add(file_path)

                    if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                        doc = self._load_file(file_path, base_path)
                        if doc:
                            documents.append(doc)

        logger.info(f"Loaded {len(documents)} documents from {path}")
        return documents

    def load_from_config(self, config: Dict[str, Any]) -> List[Document]:
        """Load documents based on sync configuration.

        Args:
            config: Source configuration dict with type, url/path, patterns

        Returns:
            List of Document objects

        Example config:
            {
                "name": "oncall-playbooks",
                "type": "git",
                "url": "https://github.com/org/playbooks.git",
                "branch": "main",
                "patterns": ["docs/**/*.md"]
            }
        """
        source_type = config.get("type", "local")
        name = config.get("name", "unknown")

        logger.info(f"Loading source: {name} (type={source_type})")

        if source_type == "git":
            return self.load_git_repo(
                url=config["url"],
                branch=config.get("branch", "main"),
                patterns=config.get("patterns"),
                shallow=config.get("shallow", True),
            )
        elif source_type == "local":
            return self.load_local_path(
                path=config["path"],
                patterns=config.get("patterns"),
                recursive=config.get("recursive", True),
            )
        else:
            logger.warning(f"Unknown source type: {source_type}")
            return []

    def _load_file(
        self,
        file_path: Path,
        base_path: Optional[Path] = None,
    ) -> Optional[Document]:
        """Load a single file.

        Args:
            file_path: Path to the file
            base_path: Base path for relative source calculation

        Returns:
            Document object or None if failed
        """
        try:
            # Read file content
            content = file_path.read_text(encoding="utf-8")

            # Calculate relative source path
            if base_path:
                try:
                    source = str(file_path.relative_to(base_path))
                except ValueError:
                    source = str(file_path)
            else:
                source = str(file_path)

            # Get file stats
            stat = file_path.stat()
            last_modified = datetime.fromtimestamp(stat.st_mtime)

            # Extract metadata from frontmatter (for markdown)
            metadata = {}
            title = ""
            if file_path.suffix.lower() in {".md", ".markdown"}:
                content, metadata = self._parse_frontmatter(content)
                title = metadata.pop("title", "")

            return Document(
                content=content,
                source=source,
                title=title,
                metadata=metadata,
                last_modified=last_modified,
            )

        except UnicodeDecodeError:
            logger.warning(f"Skipping binary file: {file_path}")
            return None
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return None

    def _parse_frontmatter(self, content: str) -> tuple[str, Dict[str, Any]]:
        """Parse YAML frontmatter from markdown content.

        Args:
            content: Raw markdown content

        Returns:
            Tuple of (content without frontmatter, metadata dict)
        """
        if not content.startswith("---"):
            return content, {}

        try:
            # Find end of frontmatter
            end_idx = content.find("---", 3)
            if end_idx == -1:
                return content, {}

            # Parse YAML
            frontmatter = content[3:end_idx].strip()
            metadata = yaml.safe_load(frontmatter) or {}

            # Return content without frontmatter
            remaining = content[end_idx + 3:].strip()
            return remaining, metadata

        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse frontmatter: {e}")
            return content, {}

    def iter_documents(
        self,
        sources: List[Dict[str, Any]],
    ) -> Iterator[Document]:
        """Iterate over documents from multiple sources.

        Args:
            sources: List of source configurations

        Yields:
            Document objects
        """
        for source in sources:
            try:
                docs = self.load_from_config(source)
                yield from docs
            except Exception as e:
                logger.error(f"Failed to load source {source.get('name')}: {e}")
                continue
