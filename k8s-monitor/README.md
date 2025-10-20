# K3s Monitoring Agent - Phase 4 Complete, Phase 6 Ready for Deployment

A production-ready multi-agent monitoring system for K3s homelab clusters using Claude Agent SDK.

## Project Status

✅ **Phase 4: Integration & Scheduling** - COMPLETE (121/121 tests passing)
✅ **Phase 6: Containerization** - COMPLETE

**Current Status**: Production-ready with Docker and K3s deployment support

- ✅ All core monitoring components implemented
- ✅ Full test coverage (121 tests, 100% passing)
- ✅ Docker containerization configured
- ✅ K3s deployment manifests ready
- ✅ End-to-end monitoring pipeline operational

## Quick Start

### Prerequisites

- Python 3.11+
- K3s cluster with kubeconfig
- Anthropic API key

### Setup

```bash
# Clone and navigate
cd k8s-monitor

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys (kubeconfig is auto-detected)
```

### Configuration

Edit `.env` with required values:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
KUBECONFIG=/root/.kube/config    # Docker path (auto-detected for local execution)
K3S_CONTEXT=default

# Optional (for later phases)
GITHUB_TOKEN=ghp_...
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL=C01234567

# Model selection (optional, has sensible defaults)
K8S_ANALYZER_MODEL=claude-haiku-4-5-20251001
```

### Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_parsers.py -v
```

## Architecture

### Directory Structure

```
k8s-monitor/
├── .claude/                          # Subagent definitions
│   ├── CLAUDE.md                     # Cluster context
│   └── agents/
│       ├── k8s-analyzer.md           # ✅ Phase 1
│       ├── escalation-manager.md     # Phase 2
│       ├── github-reviewer.md        # Phase 5
│       └── slack-notifier.md         # Phase 3
│
├── src/
│   ├── main.py                       # Entry point
│   ├── config/
│   │   └── settings.py               # Pydantic settings
│   ├── orchestrator/
│   │   └── monitor.py                # Main monitoring logic
│   ├── utils/
│   │   ├── parsers.py                # Subagent output parsing
│   │   └── scheduler.py              # Job scheduling
│   └── models/
│       └── findings.py               # Data models
│
├── tests/                            # Unit tests
│   ├── conftest.py                   # Pytest fixtures
│   ├── test_config.py                # Configuration tests
│   ├── test_models.py                # Data model tests
│   └── test_parsers.py               # Parser tests
│
├── docs/
│   └── reference/
│       └── services.txt              # Service criticality mapping
│
├── logs/                             # Runtime logs
│   └── incidents/                    # Failed notification backups
│
├── pyproject.toml                    # Python project config
├── requirements.txt                  # Dependencies
├── .env.example                      # Environment template
└── README.md                         # This file
```

### Multi-Agent Pipeline

```
Orchestrator (main.py)
    ↓
Phase 1: k8s-analyzer (kubectl analysis)
    ↓ if issues found
Phase 2: escalation-manager (severity assessment)
    ↓ if SEV-1/SEV-2
Phase 5: github-reviewer (deployment correlation)
    ↓
Phase 3: slack-notifier (alert delivery)
```

## Phase 1: What's Implemented

### Core Components

1. **Settings Management** (`src/config/settings.py`)
   - Pydantic-based configuration
   - Environment variable loading
   - Path and API key validation
   - Model selection per agent

2. **Orchestrator** (`src/orchestrator/monitor.py`)
   - ClaudeSDKClient initialization
   - MCP server configuration
   - Monitoring cycle execution
   - Cycle result reporting

3. **Data Models** (`src/models/findings.py`)
   - `Finding`: Individual cluster issue
   - `Severity`: Issue severity levels (CRITICAL, HIGH, WARNING, INFO)
   - `Priority`: Service priority tiers (P0-P3)

4. **Parsing** (`src/utils/parsers.py`)
   - Markdown output parsing from k8s-analyzer
   - JSON extraction from code blocks
   - Section-based issue extraction

5. **Scheduling** (`src/utils/scheduler.py`)
   - Async job scheduling with signal handling
   - Configurable intervals
   - Graceful shutdown support

