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
    # Now handles: "Critical Issues", "**Critical Issues**", "Critical Issues (Require...)", etc.
    critical_section = _extract_section(response, r"\*\*Critical Issues.*?\*\*|Critical Issues|P0|🔴 Critical")
    if critical_section:
        findings_dicts.extend(
            _parse_issue_section(critical_section, severity="critical", priority="P0")
        )

    # Parse High Priority Issues (P1) - try multiple patterns
    # Now handles: "High Priority", "**High Priority**", "High Priority (Important)", etc.
    high_section = _extract_section(response, r"\*\*High Priority.*?\*\*|High Priority|P1|⚠️.*?Issue")
    if high_section:
        findings_dicts.extend(
            _parse_issue_section(high_section, severity="high", priority="P1")
        )

    # Parse Warnings (P2) - handle multiple naming conventions
    warning_section = _extract_section(response, "Warnings|P2|P3|Minor Issues|Issues Found")
    if warning_section:
        findings_dicts.extend(
            _parse_issue_section(warning_section, severity="warning", priority="P2")
        )

    # Parse generic Key Findings section if no structured sections found
    # This handles analyzer responses that don't use strict P0/P1/P2 format
    if not findings_dicts:
        key_findings_section = _extract_section(response, "Key Findings")
        if key_findings_section:
            # Look for **Critical Issues:** subsection within Key Findings
            critical_subsection = _extract_bold_subsection(key_findings_section, "Critical Issues")
            if critical_subsection:
                findings_dicts.extend(_parse_key_findings_section(critical_subsection))

            # If still no findings, look for any **bold service names** with issues
            if not findings_dicts:
                findings_dicts.extend(_parse_key_findings_section(key_findings_section))

    # Parse ## FINDINGS section (2 hashes) - Claude may output this format
    # This is a direct response to our explicit instructions in the query
    if not findings_dicts:
        findings_section = _extract_findings_section(response)
        if findings_section:
            findings_dicts.extend(_parse_key_findings_section(findings_section))

    # Fallback: If still no findings but response indicates issues, parse entire response
    # This handles responses that mention "Cluster Status: DEGRADED" with numbered lists
    if not findings_dicts:
        if 'DEGRADED' in response or 'Critical Issues' in response or '🔴' in response or 'P0' in response or 'Severity:' in response:
            # Try to parse the entire response for issues
            findings_dicts.extend(_parse_key_findings_section(response))

    # Convert dicts to Finding objects
    findings = []
    for finding_dict in findings_dicts:
        try:
            finding = Finding(**finding_dict)
            findings.append(finding)
        except Exception as e:
            # Log conversion errors but append dict anyway for backward compatibility
            import sys
            print(f"Warning: Failed to convert finding dict to Finding object: {e}", file=sys.stderr)
            print(f"  Dict: {finding_dict}", file=sys.stderr)
            # Append the dict anyway so it's not lost
            findings.append(finding_dict)

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


def _extract_bold_subsection(content: str, subsection_pattern: str) -> str:
    """Extract content after a bold subsection marker like **Critical Issues:**.

    Args:
        content: Content to search within
        subsection_pattern: Pattern to match (e.g., "Critical Issues")

    Returns:
        Content from the bold marker until the next bold subsection or end
    """
    # Match **Pattern:** and capture until next **Anything:** or end
    pattern = (
        rf"\*\*{subsection_pattern}:?\*\*.*?(?=\*\*[A-Z][^*]+:?\*\*|###|\Z)"
    )
    match = re.search(pattern, content, re.MULTILINE | re.IGNORECASE | re.DOTALL)

    if match:
        return match.group(0)
    return ""


