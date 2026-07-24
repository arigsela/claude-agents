
"""Shared A2A protocol utilities.

Extracted from duplicated code across executor modules.
"""

from __future__ import annotations

from a2a.types import TextPart


def extract_user_input(message, default: str = "Hello") -> str:
    """Extract the user's text input from an A2A message.

    Handles both direct TextPart instances and wrapped Part objects
    (where the TextPart is nested under .root).
    """
    if message and message.parts:
        text_parts = []
        for part in message.parts:
            if isinstance(part, TextPart):
                text_parts.append(part.text)
            elif hasattr(part, "root") and isinstance(part.root, TextPart):
                text_parts.append(part.root.text)
        if text_parts:
            return " ".join(text_parts)
    return default