### Test Coverage

- **Configuration Tests** (9 tests)
  - Settings loading and validation
  - Environment variable handling
  - Path validation
  - Model configuration

- **Model Tests** (7 tests)
  - Finding creation and validation
  - Enum value handling
  - Model serialization

- **Parser Tests** (10 tests)
  - Markdown section extraction
  - JSON code block parsing
  - Multiple issue parsing
  - Error handling

**Total: 26/26 tests passing ✅**

## Dependencies

### Production
- `claude-agent-sdk>=0.1.1` - Multi-agent orchestration
- `pydantic>=2.12.0` - Data validation
- `pydantic-settings>=2.6.0` - Settings management
- `python-dotenv>=1.0.1` - Environment loading
- `schedule>=1.2.2` - Job scheduling
- `PyYAML>=6.0` - YAML support

### Development
- `pytest>=8.0.0` - Testing framework
- `pytest-cov>=4.0.0` - Coverage reporting
- `pytest-asyncio>=0.24.0` - Async test support
- `black>=24.0.0` - Code formatting
- `ruff>=0.4.0` - Linting
- `mypy>=1.0.0` - Type checking

## Docker Deployment

### Prerequisites
- Docker and Docker Compose installed
- K3s cluster with kubeconfig
- Anthropic API key, GitHub token, and Slack bot token

### Quick Start with Docker Compose

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 2. Build and run
docker-compose up -d

# 3. Check logs
docker-compose logs -f k8s-monitor

# 4. Verify monitoring
docker-compose exec k8s-monitor python -c "from src.config import Settings; print('✓ Configuration valid')"
```

**Kubeconfig Setup**:
The application uses intelligent kubeconfig path resolution that works for both Docker and local execution:
- **Docker**: Mounts `~/.kube/config` from host to `/root/.kube/config` in container
- **Local**: Uses `~/.kube/config` directly from your home directory
- **Configuration**: Set `KUBECONFIG=/root/.kube/config` in `.env` (works for both modes)
- **Fallback**: If configured path doesn't exist, automatically falls back to `~/.kube/config`

This means you can use the same `.env` file for both `docker compose up` and `./run_once.sh`!

### Build Custom Image

```bash
# Build for your registry
docker build -t your-registry/k8s-monitor:v1.0.0 .

# Push to registry
docker push your-registry/k8s-monitor:v1.0.0
```

## Kubernetes Deployment

### Prerequisites
- kubectl configured for your K3s cluster
- Ability to create namespaces and secrets
- Container registry access (or use local images with `imagePullPolicy: Never`)

### Deploy to K3s

```bash
# 1. Create namespace and RBAC
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/serviceaccount.yaml

# 2. Configure secrets (IMPORTANT!)
kubectl apply -f k8s/secret.yaml
# Then edit the secret with actual values:
kubectl edit secret k8s-monitor-secrets -n k8s-monitor

# 3. Create configuration
kubectl apply -f k8s/configmap.yaml

# 4. Deploy application
kubectl apply -f k8s/deployment.yaml

# 5. Verify deployment
kubectl get pods -n k8s-monitor
kubectl logs -f deployment/k8s-monitor -n k8s-monitor
```

### Verify Installation

```bash
# Check pod status
kubectl get pods -n k8s-monitor -o wide

# View logs
kubectl logs -f deployment/k8s-monitor -n k8s-monitor

# Check service account permissions
kubectl auth can-i list pods --as=system:serviceaccount:k8s-monitor:k8s-monitor

# Run a test cycle
kubectl exec -it deployment/k8s-monitor -n k8s-monitor -- python src/main.py
```

### Update Deployment

```bash
# Update configuration (no restart needed for some changes)
kubectl set env deployment/k8s-monitor -n k8s-monitor LOG_LEVEL=DEBUG

# Restart deployment
kubectl rollout restart deployment/k8s-monitor -n k8s-monitor

# View rollout status
kubectl rollout status deployment/k8s-monitor -n k8s-monitor
```

### Cleanup

```bash
# Delete deployment
kubectl delete deployment k8s-monitor -n k8s-monitor

