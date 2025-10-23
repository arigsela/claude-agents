# Phase 2: Skills Integration - Document Generation & Code Execution

## Executive Summary

**Phase 1 Status**: ✅ Complete - Skills provide reference knowledge to the agent
**Phase 2 Goal**: Transform skills from passive reference material into active capabilities

Phase 2 adds two major capabilities:
1. **Document Generation** - Skills can generate dynamic reports, runbooks, and documentation
2. **Code Execution** - Skills can execute Python/bash code for automation

**Recommended Approach**: Start with Document Generation only (Phase 2A), then optionally add Code Execution (Phase 2B)

---

## Phase 2A: Document Generation (RECOMMENDED START)

### Overview

Enable skills to generate formatted documents (markdown reports, JSON data, YAML configs) based on troubleshooting data.

### What Gets Built

#### 1. Template Engine Module
**File**: `src/api/skill_template_engine.py` (~200 lines)

**Responsibilities**:
- Parse template blocks from SKILL.md files
- Render Jinja2-style templates with data
- Validate template syntax
- Manage output file generation

**Key Functions**:
```python
class SkillTemplateEngine:
    def parse_skill_templates(skill_path: Path) -> Dict[str, str]:
        """Extract template blocks from SKILL.md"""

    def render_template(template_content: str, data: dict) -> str:
        """Render Jinja2 template with provided data"""

    def save_document(content: str, filename: str, output_dir: Path) -> Path:
        """Save rendered document to filesystem"""

    def get_available_templates(skill_name: str) -> List[str]:
        """List templates available in a skill"""
```

#### 2. Document Generation Tool
**File**: `src/api/custom_tools.py` (+100 lines)

**New Tool**:
```python
async def generate_skill_document(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a document from a skill template.

    Args:
        skill_name: Name of the skill containing the template
        template_name: Name of the template to use
        data: Dictionary of data to populate the template
        output_filename: Optional custom filename

    Returns:
        {
            "success": true,
            "file_path": "/tmp/oncall-reports/incident-2025-10-23.md",
            "template_used": "k8s_incident_report",
            "data_keys": ["timestamp", "severity", "summary"]
        }
    """
```

#### 3. Enhanced Skill Loading
**File**: `src/api/agent_client.py` (+75 lines)

**Changes**:
```python
class OnCallAgentClient:
    def _load_skill_content(self, skill_name: str) -> Optional[Dict]:
        """
        Enhanced to parse and return:
        - Skill instructions (existing)
        - Available templates (NEW)
        - Template metadata (NEW)
        """

    def _get_system_prompt(self) -> str:
        """
        Modified to include:
        - Available templates per skill
        - Instructions on using generate_skill_document tool
        """
```

#### 4. Example Skills with Templates

**File**: `.claude/skills/incident-reporter.md` (~300 lines)

```markdown
---
name: incident-reporter
description: Generate detailed incident reports for Kubernetes issues
capabilities: [document_generation]
version: 1.0.0
---

# Incident Reporter Skill

This skill generates standardized incident reports for Kubernetes issues.

## Available Templates

### k8s_incident_report
Full incident report with investigation steps and remediation.

```template:k8s_incident_report
# Kubernetes Incident Report

**Generated**: {{timestamp}}
**Cluster**: {{cluster_name}}
**Severity**: {{severity}}

## Incident Summary
{{summary}}

## Affected Resources
{% for resource in affected_resources %}
- **{{resource.kind}}**: {{resource.name}} ({{resource.namespace}})
  - Status: {{resource.status}}
  - Issue: {{resource.issue}}
{% endfor %}

## Investigation Timeline
{% for step in investigation_steps %}
{{loop.index}}. [{{step.timestamp}}] {{step.description}}
   {% if step.output %}
   ```
   {{step.output}}
   ```
   {% endif %}
{% endfor %}

## Root Cause Analysis
{{root_cause}}

## Remediation Actions Taken
{% for action in remediation_actions %}
- [{{action.status}}] {{action.description}}
  {% if action.result %}
  - Result: {{action.result}}
  {% endif %}
{% endfor %}

## Recommendations
{{recommendations}}

## Follow-up Required
{% if follow_up_required %}
{{follow_up_details}}
{% else %}
No follow-up required. Incident fully resolved.
{% endif %}
```

### pod_restart_report
Brief report for pod restart actions.

```template:pod_restart_report
# Pod Restart Report

