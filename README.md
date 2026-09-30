# AI Agent Portfolio

Production-ready AI agents demonstrating **Claude AI integration patterns** for DevOps automation.

---

## Projects & Skills Demonstrated

### Cluster Scanner ⭐⭐⭐
> Autonomous K3s health scanner with Ralph Orchestrator

**What I Built**: Autonomous cluster health scanner using Ralph Orchestrator with 3 specialized hats. Queries the oncall-agent-api for cluster data, classifies severity (SEV-1 to SEV-4), detects trends via persistent memories, and dispatches Slack alerts when warranted. No Python, no kubectl, no RBAC required.

| Skill | Implementation |
|-------|----------------|
| **Ralph Orchestration** | 3-hat event flow: scanner → analyzer → notifier with event-driven state machine |
| **Severity Classification** | SEV-1 to SEV-4 with service priority awareness (P0/P1/P2) |
| **Trend Detection** | Ralph memories persisted via PVC, detecting new/recurring/resolved issues |
| **Cost Optimization** | Haiku model achieving ~$0.90-$1.50/year (~15K tokens/cycle, 48 cycles/day) |
| **Service Catalog Integration** | Queries oncall-agent-api instead of direct kubectl access |

**Technologies**: `Ralph Orchestrator` `Claude API` `Slack API` `Kubernetes` `Docker`

```
cluster-scanner/
├── ralph.yml          # Orchestration config (3 hats, events, memories)
├── PROMPT.md          # Shared agent prompt
├── entrypoint.sh      # Container entry point
├── k8s/               # Kubernetes CronJob manifests
└── Dockerfile
```

---

### OnCall Troubleshooting API ⭐⭐⭐
> REST API with ~25 custom tools for incident response

**What I Built**: FastAPI server exposing Claude-powered troubleshooting via RESTful endpoints. Features autonomous conversation handling, Microsoft Teams integration via Power Automate, incident memory with semantic search, and GitOps PR creation for remediation.

| Skill | Implementation |
|-------|----------------|
| **FastAPI Development** | REST API with Swagger UI, Pydantic validation, OpenAPI spec |
| **Custom Tool Development** | ~25 tools: Kubernetes, GitHub, GitOps, AWS, Datadog, incident memory |
| **API Security** | Key authentication, rate limiting (60/30/10 req/min tiers), CORS |
| **Session Management** | Multi-turn conversations with 30-min TTL, automatic cleanup |
| **Teams Integration** | Power Automate webhooks with Adaptive Card responses |
| **Incident Memory** | sqlite-vec semantic search for historical incident lookup |
| **GitOps Remediation** | Automated PR creation against ArgoCD-synced repository |

**Technologies**: `Anthropic API` `FastAPI` `Kubernetes Python Client` `PyGithub` `Boto3` `Datadog API` `sqlite-vec`

```
oncall-agent-api/
├── src/
│   ├── api/
│   │   ├── api_server.py      # FastAPI application (main entry point)
│   │   ├── agent_client.py    # Anthropic SDK wrapper, tool schemas
│   │   ├── custom_tools.py    # ~25 tool implementations
│   │   ├── session_manager.py # Conversation state management
│   │   ├── middleware.py      # Auth & rate limiting
│   │   └── slack_integration.py # Slack slash commands
│   ├── memory/                # sqlite-vec incident memory
│   └── tools/                 # K8s, GitHub, AWS, Datadog integrations
├── config/
│   └── service_mapping.yaml   # Service catalog
└── k8s/                       # Kubernetes deployment manifests
```

---

### PR Review Toolkit ⭐⭐⭐
> Triage, explain and learn from AI-authored pull requests

**What I Built**: Three pieces for a GitOps repo where an AI agent opens around 77 PRs a week:
- a GitHub Action that labels every PR `review:skip`, `review:skim` or `review:read`;
- a skill that turns a GitOps PR into a grounded, diagram-first explainer;
- a skill that runs a retro of a `/code-review` session against the fixes that followed.

| Skill | Implementation |
|-------|----------------|
| **Risk-Based PR Triage** | Composite action: policy rules, then one Jev (TypeSafe) decision request, then Claude Haiku only when Jev is unsure. Posts a label and a sticky comment; failures fall back to `review:read` |
| **Policy as Code** | `review-policy.yaml` is read at the PR's base commit, so a PR can't loosen its own triage |
| **Calibration** | Replays triage on 200 merged PRs against a follow-up-fix proxy, with time-split hot components and an offline threshold sweep |
| **Grounded Explainers** | Renders Argo CD apps (directory, Helm, kustomize) at merge-base and head and builds a deterministic resource graph. The model writes only text keyed to fact IDs, and the result is verified before publishing |
| **Session Retrospectives** | Parses Claude Code transcripts (subagents, cost-state, file coverage) and classifies each missed issue, with transcript citations |

**Technologies**: `Anthropic API` `Structured Outputs` `Jev (TypeSafe)` `GitHub Actions` `uv` `Helm` `Mermaid` `Claude Code Plugins`

```
pr-triage/                    # GitHub composite action + Python package
├── action.yml
├── src/pr_triage/            # features, rules, jev, claude, decide, comment, calibrate
└── calibration/              # calibration reports
skills/pr-explainer/          # /pr-explainer <PR>
skills/review-retro/          # /review-retro <PR> | --since 14d
```

---

### Claude Code Skills ⭐⭐
> Plugin marketplace with 19 reusable skills

**What I Built**: Marketplace of 19 Claude Code plugin skills spanning architecture, development workflows, and DevOps patterns. Each skill is a standalone Claude Code plugin that can be installed directly from GitHub.

