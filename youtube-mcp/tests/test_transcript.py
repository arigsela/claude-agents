"""Tests for transcript tools."""

import pytest

from youtube_mcp.tools.transcript import extract_video_id


class TestExtractVideoId:
    """Tests for extract_video_id function."""

    def test_full_youtube_url(self):
        """Test extraction from standard YouTube URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_short_url(self):
        """Test extraction from youtu.be short URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_embed_url(self):
        """Test extraction from embed URL."""
        url = "https://youtube.com/embed/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_v_url(self):
        """Test extraction from /v/ URL format."""
        url = "https://www.youtube.com/v/dQw4w9WgXcQ"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_direct_video_id(self):
        """Test direct video ID input."""
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_url_with_extra_params(self):
        """Test URL with additional parameters."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120&list=PLxyz"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_url_with_timestamp(self):
        """Test URL with timestamp parameter."""
        url = "https://youtu.be/dQw4w9WgXcQ?t=42"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_video_id_with_hyphen(self):
        """Test video ID containing hyphen."""
        assert extract_video_id("abc-def_123") == "abc-def_123"

    def test_video_id_with_underscore(self):
        """Test video ID containing underscore."""
        assert extract_video_id("abc_def-123") == "abc_def-123"

    def test_invalid_url_raises_error(self):
        """Test that invalid input raises ValueError."""
        with pytest.raises(ValueError, match="Could not extract video ID"):
            extract_video_id("not-a-valid-id")

    def test_empty_string_raises_error(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="Could not extract video ID"):
            extract_video_id("")

    def test_too_short_id_raises_error(self):
        """Test that ID shorter than 11 chars raises ValueError."""
        with pytest.raises(ValueError, match="Could not extract video ID"):
            extract_video_id("abc123")

    def test_too_long_id_raises_error(self):
        """Test that ID longer than 11 chars (without URL) raises ValueError."""
        with pytest.raises(ValueError, match="Could not extract video ID"):
            extract_video_id("dQw4w9WgXcQextra")