def _extract_findings_section(content: str) -> str:
    """Extract ## FINDINGS section from markdown response.

    This handles the direct output from Claude when responding to our
    explicit instructions for ## FINDINGS format.

    Args:
        content: Full markdown content

    Returns:
        Content of the ## FINDINGS section, or empty string if not found
    """
    # Match ## FINDINGS (2 hashes) and capture until next ## heading or end
    pattern = r"^##\s+FINDINGS\s*$.*?(?=^##\s+|\Z)"
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
       - Namespace: mysql
       - Details: ...
       - Severity: P0

    Args:
        section: Key Findings section content

    Returns:
        List of issue dictionaries with inferred severity
    """
    findings = []

    # Strategy 1: Look for numbered items like "1. **MySQL** - Issue" with optional indented metadata
    # This pattern captures:
    # 1. **MySQL** - Database Connection Failure
    #    - Namespace: mysql
    #    - Severity: P0
    # BUT: Skip section headers like "### P1 Critical Issues (Service Impact)"
    numbered_pattern = r'^\s*\d+\.\s+\*\*([^*]+)\*\*\s*[-–]\s*(.+?)(?=\n\s*\d+\.|\n(?:\s*##|\s*###)|\Z)'
    matches = list(re.finditer(numbered_pattern, section, re.MULTILINE | re.DOTALL))

    # Filter out section headers (they don't have " - " separator and end with parentheses or colons)
    matches = [m for m in matches if not re.match(r'^(P\d+|Critical|High|Warning|Note|Issues?)\s', m.group(1).strip(), re.IGNORECASE)]

    if matches:
        for match in matches:
            service_name = match.group(1).strip()
            description_block = match.group(2).strip()

            # Extract severity from metadata lines within this block
            severity = "warning"
            priority = "P2"

            # Look for explicit severity/priority indicators in the block
            severity_match = re.search(r'Severity:\s*(P0|P1|P2|P3|critical|high|warning)', description_block, re.IGNORECASE)
            if severity_match:
                sev_value = severity_match.group(1).upper()
                if sev_value.startswith('P0') or sev_value == 'CRITICAL':
                    severity = "critical"
                    priority = "P0"
                elif sev_value.startswith('P1') or sev_value == 'HIGH':
                    severity = "high"
                    priority = "P1"

            # Also check if this block appears under a critical marker in preceding text
            if not severity_match:
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

            # Extract just the first line (the main description)
            first_line = description_block.split('\n')[0].strip()
            if first_line and len(first_line) > 5:
                findings.append({
                    "severity": severity,
                    "priority": priority,
                    "description": f"{service_name} - {first_line}",
                    "service": service_name,  # Include service field
                })

        if findings:
            return findings

    # Strategy 2: Look for bold headers with colons at start of line (no bullet)
    # Pattern: "**CRITICAL - service-name is DOWN:**" or "**MySQL Configuration Issue:**"
    header_pattern = r'^\*\*([A-Z]+\s*-\s*)?(.+?):\*\*'
    header_matches = list(re.finditer(header_pattern, section, re.MULTILINE))

    if header_matches:
        for match in header_matches:
            severity_label = match.group(1).strip() if match.group(1) else ""
            service_desc = match.group(2).strip()

            # Determine severity from label or preceding context
            # Check if CRITICAL appears anywhere in the matched text or before it
            match_start = match.start()
            preceding_text = section[:match_start]
            full_header = match.group(0)

            if 'CRITICAL' in full_header.upper() or 'CRITICAL' in preceding_text[-100:].upper():
                severity = "critical"
                priority = "P0"
            elif 'HIGH' in full_header.upper() or 'HIGH' in preceding_text[-100:].upper():
                severity = "high"
                priority = "P1"
            else:
                # Default to critical if we see DEGRADED in context
                if 'DEGRADED' in preceding_text[-200:]:
                    severity = "critical"
                    priority = "P0"
                else:
                    severity = "warning"
                    priority = "P2"

            # Extract service name (remove "is DOWN/UP" suffix if present)
            service_name = re.sub(r'\s+is\s+(DOWN|UP|DEGRADED|UNHEALTHY)', '', service_desc, flags=re.IGNORECASE)

            findings.append({
                "severity": severity,
                "priority": priority,
                "description": match.group(0).replace('**', '').replace(':', '').strip(),
                "service": service_name,
            })

        if findings:
            return findings

    # Strategy 3: Look for all bulleted items with **service-name** pattern
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
                "service": service_name,  # Include service field
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

                # Extract service name from description if possible
                service_name = None
                service_match = re.search(r'Service:\s+(.+?)(?:\s+\||$)', description)
                if service_match:
                    service_name = service_match.group(1).strip()

                findings.append({
                    "severity": severity,
                    "priority": priority,
                    "description": description,
                    "service": service_name,  # Include service field
                })
        return findings

    # Strategy 2: Fallback - look for numbered lists or bullet points
    # Pattern: "1. **Service-name - Issue**" or "1. Service: pod down" or "- Service: pod down"
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

        # Skip section headers that look like "P1 Critical Issues (Service Impact)" or "Note"
        # These don't have the format: "service-name - issue description"
        if re.match(r'^(P\d+|Critical|High|Warning|Note|Issues?)\s+', issue_text, re.IGNORECASE):
            continue

        # Skip empty lines and section headers
        if issue_text and not issue_text.startswith("#") and len(issue_text) > 10:
            # Extract service name from various patterns:
            # Pattern 1: **service-name - Issue**
            # Pattern 2: **service-name Issue**
            # Pattern 3: Service: service-name
            service_name = None

            # Try pattern: **service-name - Issue** (extract service name and issue from bold text)
            service_pattern_1 = re.match(r'^\*\*(.+?)\s+[-–]\s+(.+?)\*\*', issue_text)
            if service_pattern_1:
                service_name = service_pattern_1.group(1).strip()
                issue_desc = service_pattern_1.group(2).strip()
                # Build clean description from first line only
                issue_text = f"{service_name} - {issue_desc}"
            else:
                # Try pattern: Service: service-name
                service_match = re.search(r'Service:\s+(.+?)(?:\s+\||$)', issue_text)
                if service_match:
                    service_name = service_match.group(1).strip()

            # Clean up the text: remove newlines, collapse whitespace, remove bold markers
            issue_text = re.sub(r'\n', ' ', issue_text)
            issue_text = re.sub(r'\s+', ' ', issue_text)
            issue_text = re.sub(r'\*\*', '', issue_text)  # Remove bold markers

            findings.append({
                "severity": severity,
                "priority": priority,
                "description": issue_text,
                "service": service_name,  # Include service field
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
