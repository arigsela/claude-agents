"""Tests for parsing subagent outputs."""

import pytest

from src.utils.parsers import (
    extract_json_from_markdown,
    parse_k8s_analyzer_output,
)


class TestParseK8sAnalyzerOutput:
    """Tests for k8s-analyzer markdown parsing."""

    def test_parse_critical_issues(self):
        """Test parsing critical issues section."""
        markdown = """## K8s Health Analysis Report

### Critical Issues (P0 - Immediate Action Required)

- **Service**: chores-tracker-backend
  - **Issue**: 2/2 pods in CrashLoopBackOff
  - **Namespace**: chores-tracker-backend

### High Priority Issues (P1 - Monitor Closely)

- **Service**: mysql
  - **Issue**: Single replica with high memory usage
  - **Namespace**: mysql
"""
        findings = parse_k8s_analyzer_output(markdown)

        assert len(findings) >= 1
        assert any(f["severity"] == "critical" for f in findings)
        assert any(f["priority"] == "P0" for f in findings)

    def test_parse_high_priority_issues(self):
        """Test parsing high priority issues."""
        markdown = """### High Priority Issues (P1 - Monitor Closely)

- **Service**: postgresql
  - **Issue**: High memory usage, 85% utilized
  - **Namespace**: postgresql
"""
        findings = parse_k8s_analyzer_output(markdown)

        assert len(findings) >= 1
        assert any(f["severity"] == "high" for f in findings)
        assert any(f["priority"] == "P1" for f in findings)

    def test_parse_warnings(self):
        """Test parsing warnings section."""
        markdown = """### Warnings (P2/P3 - Informational)

- **Service**: vault
  - **Issue**: Pod restarted 1 time in last hour
  - **Namespace**: vault
"""
        findings = parse_k8s_analyzer_output(markdown)

        assert len(findings) >= 1
        assert any(f["severity"] == "warning" for f in findings)
        assert any(f["priority"] == "P2/P3" for f in findings)

    def test_parse_empty_response(self):
        """Test parsing empty/healthy response."""
        markdown = """## K8s Health Analysis Report

### All Clear (Healthy Services)

- ✅ **chores-tracker-backend**: All pods running
- ✅ **mysql**: Running normally
- ✅ **nginx-ingress**: All components healthy
"""
        findings = parse_k8s_analyzer_output(markdown)

        # Should return empty list for healthy cluster
        # (All Clear section doesn't have issues)
        assert isinstance(findings, list)

    def test_parse_multiple_issues(self):
        """Test parsing multiple issues."""
        markdown = """### Critical Issues (P0 - Immediate Action Required)

- **Service**: chores-tracker-backend
  - **Issue**: 2/2 pods in CrashLoopBackOff

- **Service**: mysql
  - **Issue**: Pod evicted due to memory pressure

### High Priority Issues (P1 - Monitor Closely)

- **Service**: postgresql
  - **Issue**: Connection pool exhausted
"""
        findings = parse_k8s_analyzer_output(markdown)

        assert len(findings) >= 2
        critical_count = sum(1 for f in findings if f["severity"] == "critical")
        high_count = sum(1 for f in findings if f["severity"] == "high")
        assert critical_count >= 1
        assert high_count >= 1


class TestExtractJsonFromMarkdown:
    """Tests for JSON extraction from markdown."""

    def test_extract_json_code_block(self):
        """Test extracting JSON from markdown code block."""
        markdown = """
## Analysis

```json
{"severity": "critical", "service": "chores-tracker-backend", "issues": 2}
```

Some text after the JSON block.
"""
        result = extract_json_from_markdown(markdown)

        assert result["severity"] == "critical"
        assert result["service"] == "chores-tracker-backend"
        assert result["issues"] == 2

    def test_extract_json_without_json_label(self):
        """Test extracting JSON from code block without json label."""
        markdown = """
```
{"notification_required": true, "sev_level": "SEV-1"}
```
"""
        result = extract_json_from_markdown(markdown)

        assert result["notification_required"] is True
        assert result["sev_level"] == "SEV-1"

    def test_no_json_found(self):
        """Test when no JSON is found in markdown."""
        markdown = """
## Some Analysis

This is just text without any JSON.
"""
        result = extract_json_from_markdown(markdown)

        assert result == {}

    def test_invalid_json_in_code_block(self):
        """Test handling invalid JSON in code block."""
        markdown = """
```json
{ this is not valid json }
```
"""
        result = extract_json_from_markdown(markdown)

        # Should return empty dict on parse error
        assert result == {}

    def test_extract_nested_json(self):
        """Test extracting nested JSON structure."""
        markdown = """
Analysis result:

```json
{
  "status": "critical",
  "findings": [
    {"service": "mysql", "issue": "high_memory"}
  ],
  "recommendation": "investigate"
}
```
"""
        result = extract_json_from_markdown(markdown)

        assert result["status"] == "critical"
        assert len(result["findings"]) == 1
        assert result["findings"][0]["service"] == "mysql"
