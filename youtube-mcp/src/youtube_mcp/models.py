"""Pydantic models for YouTube MCP server."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """A single segment of a transcript."""

    text: str
    start: float
    duration: float


class TranscriptResult(BaseModel):
    """Result from get_transcript tool."""

    video_id: str
    transcript: str
    segments: list[TranscriptSegment] | None = None
    language: str


class VideoInfo(BaseModel):
    """Video metadata."""

    video_id: str
    title: str | None = None
    channel: str | None = None
    duration: int | None = None  # seconds
    url: str


class SaveSummaryInput(BaseModel):
    """Input for save_summary tool."""

    title: Annotated[str, Field(description="Title for the summary document")]
    content: Annotated[str, Field(description="Markdown content of the summary")]
    video_id: Annotated[str, Field(description="YouTube video ID")]
    video_url: Annotated[
        str | None, Field(description="Full YouTube URL", default=None)
    ]
    tags: Annotated[
        list[str] | None, Field(description="Tags for categorization", default=None)
    ]


class SummaryMetadata(BaseModel):
    """Metadata for a saved summary."""

    filename: str
    title: str
    video_id: str
    created_at: datetime
    tags: list[str]
