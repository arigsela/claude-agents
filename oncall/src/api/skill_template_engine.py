"""
Skill Template Engine for OnCall Agent
Handles parsing and rendering of Jinja2 templates from skill files.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from jinja2 import Environment, Template, TemplateSyntaxError, UndefinedError, select_autoescape
from jinja2.sandbox import SandboxedEnvironment

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_OUTPUT_DIR = Path("/tmp/oncall-reports")
MAX_TEMPLATE_SIZE_KB = 500
MAX_OUTPUT_SIZE_KB = 2000

# Template block pattern: ```template:template_name
TEMPLATE_BLOCK_PATTERN = re.compile(
    r"```template:(\w+)\s*\n(.*?)```",
    re.DOTALL | re.MULTILINE
)


class SkillTemplateEngine:
    """Engine for parsing and rendering skill templates."""

    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize the template engine.

        Args:
            output_dir: Directory to save rendered documents (default: /tmp/oncall-reports)
        """
        self.output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Use sandboxed Jinja2 environment for security
        self.jinja_env = SandboxedEnvironment(
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        logger.info(f"SkillTemplateEngine initialized with output_dir: {self.output_dir}")

    def parse_skill_templates(self, skill_path: Path) -> Dict[str, str]:
        """
        Extract template blocks from a skill file.

        Template blocks are defined as:
        ```template:template_name
        ... template content ...
        ```

        Args:
            skill_path: Path to the SKILL.md file

        Returns:
            Dictionary mapping template names to template content

        Raises:
            FileNotFoundError: If skill file doesn't exist
            ValueError: If skill file is too large
        """
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill file not found: {skill_path}")

        # Check file size
        file_size_kb = skill_path.stat().st_size / 1024
        if file_size_kb > MAX_TEMPLATE_SIZE_KB:
            raise ValueError(
                f"Skill file too large: {file_size_kb:.1f}KB "
                f"(max: {MAX_TEMPLATE_SIZE_KB}KB)"
            )

        # Read skill content
        content = skill_path.read_text()

        # Extract template blocks
        templates = {}
        for match in TEMPLATE_BLOCK_PATTERN.finditer(content):
            template_name = match.group(1)
            template_content = match.group(2).strip()

            if template_name in templates:
                logger.warning(
                    f"Duplicate template '{template_name}' in {skill_path.name}. "
                    "Using the last occurrence."
                )

            templates[template_name] = template_content
            logger.debug(f"Found template '{template_name}' ({len(template_content)} chars)")

        if templates:
            logger.info(
                f"Parsed {len(templates)} template(s) from {skill_path.name}: "
                f"{', '.join(templates.keys())}"
            )
        else:
            logger.debug(f"No templates found in {skill_path.name}")

        return templates

    def validate_template_syntax(self, template_content: str) -> tuple[bool, Optional[str]]:
        """
        Validate Jinja2 template syntax.

        Args:
            template_content: Template string to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            self.jinja_env.from_string(template_content)
            return True, None
        except TemplateSyntaxError as e:
            error_msg = f"Template syntax error at line {e.lineno}: {e.message}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Template validation error: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    def render_template(
        self,
        template_content: str,
        data: Dict[str, Any],
        strict: bool = False
    ) -> str:
        """
        Render a Jinja2 template with provided data.

        Args:
            template_content: Jinja2 template string
            data: Dictionary of variables to populate the template
            strict: If True, raise error on undefined variables

        Returns:
            Rendered template as string

        Raises:
            TemplateSyntaxError: If template has syntax errors
            UndefinedError: If strict=True and template has undefined variables
            ValueError: If rendered output exceeds size limit
        """
        try:
            # Create template
            template = self.jinja_env.from_string(template_content)

            # Set undefined behavior
            if strict:
                template.environment.undefined = 'StrictUndefined'

            # Render template
            rendered = template.render(data)

            # Check output size
            output_size_kb = len(rendered.encode('utf-8')) / 1024
            if output_size_kb > MAX_OUTPUT_SIZE_KB:
                raise ValueError(
                    f"Rendered template too large: {output_size_kb:.1f}KB "
                    f"(max: {MAX_OUTPUT_SIZE_KB}KB)"
                )

            logger.info(
                f"Rendered template successfully "
                f"({len(template_content)} chars template → {len(rendered)} chars output)"
            )

            return rendered

        except UndefinedError as e:
            logger.error(f"Template rendering error (undefined variable): {e}")
            raise
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error at line {e.lineno}: {e.message}")
            raise
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            raise

    def save_document(
        self,
        content: str,
        filename: str,
        output_dir: Optional[Path] = None
    ) -> Path:
        """
        Save rendered document to filesystem.

        Args:
            content: Rendered template content
            filename: Output filename (e.g., "incident-2025-10-23.md")
            output_dir: Optional custom output directory (uses default if not provided)

        Returns:
            Path to saved file

        Raises:
            IOError: If file cannot be written
        """
        save_dir = output_dir or self.output_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        file_path = save_dir / filename

        try:
            file_path.write_text(content, encoding='utf-8')
            logger.info(f"Saved document to {file_path} ({len(content)} chars)")
            return file_path
        except Exception as e:
            logger.error(f"Failed to save document to {file_path}: {e}")
            raise IOError(f"Failed to save document: {e}")

    def get_available_templates(self, skill_name: str, skills_dir: Path) -> List[str]:
        """
        Get list of templates available in a skill.

        Args:
            skill_name: Name of the skill
            skills_dir: Directory containing skills (e.g., .claude/skills/)

        Returns:
            List of template names

        Raises:
            FileNotFoundError: If skill file doesn't exist
        """
        skill_path = skills_dir / skill_name / "SKILL.md"
        if not skill_path.exists():
            skill_path = skills_dir / f"{skill_name}.md"

        if not skill_path.exists():
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        templates = self.parse_skill_templates(skill_path)
        return list(templates.keys())

    def generate_filename(
        self,
        template_name: str,
        data: Dict[str, Any],
        extension: str = "md"
    ) -> str:
        """
        Generate a unique filename for a rendered document.

        Args:
            template_name: Name of the template used
            data: Data used to render (may contain identifiers)
            extension: File extension (default: "md")

        Returns:
            Filename string (e.g., "incident-2025-10-23-143052.md")
        """
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")

        # Try to extract identifiers from data
        identifiers = []

        # Common identifier fields
        for key in ['service_name', 'pod_name', 'cluster_name', 'namespace']:
            if key in data and data[key]:
                identifiers.append(str(data[key]).replace('/', '-'))

        # Build filename
        if identifiers:
            filename = f"{template_name}-{'-'.join(identifiers)}-{timestamp}.{extension}"
        else:
            filename = f"{template_name}-{timestamp}.{extension}"

        # Sanitize filename
        filename = re.sub(r'[^\w\-\.]', '-', filename)

        return filename


def create_template_engine(output_dir: Optional[str] = None) -> SkillTemplateEngine:
    """
    Factory function to create a template engine instance.

    Args:
        output_dir: Optional output directory path as string

    Returns:
        SkillTemplateEngine instance
    """
    output_path = Path(output_dir) if output_dir else None
    return SkillTemplateEngine(output_dir=output_path)