# Delete entire namespace
kubectl delete namespace k8s-monitor
```

## Deployment Architecture

### Docker Compose Setup
- Single service with mounted kubeconfig
- Persistent logs volume
- Resource limits (512MB memory, 1 CPU)
- Health checks every 60 seconds
- Automatic restart on failure

### Kubernetes Setup
- Namespace: `k8s-monitor`
- Service Account: `k8s-monitor` with cluster read permissions
- ConfigMap: Configuration (non-sensitive settings)
- Secret: API credentials (Anthropic, GitHub, Slack)
- Deployment: Single replica of monitoring agent
- RBAC: ClusterRole with read access to cluster resources

## What's Next (Phase 5+)

### Phase 5: GitHub Correlation (Optional)
- GitHub MCP server integration
- Deployment correlation with recent commits
- Enriches alerts with root cause context
- Adds HIGH/MEDIUM/LOW confidence scores

**Skip Phase 5 if**: You want faster deployment without deployment correlation

### Post-MVP Enhancements
- State persistence for duplicate detection
- Trend analysis and pattern detection
- Web dashboard for monitoring history
- Auto-remediation for common issues
- Multi-cluster support

## Development

### Run Code Quality Checks

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type checking
mypy src/

# All checks
black src/ tests/ && ruff check src/ tests/ && mypy src/ && pytest tests/
```

### Adding New Tests

1. Create test file in `tests/test_*.py`
2. Use fixtures from `tests/conftest.py`
3. Follow existing test structure
4. Run `pytest tests/ -v` to verify

### Adding New Modules

1. Create module in `src/`
2. Add `__init__.py` for packages
3. Add unit tests in `tests/`
4. Update imports in relevant `__init__.py` files

## Key Design Decisions

### File-Based Subagents
- Subagents defined in `.claude/agents/*.md` files
- Human-readable and version-controllable
- GitOps-friendly (hot-reload with ConfigMaps)
- Matches successful EKS agent pattern

### Model Optimization
- Use Haiku (fast, cheap) for simple tasks: parsing, formatting
- Use Sonnet (smart, expensive) for complex reasoning: decisions, correlation
- ~50% cost savings vs all-Sonnet configuration

### Pydantic V2
- Modern configuration management
- Enhanced validation
- Better type support
- ConfigDict for configuration

## Troubleshooting

### Tests fail with import errors
```bash
# Reinstall dependencies
pip install -r requirements.txt
```

### "ANTHROPIC_API_KEY not found" error
```bash
# Create and configure .env file
cp .env.example .env
# Edit .env with your API key
```

### Path validation errors
```bash
# Verify kubeconfig exists
ls $KUBECONFIG

# Update .env with correct path
KUBECONFIG=/path/to/your/kubeconfig
```

## Success Criteria - Phase 1

- ✅ Project structure created and organized
- ✅ Configuration management working with validation
- ✅ ClaudeSDKClient properly initialized
- ✅ k8s-analyzer subagent definition verified
- ✅ Markdown output parsing tested
- ✅ 26 unit tests passing (100% coverage of Phase 1)
- ✅ Code follows Python best practices
- ✅ Documentation complete

## References

- [Claude Agent SDK Docs](https://docs.claude.com/en/api/agent-sdk/overview)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Kubernetes Python Client](https://github.com/kubernetes-client/python)

## License

MIT

## Version

- **Version**: 1.0.0
- **Phase**: 6 (Containerization - Production Ready)
- **Status**: Production Ready for Deployment
- **Created**: 2025-10-19
- **Last Updated**: 2025-10-20 (Phase 6 Complete)

---

## Deployment Options

### Option 1: Local Development (Recommended for Testing)
```bash
cd k8s-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
python src/main.py
```

### Option 2: Docker Compose (Recommended for Single-Node Setup)
```bash
docker-compose up -d
docker-compose logs -f
```

### Option 3: Kubernetes (Recommended for Production)
```bash
# Update k8s/secret.yaml with actual values first!
kubectl apply -f k8s/
```

---

**Production Deployment Ready**: Use Option 2 (Docker Compose) for homelab, or Option 3 (Kubernetes) for production clusters.
