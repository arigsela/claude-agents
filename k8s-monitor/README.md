# K3s Monitoring Agent - Phase 5 Complete

A production-ready multi-agent monitoring system for K3s homelab clusters using Claude Agent SDK with **long-context multi-cycle monitoring**.

## Project Status

✅ **Phase 4: Integration & Scheduling** - COMPLETE (121/121 tests passing)
✅ **Phase 5: Long-Context Monitoring** - COMPLETE (208/208 tests passing)
✅ **Phase 6: Containerization** - COMPLETE

**Current Status**: Production-ready with long-context trend detection and Docker/K3s deployment support

- ✅ All core monitoring components implemented
- ✅ **Long-context persistent monitoring** with trend detection
- ✅ **Session management** with smart pruning (120k token limit)
- ✅ Full test coverage (208 tests, 100% passing)
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

# Run long-context tests
pytest test_context_accumulation.py test_trend_detection.py test_context_pruning.py -v
```

## Long-Context Monitoring (Phase 5)

### What is Long-Context Monitoring?

Traditional monitoring systems analyze each cycle independently. Long-context monitoring maintains **persistent conversation history** across monitoring cycles, enabling:

- **Trend Detection**: Identifies escalation, degradation, and recovery patterns
- **Root Cause Analysis**: Correlates issues across multiple cycles
- **Smart Escalation**: Distinguishes recurring issues from transient problems
- **Context-Aware Decisions**: References previous cycles in analysis

### Modes

**Stateless Mode** (Default)
- Each cycle independent, no history accumulation
- Lower token usage (~8K/cycle)
- Suitable for cost-sensitive deployments
- Can still track trends via external systems

**Persistent Mode** (Long-Context)
- Maintains conversation history across cycles
- Automatic trend detection and pattern recognition
- Higher token usage (~15K/cycle) but richer insights
- Smart pruning at 80% of 120k token limit

### Configuration

Enable long-context monitoring in `.env`:

```bash
# Enable persistent session mode
ENABLE_LONG_CONTEXT=true

# Session configuration (optional)
SESSION_DIR=.sessions              # Session storage location
MAX_CONTEXT_TOKENS=120000          # Token limit before pruning
```

### Session Management

Sessions are automatically managed:
- **Saved**: After each cycle to `SESSION_DIR/`
- **Pruned**: At 80% token usage (96k tokens)
- **Preserved**: System messages and recent 50 messages
- **Recovered**: Automatically loads previous session on restart

### Smart Pruning

When context approaches token limits:
1. **Preserves critical messages** containing:
   - SEV-1/P0 escalations
   - Critical/high-severity issues
   - Incident declarations
2. **Keeps recent history** (last 50 messages)
3. **Maintains system context** (agent instructions)

### Example: Trend Detection in Action

```
Cycle 1: "Found 5 unhealthy pods in monitoring namespace"
Cycle 2: "Detected worsening trend: 5 → 13 issues (2.6x increase)"
Cycle 3: "Escalation continues: 13 → 56 issues across 8 namespaces"
         "Pattern: Cascading failure from node-2 memory pressure"
```

### Testing Long-Context Behavior

```bash
# Test context accumulation patterns
pytest test_context_accumulation.py -v

# Test trend detection algorithms
pytest test_trend_detection.py -v

# Test pruning and recovery
pytest test_context_pruning.py -v

# Test real-world scenarios
pytest test_real_world_scenarios.py -v

# Test performance comparison
pytest test_performance_comparison.py -v
```

**Test Coverage**: 87 long-context tests validating:
- Cycle tracking and timestamps
- Stateless vs persistent mode differences
- Escalation/degradation/recovery patterns
- Context pruning strategies
- Session persistence and recovery
- Real-world scenario validation

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
│   │   ├── monitor.py                # Main monitoring logic
│   │   ├── persistent_monitor.py     # ✅ Phase 5: Long-context mode
│   │   └── stateless_monitor.py      # ✅ Phase 5: Stateless mode
│   ├── sessions/
│   │   └── session_manager.py        # ✅ Phase 5: Session persistence
│   ├── utils/
│   │   ├── parsers.py                # Subagent output parsing
│   │   ├── scheduler.py              # Job scheduling
│   │   └── formatters.py             # ✅ Phase 5: Message formatting
│   └── models/
│       └── findings.py               # Data models
│
├── tests/                            # Unit tests (121 tests)
│   ├── conftest.py                   # Pytest fixtures
│   ├── test_config.py                # Configuration tests
│   ├── test_models.py                # Data model tests
│   └── test_parsers.py               # Parser tests
│
├── test_*.py                         # ✅ Phase 5: Long-context tests (87 tests)
│   ├── test_context_accumulation.py  # Context growth patterns
│   ├── test_trend_detection.py       # Trend algorithms
│   ├── test_context_pruning.py       # Pruning strategies
│   ├── test_real_world_scenarios.py  # Production scenarios
│   └── test_performance_comparison.py # Mode comparison
│
├── .sessions/                        # ✅ Phase 5: Session storage
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

## What's Next

### Potential Enhancements
- ✅ ~~State persistence for duplicate detection~~ (Phase 5 complete)
- ✅ ~~Trend analysis and pattern detection~~ (Phase 5 complete)
- GitHub MCP server integration (deployment correlation)
- Web dashboard for monitoring history
- Auto-remediation for common issues
- Multi-cluster support
- Enhanced smart pruning with semantic analysis
- Anomaly detection with statistical models
- Custom alert rules engine

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

## Success Criteria

### Phase 1 ✅
- ✅ Project structure created and organized
- ✅ Configuration management working with validation
- ✅ ClaudeSDKClient properly initialized
- ✅ k8s-analyzer subagent definition verified
- ✅ Markdown output parsing tested
- ✅ 26 unit tests passing (100% coverage of Phase 1)
- ✅ Code follows Python best practices
- ✅ Documentation complete

### Phase 5 (Long-Context Monitoring) ✅
- ✅ Persistent session architecture designed
- ✅ SessionManager with pruning implemented
- ✅ PersistentMonitor with conversation history
- ✅ StatelessMonitor for cost-sensitive deployments
- ✅ MessageFormatter for cycle summaries
- ✅ Smart pruning preserving critical messages
- ✅ Session persistence and recovery
- ✅ 87 long-context tests passing (100% coverage)
- ✅ Real-world scenarios validated
- ✅ Production deployment confirmed working

## References

- [Claude Agent SDK Docs](https://docs.claude.com/en/api/agent-sdk/overview)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Kubernetes Python Client](https://github.com/kubernetes-client/python)

## License

MIT

## Version

- **Version**: 1.1.0
- **Phase**: 5 (Long-Context Monitoring - Complete)
- **Status**: Production Ready with Trend Detection
- **Created**: 2025-10-19
- **Last Updated**: 2025-10-22 (Phase 5 Complete - Long-Context Monitoring)

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
