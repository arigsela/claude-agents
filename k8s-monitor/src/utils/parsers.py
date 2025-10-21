"""Parsers for subagent markdown output."""

import json
import re
from typing import Any

from src.models import Finding


def parse_k8s_analyzer_output(response: str) -> list[Finding]:
    """Parse k8s-analyzer subagent output (markdown format).

    The k8s-analyzer returns structured markdown with sections:
    - Critical Issues (P0) / 🔴 Critical Issue
    - High Priority Issues (P1) / ⚠️ Other Issues
    - Warnings (P2/P3)
    - All Clear (if healthy)
    - Key Findings (generic findings section)

    Args:
        response: Raw markdown response from k8s-analyzer

    Returns:
        List of Finding objects parsed from markdown
    """
    findings_dicts = []

    # Parse Critical Issues (P0) - try multiple patterns
    critical_section = _extract_section(response, "Critical Issues|P0|🔴 Critical")
    if critical_section:
        findings_dicts.extend(
            _parse_issue_section(critical_section, severity="critical", priority="P0")
        )

    # Parse High Priority Issues (P1) - try multiple patterns
    high_section = _extract_section(response, "High Priority|P1|⚠️.*?Issue")
    if high_section:
        findings_dicts.extend(
            _parse_issue_section(high_section, severity="high", priority="P1")
        )

    # Parse Warnings (P2/P3) - handle multiple naming conventions
    warning_section = _extract_section(response, "Warnings|P2|P3|Minor Issues|Issues Found")
    if warning_section:
        findings_dicts.extend(
            _parse_issue_section(warning_section, severity="warning", priority="P2/P3")
        )

    # Parse generic Key Findings section if no structured sections found
    # This handles analyzer responses that don't use strict P0/P1/P2 format
    if not findings_dicts:
        key_findings_section = _extract_section(response, "Key Findings")
        if key_findings_section:
            # Look for **bold service names** with issues (pattern: **service-name** followed by description)
            findings_dicts.extend(_parse_key_findings_section(key_findings_section))

    # Fallback: If still no findings but response indicates issues, parse entire response
    # This handles responses that mention "Cluster Status: DEGRADED" with numbered lists
    if not findings_dicts:
        if 'DEGRADED' in response or 'Critical Issues' in response or '🔴' in response:
            # Try to parse the entire response for issues
            findings_dicts.extend(_parse_key_findings_section(response))

    # Convert dicts to Finding objects
    findings = []
    for finding_dict in findings_dicts:
        try:
            finding = Finding(**finding_dict)
            findings.append(finding)
        except Exception as e:
            # Log conversion errors but continue processing other findings
            import sys
            print(f"Warning: Failed to convert finding dict to Finding object: {e}", file=sys.stderr)
            print(f"  Dict: {finding_dict}", file=sys.stderr)

    return findings


def _extract_section(content: str, section_pattern: str) -> str:
    """Extract a section from markdown by pattern.

    Args:
        content: Full markdown content
        section_pattern: Regex pattern for section header

    Returns:
        Content of the section, or empty string if not found
    """
    # Match section heading (###) and capture until next heading at same or higher level
    # This allows #### subsections within the ### section
    pattern = (
        f"^###\\s+(?:{section_pattern}).*?(?=^###\\s+|\\Z)"
    )
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE | re.DOTALL)

    if match:
        return match.group(0)
    return ""


def _parse_key_findings_section(section: str) -> list[dict[str, Any]]:
    """Parse findings from generic Key Findings section.

    Looks for patterns like:
    **🔴 Critical Issue:**
    - **service-name** description
    - More details

    Also handles numbered lists like:
    1. **MySQL** - Issue description

    Args:
        section: Key Findings section content

    Returns:
        List of issue dictionaries with inferred severity
    """
    findings = []

    # Strategy 1: Look for numbered items like "1. **MySQL** - Issue"
    numbered_pattern = r'^\s*\d+\.\s+\*\*([^*]+)\*\*\s*[-–]\s*(.+?)(?=\n\s*\d+\.|\n\n|$)'
    matches = list(re.finditer(numbered_pattern, section, re.MULTILINE | re.DOTALL))

    if matches:
        for match in matches:
            service_name = match.group(1).strip()
            description = match.group(2).strip()

            if description and len(description) > 5:
                # Infer severity from context
                match_start = match.start()
                preceding_text = section[:match_start]

                last_critical = preceding_text.rfind('🔴')
                last_warning = preceding_text.rfind('⚠️')
                last_degraded = preceding_text.rfind('DEGRADED')

                # If we see DEGRADED or 🔴, mark as critical
                if last_degraded > last_critical and last_degraded > last_warning:
                    severity = "critical"
                    priority = "P0"
                elif last_critical > last_warning:
                    severity = "critical"
                    priority = "P0"
                else:
                    severity = "warning"
                    priority = "P2"  # Use P2 instead of P2/P3 combination

                findings.append({
                    "severity": severity,
                    "priority": priority,
                    "description": f"{service_name} - {description}",
                })

        if findings:
            return findings

    # Strategy 2: Look for all bulleted items with **service-name** pattern
    # Pattern: "- **service-name** description"
    bullet_pattern = r'^[\s]*[-*]\s+\*\*([^*]+)\*\*\s*(.+?)(?=\n|$)'
    matches = re.finditer(bullet_pattern, section, re.MULTILINE)

    for match in matches:
        service_name = match.group(1).strip()
        description = match.group(2).strip()

        # Skip metadata lines like "Service:", "Namespace:", etc.
        if description and not description.startswith(('Service', 'Namespace', 'Issue', 'Impact')) and len(description) > 5:
            # Infer severity from context - check if we're in a critical section
            # Look back in the section to see if we're under 🔴 or ⚠️
            match_start = match.start()
            preceding_text = section[:match_start]

            # Find the last severity marker before this match
            last_critical = preceding_text.rfind('🔴')
            last_warning = preceding_text.rfind('⚠️')

            if last_critical > last_warning:
                severity = "critical"
                priority = "P0"
            else:
                severity = "warning"
                priority = "P2"  # Use P2 instead of P2/P3 combination

            findings.append({
                "severity": severity,
                "priority": priority,
                "description": f"{service_name} - {description}",
            })

    return findings