**Time**: {{timestamp}}
**Pod**: {{pod_name}} ({{namespace}})
**Reason**: {{restart_reason}}

## Pre-Restart Status
- Restart Count: {{pre_restart_count}}
- Status: {{pre_status}}

## Action Taken
{{action_description}}

## Post-Restart Status
- Status: {{post_status}}
- Ready: {{post_ready}}
```

## Usage Instructions

When investigating a Kubernetes incident:

1. Gather all relevant data (pod info, events, logs)
2. Call `generate_skill_document` tool with:
   - skill_name: "incident-reporter"
   - template_name: "k8s_incident_report" or "pod_restart_report"
   - data: Dictionary with all template variables
3. Document is saved to `/tmp/oncall-reports/`
4. Return file path to user for sharing

## Template Variables

### k8s_incident_report
- `timestamp` (str): ISO format timestamp
- `cluster_name` (str): Kubernetes cluster name
- `severity` (str): critical|high|medium|low
- `summary` (str): Brief incident description
- `affected_resources` (list): [{"kind": "Pod", "name": "...", "namespace": "...", "status": "...", "issue": "..."}]
- `investigation_steps` (list): [{"timestamp": "...", "description": "...", "output": "..."}]
- `root_cause` (str): RCA summary
- `remediation_actions` (list): [{"status": "completed|pending", "description": "...", "result": "..."}]
- `recommendations` (str): Future prevention steps
- `follow_up_required` (bool): Whether follow-up needed
- `follow_up_details` (str): Follow-up details if required
```

**Additional Skills**:
- `.claude/skills/runbook-generator.md` - Generate troubleshooting runbooks
- `.claude/skills/status-reporter.md` - Cluster health status reports

---

### Architecture & Data Flow

```
User Query: "MySQL pod crashed, investigate and create incident report"
    ↓
Agent analyzes using existing tools
    ↓
Gathers: pod logs, events, recent deployments
    ↓
Determines: OOMKilled, needs restart, root cause found
    ↓
Agent calls: generate_skill_document
    ├─ skill_name: "incident-reporter"
    ├─ template_name: "k8s_incident_report"
    └─ data: {timestamp, severity, summary, affected_resources, ...}
    ↓
SkillTemplateEngine
    ├─ Loads template from .claude/skills/incident-reporter.md
    ├─ Validates data against template variables
    ├─ Renders Jinja2 template
    └─ Saves to /tmp/oncall-reports/incident-2025-10-23-mysql-crash.md
    ↓
Returns: {"success": true, "file_path": "...", ...}
    ↓
Agent response: "Incident report generated at /tmp/oncall-reports/..."
```

---

### Implementation Checklist

**Week 1: Core Infrastructure**

- [ ] Day 1-2: Create `skill_template_engine.py`
  - [ ] Template block parser
  - [ ] Jinja2 renderer
  - [ ] File output management
  - [ ] Unit tests

- [ ] Day 3-4: Add `generate_skill_document` tool
  - [ ] Tool implementation in custom_tools.py
  - [ ] Template discovery from skills
  - [ ] Integration with SkillTemplateEngine
  - [ ] Error handling and validation

- [ ] Day 5: Update agent_client.py
  - [ ] Modify `_load_skill_content()` to parse templates
  - [ ] Add template metadata to system prompt
  - [ ] Register new tool with agent

**Week 2: Skills & Testing**

- [ ] Day 1-2: Create incident-reporter.md skill
  - [ ] k8s_incident_report template
  - [ ] pod_restart_report template
  - [ ] Documentation and examples

- [ ] Day 3: Create additional skills
  - [ ] runbook-generator.md
  - [ ] status-reporter.md

- [ ] Day 4: Integration testing
  - [ ] End-to-end test with real query
  - [ ] Template rendering validation
  - [ ] Output file verification

- [ ] Day 5: Documentation
  - [ ] Update testing-skills-locally.md
  - [ ] Create template authoring guide
  - [ ] Update README with Phase 2 info

---

### Dependencies

**New Python Packages**:
```txt
jinja2>=3.1.0
```

**Update requirements.txt**:
```bash
echo "jinja2>=3.1.0" >> requirements.txt
pip install -r requirements.txt
```

---

### Testing Strategy

#### Unit Tests
**File**: `tests/api/test_skill_template_engine.py`

