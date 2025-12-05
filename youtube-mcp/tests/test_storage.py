"""Tests for storage tools."""

import pytest

from youtube_mcp.tools.storage import sanitize_filename


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_simple_title(self):
        """Test simple title conversion."""
        assert sanitize_filename("Hello World") == "hello-world"

    def test_special_characters_removed(self):
        """Test that special characters are removed."""
        assert sanitize_filename("Video: The Best Tutorial (2024)!") == "video-the-best-tutorial-2024"

    def test_extra_spaces_collapsed(self):
        """Test that multiple spaces become single hyphen."""
        assert sanitize_filename("  Extra   Spaces  ") == "extra-spaces"

    def test_hyphens_preserved(self):
        """Test that hyphens are preserved."""
        assert sanitize_filename("step-by-step guide") == "step-by-step-guide"

    def test_multiple_hyphens_collapsed(self):
        """Test that multiple hyphens become single hyphen."""
        assert sanitize_filename("hello---world") == "hello-world"

    def test_length_limit(self):
        """Test that output is limited to 50 characters."""
        long_title = "a" * 100
        result = sanitize_filename(long_title)
        assert len(result) <= 50

    def test_unicode_preserved(self):
        """Test that unicode word characters are preserved."""
        # Python's \w matches unicode letters, so they're kept
        assert sanitize_filename("Hello 世界") == "hello-世界"

    def test_numbers_preserved(self):
        """Test that numbers are preserved."""
        assert sanitize_filename("Tutorial Part 3") == "tutorial-part-3"

    def test_underscores_preserved(self):
        """Test that underscores are preserved."""
        assert sanitize_filename("my_video_title") == "my_video_title"

    def test_empty_after_sanitize(self):
        """Test title that becomes empty after sanitizing."""
        result = sanitize_filename("!@#$%")
        assert result == ""

    def test_leading_trailing_hyphens_stripped(self):
        """Test that leading/trailing hyphens are removed."""
        assert sanitize_filename("-hello-world-") == "hello-world"