def _parse_issue_section(
    section: str, severity: str, priority: str
) -> list[dict[str, Any]]:
    """Parse issues from a section of markdown.

    Args:
        section: Markdown section content
        severity: Severity level (critical, high, warning)
        priority: Priority tier (P0, P1, P2/P3)

    Returns:
        List of issue dictionaries
    """
    findings = []

    # Check if section says "None detected" or similar
    if re.search(r'\*\*None detected\*\*|No issues|All clear', section, re.IGNORECASE):
        return findings

    # Strategy 1: Look for #### subsection headers (e.g., "#### 1. route53-updater - ImagePullBackOff (P3)")
    # This is the format used in detailed reports
    subsection_pattern = r'^####\s+\d+\.\s+(.+?)(?=^####|\Z)'
    subsection_matches = list(re.finditer(subsection_pattern, section, re.MULTILINE | re.DOTALL))

    if subsection_matches:
        # Found subsections - use those as issues
        for match in subsection_matches:
            issue_block = match.group(0)
            # Extract the title from the #### header
            title_match = re.search(r'^####\s+\d+\.\s+(.+?)$', issue_block, re.MULTILINE)
            if title_match:
                issue_title = title_match.group(1).strip()

                # Extract key details from bullet points
                service_match = re.search(r'- \*\*Service\*\*:\s+(.+?)(?=\n|$)', issue_block)
                namespace_match = re.search(r'- \*\*Namespace\*\*:\s+(.+?)(?=\n|$)', issue_block)
                issue_match = re.search(r'- \*\*Issue\*\*:\s+(.+?)(?=\n|$)', issue_block)

                # Build description
                description = issue_title
                if service_match:
                    description += f" | Service: {service_match.group(1).strip()}"
                if namespace_match:
                    description += f" | Namespace: {namespace_match.group(1).strip()}"
                if issue_match:
                    description += f" | {issue_match.group(1).strip()}"

                findings.append({
                    "severity": severity,
                    "priority": priority,
                    "description": description,
                })
        return findings

    # Strategy 2: Fallback - look for numbered lists or bullet points
    # Pattern: "1. Service: pod down" or "- Service: pod down"
    numbered_pattern = r"^\s*\d+\.\s+(.+?)(?=^\s*\d+\.|\n\n|$)"
    bullet_pattern = r"^[\s]*[-*]\s+(.+?)(?=\n[\s]*[-*]|\n\n|$)"

    # Try numbered lists first
    matches = list(re.finditer(numbered_pattern, section, re.MULTILINE | re.DOTALL))

    # If no numbered lists, try bullet points
    if not matches:
        matches = list(re.finditer(bullet_pattern, section, re.MULTILINE))

    for match in matches:
        issue_text = match.group(1).strip()

        # Skip sub-bullets with generic labels (like "**Service**:", "**Namespace**:", "**Issue**:")
        # But keep specific items like "**route53-updater**:" or "**ECR secret warnings**:"
        if re.match(r'^\*\*(Service|Namespace|Issue|Impact|Root Cause|Recent Events|Max Downtime|Services Affected)\*\*:', issue_text):
            continue

        # Skip empty lines and section headers
        if issue_text and not issue_text.startswith("#") and len(issue_text) > 10:
            # Clean up the text: remove newlines, collapse whitespace
            issue_text = re.sub(r'\n', ' ', issue_text)
            issue_text = re.sub(r'\s+', ' ', issue_text)

            findings.append({
                "severity": severity,
                "priority": priority,
                "description": issue_text,
            })

    return findings


def extract_json_from_markdown(response: str) -> dict[str, Any]:
    """Extract JSON payload from markdown response.

    Some subagents include JSON payloads in markdown code blocks:
    ```json
    { "key": "value" }
    ```

    Args:
        response: Markdown response containing JSON

    Returns:
        Extracted JSON as dictionary, or empty dict if not found
    """
    # Look for JSON code blocks
    pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    match = re.search(pattern, response, re.DOTALL)

    if match:
        try:
            json_text = match.group(1)
            return json.loads(json_text)
        except json.JSONDecodeError:
            return {}

    return {}