```python
def test_parse_skill_templates():
    """Test template extraction from SKILL.md"""

def test_render_template():
    """Test Jinja2 rendering with sample data"""

def test_save_document():
    """Test file output generation"""

def test_template_validation():
    """Test validation of required template variables"""
```

#### Integration Tests
**File**: `tests/api/test_document_generation.py`

```python
async def test_generate_document_tool():
    """Test end-to-end document generation"""

async def test_template_discovery():
    """Test agent can discover available templates"""

async def test_output_file_creation():
    """Test documents saved to correct location"""
```

#### Manual Testing

```bash
# 1. Start API server
./run_api_server.sh

# 2. Test document generation
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "The chores-tracker pod in homelab-prod crashed due to OOMKilled. Generate an incident report."
  }'

# 3. Verify document created
ls -la /tmp/oncall-reports/
cat /tmp/oncall-reports/incident-*.md
```

---

### Configuration

**Output Directory** (configurable via environment):
```bash
# .env
SKILL_REPORTS_DIR=/tmp/oncall-reports

# Docker
volumes:
  - ./reports:/tmp/oncall-reports
```

**Template Validation** (in skill_template_engine.py):
```python
TEMPLATE_VALIDATION = {
    "max_size_kb": 500,  # Max template size
    "max_output_size_kb": 2000,  # Max rendered output
    "allowed_jinja_features": [
        "for", "if", "else", "elif",  # Control flow
        "loop.index", "loop.first"     # Loop variables
    ],
    "forbidden_jinja_features": [
        "import", "include",  # No file includes
        "exec", "eval"        # No code execution
    ]
}
```

---

### Benefits

1. **Automated Documentation**
   - Consistent, professional incident reports
   - Generated in seconds, not minutes
   - No manual formatting errors

2. **Knowledge Sharing**
   - Reports can be attached to Teams notifications
   - Shareable markdown format
   - Historical record of incidents

3. **Extensibility**
   - Easy to add new report types
   - Team members can create templates without code changes
   - Templates versioned in git

4. **Foundation for Phase 2B**
   - Template engine also useful for code execution
   - Established patterns for skill capabilities
   - Tested infrastructure for dynamic content

---

### Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Template injection vulnerabilities | High | Jinja2 sandboxing, no eval/exec, validation |
| Large output files consuming disk | Medium | Size limits, automatic cleanup, monitoring |
| Invalid template syntax breaks agent | Medium | Template validation on load, error handling |
| User confusion about available templates | Low | Clear documentation, list-templates command |

---

### Success Metrics

After Phase 2A completion:

- [ ] Agent can generate incident reports from troubleshooting data
- [ ] Documents saved to `/tmp/oncall-reports/` with correct formatting
- [ ] 3+ template types available (incident, runbook, status)
- [ ] Templates render without errors for valid data
- [ ] Documentation complete and tested
- [ ] Team members can create new templates by following guide

---

## Phase 2B: Code Execution (OPTIONAL - FUTURE)

### Overview

Enable skills to execute Python scripts and bash commands for automation (e.g., vault unsealing, pod restarts).

### What Gets Built

#### 1. Code Execution Module
**File**: `src/api/skill_code_executor.py` (~300 lines)

**Features**:
- Parse code blocks from SKILL.md
- Sandboxed subprocess execution
- Timeout enforcement (30s default)
- Whitelist of allowed commands/modules
- Audit logging

#### 2. Execution Tool
**File**: `src/api/custom_tools.py` (+150 lines)

```python
async def execute_skill_code(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute code from a skill.

    Args:
        skill_name: Skill containing the code
        function_name: Named code block to execute
        context: Data to pass to the code

    Returns:
        {
            "success": true,
            "output": "...",
            "exit_code": 0,
            "execution_time_ms": 1234
        }
    """
```

#### 3. Example Skills with Code

**File**: `.claude/skills/vault-automation.md`

```markdown
---
name: vault-automation
description: Automate Vault unsealing procedures
capabilities: [code_execution]
allowed_operations: [kubectl_exec]
---

## Automated Vault Unsealing

```python:unseal_vault
import subprocess
import json

def unseal_vault(namespace="vault", pod_name="vault-0"):
    """Unseal Vault pod using kubectl exec"""
    cmd = [
        "kubectl", "exec", "-n", namespace, pod_name,
        "--", "vault", "operator", "unseal"
    ]

    result = subprocess.run(cmd, capture_output=True, timeout=30)

    return {
        "status": "success" if result.returncode == 0 else "failed",
        "output": result.stdout.decode(),
        "exit_code": result.returncode
    }