| Skill | Implementation |
|-------|----------------|
| **Plugin System** | Claude Code plugin manifests with YAML frontmatter |
| **CLI Development** | Bash CLI with list, search, info, add, update, remove, validate, pack commands |
| **Package Management** | Install from local dirs, .skill bundles, or GitHub repositories |
| **Catalog System** | JSON-based tracking of installed skills with source metadata |

**Technologies**: `Claude Code Plugins` `Bash` `jq` `YAML Frontmatter` `ZIP Bundles`

**Available Skills (19)**:
| Skill | Category | Description |
|-------|----------|-------------|
| architecture-diagrams | documentation | Mermaid, PlantUML, C4 system diagrams |
| code-review | development | Parallel agent PR review with confidence scoring |
| feature-builder | development | Ralph Loop automated feature development |
| prompt-engineering-patterns | learning | LLM prompt optimization techniques |
| aws-well-architected | architecture | AWS Well-Architected Framework reviews |
| devops-architect | architecture | DevOps best practices with maturity scoring |
| cloud-design-patterns | architecture | AWS cloud patterns for microservices |
| platform-engineering-architect | architecture | IDP design (CNPA, Team Topologies, DORA) |
| git-commit-pr | development | Automated git workflow: branch, commit, push, PR |
| creating-implementation-plans | development | Phase-based implementation planning |
| executing-implementation-plans | development | Phase-based execution with checkpoints |
| olympus-customer-deletion | automation | Olympus customer data termination — Excel-to-CSV, dry-run, live deletion, JIRA update, certificate of destruction |
| crewai-agent-design | learning | CrewAI agent design with Role-Goal-Backstory framework and best practices |
| crewai-crew-orchestration | learning | CrewAI crew orchestration with tasks, flows, processes, and production patterns |
| crewai-testing-observability | learning | CrewAI testing, event listeners, fingerprinting, prompt customization, and multimodal files |
| crewai-tool-development | learning | CrewAI custom tools (BaseTool, @tool), async tools, MCP integration, and built-in tools catalog |
| crewai-memory-knowledge | learning | CrewAI unified memory (scopes, slices, scoring) and knowledge (RAG sources, embedders) |
| pr-explainer | development | Grounded HTML explainer for GitOps PRs: rendered-manifest resource map, risks, must-read hunks |
| review-retro | development | Retro of a /code-review session against later fixes: misses, causes, cost, proposals |

#### Install Skills from the Marketplace

Each skill is a standalone Claude Code plugin. Install individual skills directly from GitHub:

```bash
# Install a single skill
claude plugin add --from-github arigsela/claude-agents/skills/code-review

# Install any skill using the pattern:
claude plugin add --from-github arigsela/claude-agents/skills/<skill-name>
```

**Available skill names for installation:**
```
architecture-diagrams           aws-well-architected            cloud-design-patterns
code-review                     creating-implementation-plans   crewai-agent-design
crewai-crew-orchestration       crewai-memory-knowledge         crewai-testing-observability
crewai-tool-development         devops-architect                executing-implementation-plans
feature-builder                 git-commit-pr                   olympus-customer-deletion
platform-engineering-architect  prompt-engineering-patterns
```

#### Legacy CLI (local use)

```bash
./skills/skill-cli.sh list                    # List installed skills
./skills/skill-cli.sh search "review"         # Search by name/tags
./skills/skill-cli.sh info code-review        # Show skill details
./skills/skill-cli.sh add ./skills/code-review # Install from local directory
```

```
skills/
├── skill-cli.sh           # Legacy CLI entry point
├── lib/skill-utils.sh     # Core utilities
├── skills-catalog.json    # Installed skills tracking
├── architecture-diagrams/ # System diagrams
├── code-review/           # Parallel agent PR review
├── feature-builder/       # Ralph Loop development
├── devops-architect/      # DevOps best practices
└── ...                    # 7 more skills
```

---

## Architecture Patterns Demonstrated

| Pattern | Cluster Scanner | OnCall API | Skills Marketplace |
|---------|:--------------:|:----------:|:------------------:|
| Ralph Orchestration | ✅ | - | - |
| REST API Design | - | ✅ | - |
| Custom Tool Development | - | ✅ | - |
| Semantic Vector Search | - | ✅ | - |
| Session Management | - | ✅ | - |
| Rate Limiting & Auth | - | ✅ | - |
| Teams Integration | - | ✅ | - |
| GitOps Remediation | - | ✅ | - |
| Severity Classification | ✅ | ✅ | - |
| Trend Detection | ✅ | - | - |
| CLI Development | - | - | ✅ |
| Plugin System | - | - | ✅ |

---

## Quick Start

```bash
# Cluster Scanner - Autonomous K3s monitoring
cd cluster-scanner && ./test-local.sh  # Needs port-forwarded oncall-api

# OnCall API - HTTP endpoints with Teams integration
cd oncall-agent-api && pip install -r requirements.txt && ./run_api_server.sh
open http://localhost:8000/docs        # Interactive Swagger UI

# Skills Marketplace - List and manage skills
./skills/skill-cli.sh list
./skills/skill-cli.sh info code-review

# PR Triage - dry-run one PR (needs TYPESAFE_API_KEY and ANTHROPIC_API_KEY)
uv run --project pr-triage python -m pr_triage run --repo arigsela/kubernetes --pr 650 --dry-run
```

---

## Tech Stack

**AI/ML**: Anthropic API, Claude Haiku/Sonnet, sqlite-vec, Semantic Search

**Backend**: Python 3.11+, FastAPI, Pydantic, AsyncIO

**Orchestration**: Ralph Orchestrator, Event-driven State Machine

**Infrastructure**: Kubernetes, Docker, AWS (ECR, Secrets Manager, Cost Explorer)

**Integrations**: Microsoft Teams, Slack, GitHub, Datadog

---

MIT License