```

### Security Considerations

**Whitelist Approach**:
```python
ALLOWED_COMMANDS = {
    "kubectl": ["get", "describe", "logs", "exec"],
    "python": ["subprocess.run"],  # Only specific functions
}

FORBIDDEN_OPERATIONS = [
    "kubectl delete",
    "kubectl apply",
    "rm -rf",
    "eval",
    "exec"
]
```

**Approval Workflow**:
- All code execution requires explicit user approval
- Show code to be executed before running
- Log all executions to audit trail

### Why Defer Phase 2B

1. **Security Complexity**: Requires robust sandboxing and approval system
2. **Lower Priority**: Document generation provides immediate value
3. **Testing Burden**: Need comprehensive security testing
4. **Existing Tools**: Agent already has kubectl/GitHub tools for most operations

**When to Implement Phase 2B**:
- After Phase 2A is stable and proven
- When automation needs exceed existing tools
- When security review process is established

---

## Decision Points for Phase 2

### Question 1: Which phase to implement?

**Option A: Phase 2A Only (Document Generation)** ✅ RECOMMENDED
- Lower risk, immediate value
- Safe auto-execution
- Good foundation for future

**Option B: Phase 2A + 2B (Full Implementation)**
- More powerful but higher risk
- Requires security review
- Longer implementation time

**Option C: Phase 2B Only (Code Execution)**
- Not recommended - document generation is prerequisite
- Higher risk without the foundation

### Question 2: Output location?

**Option A: /tmp/oncall-reports/** ✅ RECOMMENDED
- Simple, works in containers
- Easy to mount volume for persistence

**Option B: S3 Bucket**
- Persistent, accessible from anywhere
- Requires AWS credentials
- More complex implementation

**Option C: Attach to API response**
- No filesystem required
- Limited to small documents
- Can't share file paths

### Question 3: Template validation strictness?

**Option A: Strict (Recommended for production)** ✅
- Validate all template variables present
- Enforce size limits
- Syntax check on load

**Option B: Permissive (Good for development)**
- Allow missing variables (render as blank)
- Larger size limits
- More flexible but riskier

### Question 4: Implementation timeline?

**Option A: 2 weeks (Full implementation)** ✅ RECOMMENDED
- Week 1: Core infrastructure + tools
- Week 2: Skills + testing + docs

**Option B: 1 week (Minimal viable)**
- Core infrastructure only
- 1 example skill
- Basic testing

**Option C: 3-4 weeks (Production-ready)**
- Full implementation
- Comprehensive testing
- Security review
- Performance optimization

---

## Recommended Next Steps

### Immediate (Now)

1. **Review this document** and decide:
   - Proceed with Phase 2A? (Document Generation)
   - Timeline preference (1-2 weeks)?
   - Output directory preference?

2. **Confirm scope**:
   - Start with incident-reporter skill only?
   - Or implement all 3 example skills?

3. **Environment setup**:
   - Create `/tmp/oncall-reports/` directory
   - Update .env with SKILL_REPORTS_DIR if needed

### After Approval

1. **Week 1**: Implement core infrastructure
2. **Week 2**: Create skills and test
3. **Week 3**: Deploy and gather feedback

### Future Considerations

- **Phase 2B (Code Execution)**: Defer until Phase 2A proven stable
- **Additional Templates**: Team can add templates as needed
- **Integration**: Consider integrating generated reports with Teams notifications

---

## Questions & Clarifications Needed

Before proceeding, please confirm:

1. ✅ or ❌ Proceed with Phase 2A (Document Generation)?
2. Timeline: 1 week (minimal) or 2 weeks (complete)?
3. Output directory: `/tmp/oncall-reports/` or S3 or other?
4. Scope: Start with incident-reporter only or all 3 skills?
5. Any specific report types you'd like to see?
6. Should reports be automatically attached to Teams notifications?

---

## Conclusion

**Phase 2A: Document Generation** provides significant value with minimal risk. It enables automated, consistent reporting while establishing the foundation for future automation capabilities.

**Estimated effort**: 40-60 hours (1-2 weeks)
**Risk level**: Low (read-only, safe operations)
**Value**: High (immediate documentation automation)

**Recommendation**: ✅ Proceed with Phase 2A, defer Phase 2B until proven need.
