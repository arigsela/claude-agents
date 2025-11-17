# **CAIPE Local Implementation Plan - November 2025**

## **📋 Table of Contents**

1. [Prerequisites & System Requirements](#prerequisites--system-requirements)
2. [Phase 1: Environment Setup](#phase-1-environment-setup-30-minutes)
3. [Phase 2: Deploy CNOE IDP with idpbuilder](#phase-2-deploy-cnoe-idp-with-idpbuilder-20-minutes)
4. [Phase 3: Deploy CAIPE Components](#phase-3-deploy-caipe-components-30-minutes)
5. [Phase 4: Integrate Your Existing Agents](#phase-4-integrate-your-existing-agents-45-minutes)
6. [Phase 5: Configure Claude Agent Integration](#phase-5-configure-claude-agent-integration-30-minutes)
7. [Phase 6: Testing & Validation](#phase-6-testing--validation-20-minutes)
8. [Phase 7: Production Readiness](#phase-7-production-readiness-optional)
9. [Troubleshooting Guide](#troubleshooting-guide)
10. [Cost Optimization](#cost-optimization)
11. [Next Steps](#next-steps)

---

## **📋 Prerequisites & System Requirements**

### **Latest Stable Versions (November 2025)**

| Component | Version | Notes |
|-----------|---------|-------|
| **Docker Desktop** | `4.36.0+` | Latest stable release |
| **Kubernetes** | `1.31.x` | Latest stable (1.32 in beta) |
| **kubectl** | `1.31.x` | Match K8s version |
| **idpbuilder** | `v0.10.1` | Latest stable release |
| **CAIPE** | `v0.1.x` | Active development |
| **Kind** | `0.24.0+` | Bundled with idpbuilder |
| **ArgoCD** | `v2.12.x` | Part of CNOE stack |
| **Backstage** | `v1.29.x` | Part of CNOE stack |

### **Hardware Requirements**

- **CPU**: 8+ cores recommended (minimum 4 cores)
- **RAM**: 16GB+ recommended (minimum 12GB)
- **Disk**: 50GB+ free space
- **Network**: Reliable internet connection
- **OS**: macOS 12+, Ubuntu 22.04+, or Windows 11 with WSL2

### **Required Tools**

- Git
- Docker Desktop (or Docker Engine + Kind)
- kubectl
- curl/wget
- Text editor (VS Code recommended)

---

## **🚀 Phase 1: Environment Setup (30 minutes)**

### **Step 1.1: Install Docker Desktop**

#### **macOS**
```bash
# For Intel Macs
curl -O "https://desktop.docker.com/mac/main/amd64/Docker.dmg"
open Docker.dmg

# For Apple Silicon Macs
curl -O "https://desktop.docker.com/mac/main/arm64/Docker.dmg"
open Docker.dmg
```

#### **Linux**
```bash
# Ubuntu/Debian
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

#### **Windows**
```powershell
# Download and install Docker Desktop for Windows
# https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe
# Ensure WSL2 is enabled
```

### **Step 1.2: Configure Docker Resources**

Open Docker Desktop → Settings → Resources:

| Resource | Recommended | Minimum |
|----------|-------------|---------|
| **CPUs** | 8 | 4 |
| **Memory** | 12 GB | 8 GB |
| **Swap** | 4 GB | 2 GB |
| **Disk** | 100 GB | 50 GB |

### **Step 1.3: Install kubectl**

```bash
# macOS (via Homebrew)
brew install kubectl

# macOS (manual)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/darwin/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# Linux
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# Verify
kubectl version --client
```

### **Step 1.4: Verify Docker & Kubernetes**

```bash
# Test Docker
docker --version
docker run hello-world

# Test Docker resources
docker info | grep -E "CPUs|Total Memory"
```

---

## **🏗️ Phase 2: Deploy CNOE IDP with idpbuilder (20 minutes)**

### **Step 2.1: Download idpbuilder**

```bash
# Create working directory
mkdir -p ~/caipe-lab && cd ~/caipe-lab

# Download latest idpbuilder
version=$(curl -Ls -o /dev/null -w %{url_effective} https://github.com/cnoe-io/idpbuilder/releases/latest)
version=${version##*/}

# macOS (Intel)
curl -L -o ./idpbuilder.tar.gz "https://github.com/cnoe-io/idpbuilder/releases/download/${version}/idpbuilder-darwin-amd64.tar.gz"

# macOS (Apple Silicon)
curl -L -o ./idpbuilder.tar.gz "https://github.com/cnoe-io/idpbuilder/releases/download/${version}/idpbuilder-darwin-arm64.tar.gz"

# Linux
curl -L -o ./idpbuilder.tar.gz "https://github.com/cnoe-io/idpbuilder/releases/download/${version}/idpbuilder-linux-amd64.tar.gz"

# Extract and install
tar xvzf idpbuilder.tar.gz
chmod +x idpbuilder
sudo mv idpbuilder /usr/local/bin/

# Verify
idpbuilder version
```

### **Step 2.2: Deploy CNOE Reference Implementation**

**Choose your deployment option based on your needs:**

| Option | Includes | Resource Usage | Recommended For |
|--------|----------|----------------|-----------------|
| **Basic CNOE** | ArgoCD, Gitea, Backstage, Keycloak, NGINX | Low | Learning CNOE basics |
| **CNOE + CAIPE Base** | Basic CNOE + Core CAIPE components | Medium | Testing CAIPE fundamentals |
| **CNOE + CAIPE Complete** | Basic CNOE + Full CAIPE stack | High | Production-like environment |
| **CNOE + CAIPE Complete Slim** | Basic CNOE + Streamlined CAIPE | Medium-High | Resource-constrained environments |

```bash
# Deploy the stack with CAIPE integration
# Note: idpbuilder v0.10.1+ uses --package instead of --package-dir
# and --name instead of --build-name

# Option 1: Basic CNOE stack only (RECOMMENDED FOR FIRST-TIME USERS)
# Use this if you want to understand CNOE first, then add CAIPE later
idpbuilder create \
  --use-path-routing \
  --package https://github.com/cnoe-io/stacks//ref-implementation \
  --name caipe-local

# Option 2: CNOE + CAIPE Base (RECOMMENDED FOR THIS TUTORIAL)
# Includes core CAIPE components for AI platform engineering
idpbuilder create \
  --use-path-routing \
  --package https://github.com/cnoe-io/stacks//ref-implementation \
  --package https://github.com/cnoe-io/stacks//caipe/base \
  --name caipe-local

# Option 3: CNOE + CAIPE Complete
# Full-featured CAIPE with all components (requires 16GB+ RAM)
idpbuilder create \
  --use-path-routing \
  --package https://github.com/cnoe-io/stacks//ref-implementation \
  --package https://github.com/cnoe-io/stacks//caipe/complete \
  --name caipe-local

# Option 4: CNOE + CAIPE Complete Slim
# Streamlined CAIPE with reduced resource overhead
idpbuilder create \
  --use-path-routing \
  --package https://github.com/cnoe-io/stacks//ref-implementation \
  --package https://github.com/cnoe-io/stacks//caipe/complete-slim \
  --name caipe-local

# This will take 10-20 minutes to complete (longer with CAIPE packages)
# Expected output:
# ✓ Creating kind cluster
# ✓ Installing ArgoCD
# ✓ Deploying core packages
# ✓ Setting up ingress
# ✓ Configuring Backstage
# ✓ Syncing CAIPE components (if included)
```

**What gets deployed:**

| Component | Purpose | Access |
|-----------|---------|--------|
| **Kind Cluster** | Local Kubernetes cluster | `kubectl cluster-info` |
| **ArgoCD** | GitOps CD platform | `https://cnoe.localtest.me:8443/argocd` |
| **Gitea** | Internal Git server | `https://cnoe.localtest.me:8443/gitea` |
| **Backstage** | Developer portal | `https://cnoe.localtest.me:8443` |
| **Keycloak** | Identity provider | `https://cnoe.localtest.me:8443/keycloak` |
| **Argo Workflows** | Workflow engine | `https://cnoe.localtest.me:8443/argo-workflows` |
| **AI Platform** | CAIPE multi-agent system | `https://cnoe.localtest.me:8443/ai-platform-engineering` |
| **Vault** | Secrets management | `https://vault.cnoe.localtest.me:8443` |
| **NGINX Ingress** | Traffic routing | Automatic |

**📌 Important:** All services use **path-based routing** on the same domain `cnoe.localtest.me:8443`, except Vault which uses its own subdomain `vault.cnoe.localtest.me:8443`.

### **Step 2.3: Verify Deployment**

```bash
# Check cluster status
kubectl cluster-info
kubectl get nodes

# Check all namespaces
kubectl get namespaces

# Check ArgoCD applications
kubectl get applications -n argocd

# Wait for all applications to sync (5-10 minutes)
watch kubectl get applications -n argocd

# Expected: All applications show "Synced" and "Healthy"
```

### **Step 2.4: Access Web Interfaces**

```bash
# Get user credentials (recommended for daily use)
kubectl get secret -n keycloak keycloak-config --context kind-caipe-local \
  -o jsonpath='{.data.USER_PASSWORD}' | base64 -d && echo

# Get admin credentials (for Keycloak administration)
kubectl get secret -n keycloak keycloak-config --context kind-caipe-local \
  -o jsonpath='{.data.KEYCLOAK_ADMIN_PASSWORD}' | base64 -d && echo

# Open Backstage (main developer portal)
open https://cnoe.localtest.me:8443

# Open ArgoCD (GitOps dashboard)
open https://cnoe.localtest.me:8443/argocd

# Open Gitea (internal Git server)
open https://cnoe.localtest.me:8443/gitea
```

**Login Credentials:**

| Username | Password | Use Case |
|----------|----------|----------|
| `user1` | Run first command above | **Recommended** - Daily Backstage access |
| `admin` | Run second command above | Keycloak administration only |

**Note:** When accessing Backstage, you'll be redirected to Keycloak for authentication. Use the `user1` credentials for normal usage.

**All Service URLs:**
- **Backstage**: `https://cnoe.localtest.me:8443` (root path)
- **ArgoCD**: `https://cnoe.localtest.me:8443/argocd`
- **Gitea**: `https://cnoe.localtest.me:8443/gitea`
- **Keycloak**: `https://cnoe.localtest.me:8443/keycloak`
- **Argo Workflows**: `https://cnoe.localtest.me:8443/argo-workflows`
- **AI Platform Engineering**: `https://cnoe.localtest.me:8443/ai-platform-engineering`
- **Vault**: `https://vault.cnoe.localtest.me:8443` (separate subdomain)

### **Step 2.5: Configure LLM Provider Credentials (REQUIRED for CAIPE)**

**⚠️ IMPORTANT:** If you deployed CAIPE (Option 2, 3, or 4 in Step 2.2), the CAIPE agents require LLM provider credentials to function. Without these credentials, the agent pods will fail with `CreateContainerConfigError`.

CAIPE uses **Vault** and **External Secrets Operator** to manage credentials securely. You need to configure your LLM provider credentials in Vault.

#### **Step 2.5.1: Get Vault Root Token**

```bash
# Get the Vault root token
export VAULT_ROOT_TOKEN=$(kubectl get secret -n vault vault-root-token \
  --context kind-caipe-local \
  -o jsonpath='{.data.token}' | base64 -d)

echo "Vault Root Token: $VAULT_ROOT_TOKEN"
```

#### **Step 2.5.2: Configure Anthropic Credentials**

**Supported LLM Providers:**
- `anthropic-claude` - Anthropic Claude (this tutorial)
- `azure-openai` - Azure OpenAI
- `openai` - OpenAI
- `aws-bedrock` - AWS Bedrock
- `gcp-vertexai` - Google Vertex AI
- `google-gemini` - Google Gemini

**For Anthropic Claude (recommended for this tutorial):**

```bash
# Configure Anthropic credentials in Vault
kubectl exec -n vault vault-0 --context kind-caipe-local -- sh -c "
export VAULT_TOKEN=$VAULT_ROOT_TOKEN
export VAULT_SKIP_VERIFY=true

vault kv put secret/ai-platform-engineering/global \
  LLM_PROVIDER=anthropic-claude \
  ANTHROPIC_API_KEY=sk-ant-api03-YOUR-API-KEY-HERE \
  ANTHROPIC_MODEL_NAME=claude-sonnet-4-20250514 \
  AZURE_OPENAI_API_KEY='' \
  AZURE_OPENAI_ENDPOINT='' \
  AZURE_OPENAI_API_VERSION='' \
  AZURE_OPENAI_DEPLOYMENT='' \
  OPENAI_API_KEY='' \
  OPENAI_ENDPOINT='' \
  OPENAI_API_VERSION='' \
  OPENAI_MODEL_NAME='' \
  AWS_ACCESS_KEY_ID='' \
  AWS_SECRET_ACCESS_KEY='' \
  AWS_REGION='' \
  AWS_BEDROCK_MODEL_ID='' \
  AWS_BEDROCK_PROVIDER=''
"
```

**Available Anthropic Models:**
- `claude-sonnet-4-20250514` (recommended - latest, best balance)
- `claude-opus-4-20250514` (most capable, slower, more expensive)
- `claude-sonnet-3-5-20241022` (previous generation)
- `claude-haiku-3-5-20250307` (fastest, cheapest)

#### **Step 2.5.3: Update ExternalSecret to Include ANTHROPIC Keys**

The default ExternalSecret doesn't map ANTHROPIC_API_KEY and ANTHROPIC_MODEL_NAME. We need to add these mappings:

```bash
# Disable ArgoCD auto-sync to prevent our changes from being reverted
kubectl patch application ai-platform-engineering \
  -n argocd \
  --context kind-caipe-local \
  --type=merge \
  -p='{"spec":{"syncPolicy":{"automated":null}}}'

# Add ANTHROPIC_API_KEY mapping
kubectl patch externalsecret llm-secret \
  -n ai-platform-engineering \
  --context kind-caipe-local \
  --type='json' \
  -p='[
    {
      "op": "add",
      "path": "/spec/data/0",
      "value": {
        "secretKey": "ANTHROPIC_API_KEY",
        "remoteRef": {
          "key": "secret/ai-platform-engineering/global",
          "property": "ANTHROPIC_API_KEY"
        }
      }
    }
  ]'

# Add ANTHROPIC_MODEL_NAME mapping
kubectl patch externalsecret llm-secret \
  -n ai-platform-engineering \
  --context kind-caipe-local \
  --type='json' \
  -p='[
    {
      "op": "add",
      "path": "/spec/data/-",
      "value": {
        "secretKey": "ANTHROPIC_MODEL_NAME",
        "remoteRef": {
          "key": "secret/ai-platform-engineering/global",
          "property": "ANTHROPIC_MODEL_NAME"
        }
      }
    }
  ]'
```

#### **Step 2.5.4: Force Secret Refresh and Restart CAIPE Agents**

```bash
# Delete the secret to force External Secrets Operator to recreate it
kubectl delete secret llm-secret \
  -n ai-platform-engineering \
  --context kind-caipe-local

# Wait for secret to be recreated (10 seconds)
sleep 10

# Verify the secret has the required keys
kubectl get secret llm-secret \
  -n ai-platform-engineering \
  --context kind-caipe-local \
  -o jsonpath='{.data}' | grep -o "ANTHROPIC_API_KEY\|ANTHROPIC_MODEL_NAME\|LLM_PROVIDER"

# Restart CAIPE agent deployments to pick up the new credentials
kubectl rollout restart deployment \
  -n ai-platform-engineering \
  --context kind-caipe-local
```

#### **Step 2.5.5: Monitor CAIPE Agent Startup**

CAIPE agents can take 5-10 minutes to start up on first launch as they:
1. Initialize multi-agent system graphs
2. Load LLM model configurations
3. Check connectivity to other agent services
4. Build RAG (Retrieval Augmented Generation) indexes

```bash
# Watch pod status (wait for all agents to be 1/1 Ready)
watch kubectl get pods -n ai-platform-engineering --context kind-caipe-local

# Check specific agent logs if needed
kubectl logs -n ai-platform-engineering \
  deployment/ai-platform-engineering-supervisor-agent \
  --context kind-caipe-local \
  --tail=50

# Expected final state:
# - 3 MCP servers: 1/1 Running (fast startup)
# - 4 Agents: 1/1 Running (slow startup, 5-10 minutes)
```

**Common Issues:**

| Issue | Error Message | Solution |
|-------|--------------|----------|
| **Missing API Key** | `CreateContainerConfigError: secret "llm-secret" not found` | Complete Step 2.5.2 to configure Vault |
| **Wrong Provider** | `ValueError: Unsupported provider: anthropic` | Use `anthropic-claude` not `anthropic` in Step 2.5.2 |
| **Missing Model Name** | `OSError: ANTHROPIC_MODEL_NAME environment variable is required` | Complete Step 2.5.3 to add model name mapping |
| **Slow Startup** | Pods stuck in `Running 0/1` for >5 minutes | Normal - CAIPE agents are complex, wait up to 10 minutes |
| **CrashLoopBackOff** | Repeated restarts | Check logs with `kubectl logs` command above |

---

## **🤖 Phase 3: Deploy CAIPE Components (30 minutes)**

**⚠️ NOTE:** If you deployed CAIPE via Step 2.2 Options 2-4, CAIPE components are already deployed. This phase is only needed if you deployed Option 1 (Basic CNOE only) and want to add CAIPE manually later.

### **Step 3.1: Clone CAIPE Repository**

```bash
cd ~/caipe-lab
git clone https://github.com/cnoe-io/ai-platform-engineering.git
cd ai-platform-engineering
git checkout main
```

### **Step 3.2: Deploy CAIPE Core**

```bash
# Create CAIPE namespace
kubectl create namespace caipe-system

# Deploy CAIPE CRDs (Custom Resource Definitions)
kubectl apply -f examples/basic-setup/crds/

# Deploy CAIPE controller
kubectl apply -f examples/basic-setup/manifests/

# Verify controller is running
kubectl get pods -n caipe-system
kubectl logs -n caipe-system -l app=caipe-controller --tail=50
```

### **Step 3.3: Deploy Sample MCP Servers**

CAIPE uses Model Context Protocol (MCP) servers to provide tools to agents.

```bash
# Deploy kubectl MCP server (for K8s operations)
kubectl apply -f examples/mcp-servers/kubectl-mcp-server.yaml

# Deploy ArgoCD MCP server (for GitOps operations)
kubectl apply -f examples/mcp-servers/argocd-mcp-server.yaml

# Deploy Backstage MCP server (for catalog operations)
kubectl apply -f examples/mcp-servers/backstage-mcp-server.yaml

# Verify MCP servers
kubectl get pods -n caipe-system -l app.kubernetes.io/component=mcp-server
```

### **Step 3.4: Configure Your First Platform Agent**

Create a Platform Engineer agent that can help with IDP operations:

```yaml
# ~/caipe-lab/platform-engineer-agent.yaml
apiVersion: caipe.cnoe.io/v1alpha1
kind: PlatformAgent
metadata:
  name: platform-engineer
  namespace: caipe-system
spec:
  persona: "platform-engineer"
  description: "Platform Engineer Agent for IDP operations"

  # Claude API configuration
  llm:
    provider: "anthropic"
    model: "claude-sonnet-4-20250514"
    apiKeySecret:
      name: anthropic-api-key
      key: api-key

  # System prompt
  systemPrompt: |
    You are a Platform Engineer Agent specializing in:
    - Kubernetes cluster operations
    - GitOps workflows with ArgoCD
    - Internal Developer Platform (IDP) management
    - Backstage catalog operations
    - Infrastructure troubleshooting

    You have access to tools via MCP servers for:
    - kubectl (Kubernetes operations)
    - ArgoCD (GitOps deployments)
    - Backstage (Service catalog management)

    Always prioritize safety:
    - Never delete production resources
    - Always check before making changes
    - Provide clear explanations of actions

  # MCP tool servers
  tools:
    - name: kubectl-tool
      type: mcp-server
      endpoint: http://kubectl-mcp-server.caipe-system.svc.cluster.local:8080
      description: "Kubernetes cluster operations"

    - name: argocd-tool
      type: mcp-server
      endpoint: http://argocd-mcp-server.caipe-system.svc.cluster.local:8080
      description: "GitOps deployment operations"

    - name: backstage-tool
      type: mcp-server
      endpoint: http://backstage-mcp-server.caipe-system.svc.cluster.local:8080
      description: "Service catalog operations"

  # Integration points
  integrations:
    backstage:
      enabled: true
      url: https://backstage.cnoe.localtest.me:8443

    slack:
      enabled: false  # Configure later if needed

    github:
      enabled: false  # Configure later if needed

  # Safety constraints
  constraints:
    allowedNamespaces:
      - "default"
      - "caipe-system"
      - "backstage"

    forbiddenOperations:
      - "delete persistentvolumeclaim"
      - "delete namespace"
      - "delete node"

    requireApproval:
      - "scale deployment"
      - "delete pod"
```

Deploy the agent:

```bash
# First, create the API key secret
kubectl create secret generic anthropic-api-key \
  --from-literal=api-key="YOUR_ANTHROPIC_API_KEY" \
  -n caipe-system

# Deploy the agent
kubectl apply -f ~/caipe-lab/platform-engineer-agent.yaml

# Verify agent is running
kubectl get platformagents -n caipe-system
kubectl describe platformagent platform-engineer -n caipe-system
```

---

## **🔗 Phase 4: Integrate Your Existing Agents (45 minutes)**

Now let's integrate your existing agents (EKS monitoring and OnCall) into the CAIPE framework.

### **Step 4.1: Convert EKS Monitoring Agent to MCP Server**

Your EKS agent uses Claude Agent SDK with MCP servers. We'll adapt it to work within CAIPE:

```python
# ~/caipe-lab/eks-monitoring-mcp-adapter.py
"""
MCP Server adapter for the EKS monitoring agent.
Exposes the agent's monitoring capabilities as MCP tools.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import your existing EKS monitoring logic
# Adjust the import path to match your repository structure
import sys
sys.path.append('/path/to/your/claude-agents/eks')
from monitor_daemon import ClusterMonitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EKSMonitoringMCPServer:
    """MCP Server wrapper for EKS monitoring agent."""

    def __init__(self):
        self.server = Server("eks-monitoring")
        self.monitor = None

        # Register tools
        self.server.list_tools()(self._list_tools)
        self.server.call_tool()(self._call_tool)

    async def _list_tools(self) -> List[Tool]:
        """List available monitoring tools."""
        return [
            Tool(
                name="check_cluster_health",
                description="Perform comprehensive cluster health check across all namespaces",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "cluster_name": {
                            "type": "string",
                            "description": "Name of the EKS cluster to monitor"
                        },
                        "namespaces": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific namespaces to check (optional, defaults to all)"
                        }
                    },
                    "required": ["cluster_name"]
                }
            ),
            Tool(
                name="analyze_pod_logs",
                description="Analyze pod logs for errors and patterns",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "pod_name": {"type": "string"},
                        "container": {"type": "string"},
                        "lines": {
                            "type": "number",
                            "description": "Number of log lines to analyze",
                            "default": 100
                        }
                    },
                    "required": ["namespace", "pod_name"]
                }
            ),
            Tool(
                name="remediate_deployment",
                description="Perform safe remediation for a failing deployment",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "deployment": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": ["restart", "scale_up", "scale_down"],
                            "description": "Remediation action to perform"
                        },
                        "dry_run": {
                            "type": "boolean",
                            "default": True,
                            "description": "Perform dry run without making changes"
                        }
                    },
                    "required": ["namespace", "deployment", "action"]
                }
            ),
            Tool(
                name="get_cost_insights",
                description="Get cost optimization insights for the cluster",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "cluster_name": {"type": "string"},
                        "namespace": {
                            "type": "string",
                            "description": "Specific namespace (optional)"
                        }
                    },
                    "required": ["cluster_name"]
                }
            )
        ]

    async def _call_tool(self, name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Execute a monitoring tool."""
        try:
            if name == "check_cluster_health":
                result = await self._check_cluster_health(arguments)
            elif name == "analyze_pod_logs":
                result = await self._analyze_pod_logs(arguments)
            elif name == "remediate_deployment":
                result = await self._remediate_deployment(arguments)
            elif name == "get_cost_insights":
                result = await self._get_cost_insights(arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")

            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e)})
            )]

    async def _check_cluster_health(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to the k8s-diagnostics subagent logic."""
        # This would invoke your existing diagnostic logic
        # Adapt based on your actual implementation
        cluster_name = args["cluster_name"]
        namespaces = args.get("namespaces", [])

        # Example: Call your existing monitoring code
        # result = await self.monitor.run_health_check(cluster_name, namespaces)

        return {
            "cluster": cluster_name,
            "status": "healthy",
            "namespaces_checked": len(namespaces) if namespaces else "all",
            "issues_found": 0,
            "details": "Cluster health check completed successfully"
        }

    async def _analyze_pod_logs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to the k8s-log-analyzer subagent logic."""
        # Adapt based on your actual log analyzer implementation
        return {
            "namespace": args["namespace"],
            "pod": args["pod_name"],
            "errors_found": [],
            "analysis": "No critical errors detected"
        }

    async def _remediate_deployment(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to the k8s-remediation subagent logic."""
        # Adapt based on your actual remediation implementation
        if args.get("dry_run", True):
            return {
                "status": "dry_run",
                "action": args["action"],
                "deployment": f"{args['namespace']}/{args['deployment']}",
                "message": "Dry run completed - no changes made"
            }

        return {
            "status": "executed",
            "action": args["action"],
            "deployment": f"{args['namespace']}/{args['deployment']}"
        }

    async def _get_cost_insights(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delegate to the k8s-cost-optimizer subagent logic."""
        # Adapt based on your actual cost optimization implementation
        return {
            "cluster": args["cluster_name"],
            "total_cost_monthly": 0,
            "optimization_opportunities": [],
            "recommendations": []
        }

    async def run(self):
        """Run the MCP server."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


if __name__ == "__main__":
    server = EKSMonitoringMCPServer()
    asyncio.run(server.run())
```

Create a Kubernetes deployment for this MCP server:

```yaml
# ~/caipe-lab/eks-monitoring-mcp-deployment.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: eks-monitoring-config
  namespace: caipe-system
data:
  ORCHESTRATOR_MODEL: "claude-sonnet-4-20250514"
  DIAGNOSTIC_MODEL: "claude-sonnet-4-20250514"
  LOG_ANALYZER_MODEL: "claude-sonnet-4-5-20250929"
  CLUSTER_NAME: "dev-eks"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: eks-monitoring-mcp-server
  namespace: caipe-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: eks-monitoring-mcp
  template:
    metadata:
      labels:
        app: eks-monitoring-mcp
    spec:
      containers:
      - name: mcp-server
        image: your-registry/eks-monitoring-mcp:latest
        ports:
        - containerPort: 8080
          name: mcp
        env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: anthropic-api-key
              key: api-key
        envFrom:
        - configMapRef:
            name: eks-monitoring-config
        volumeMounts:
        - name: kubeconfig
          mountPath: /root/.kube
          readOnly: true
      volumes:
      - name: kubeconfig
        secret:
          secretName: eks-kubeconfig
---
apiVersion: v1
kind: Service
metadata:
  name: eks-monitoring-mcp-server
  namespace: caipe-system
spec:
  selector:
    app: eks-monitoring-mcp
  ports:
  - port: 8080
    targetPort: 8080
    name: mcp
```

### **Step 4.2: Convert OnCall Agent to MCP Server**

Your OnCall agent uses the Anthropic API directly. Let's create an MCP adapter:

```python
# ~/caipe-lab/oncall-agent-mcp-adapter.py
"""
MCP Server adapter for the OnCall troubleshooting agent.
Exposes the agent's troubleshooting capabilities as MCP tools.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import your existing OnCall agent logic
import sys
sys.path.append('/path/to/your/claude-agents/oncall')
from src.agent.orchestrator import OnCallOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OnCallMCPServer:
    """MCP Server wrapper for OnCall troubleshooting agent."""

    def __init__(self):
        self.server = Server("oncall-troubleshooting")
        self.orchestrator = OnCallOrchestrator()

        # Register tools
        self.server.list_tools()(self._list_tools)
        self.server.call_tool()(self._call_tool)

    async def _list_tools(self) -> List[Tool]:
        """List available troubleshooting tools."""
        return [
            Tool(
                name="investigate_incident",
                description="Perform two-turn investigation of a Kubernetes incident",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "incident_description": {
                            "type": "string",
                            "description": "Description of the incident or error"
                        },
                        "namespace": {"type": "string"},
                        "pod_name": {
                            "type": "string",
                            "description": "Affected pod (if known)"
                        },
                        "service_name": {
                            "type": "string",
                            "description": "Affected service (if known)"
                        }
                    },
                    "required": ["incident_description"]
                }
            ),
            Tool(
                name="query_oncall",
                description="Ask the OnCall agent a question about the cluster or services",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Question or query for the OnCall agent"
                        },
                        "context": {
                            "type": "object",
                            "description": "Additional context (namespace, service, etc.)"
                        }
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name="create_session",
                description="Create a troubleshooting session for multi-turn conversation",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "initial_query": {"type": "string"},
                        "metadata": {
                            "type": "object",
                            "description": "Session metadata (user, team, etc.)"
                        }
                    },
                    "required": ["initial_query"]
                }
            )
        ]

    async def _call_tool(self, name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Execute a troubleshooting tool."""
        try:
            if name == "investigate_incident":
                result = await self._investigate_incident(arguments)
            elif name == "query_oncall":
                result = await self._query_oncall(arguments)
            elif name == "create_session":
                result = await self._create_session(arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")

            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e)})
            )]

    async def _investigate_incident(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Perform incident investigation using two-turn pattern."""
        # Delegate to your existing orchestrator logic
        result = await self.orchestrator.investigate_incident(
            description=args["incident_description"],
            namespace=args.get("namespace"),
            pod_name=args.get("pod_name")
        )

        return {
            "incident": args["incident_description"],
            "severity": result.get("severity", "unknown"),
            "root_cause": result.get("root_cause", ""),
            "remediation_steps": result.get("remediation", []),
            "investigation_details": result
        }

    async def _query_oncall(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a general query."""
        result = await self.orchestrator.handle_query(
            query=args["query"],
            context=args.get("context", {})
        )

        return {
            "query": args["query"],
            "response": result.get("response", ""),
            "confidence": result.get("confidence", 0.0)
        }

    async def _create_session(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new troubleshooting session."""
        session_id = await self.orchestrator.create_session(
            initial_query=args["initial_query"],
            metadata=args.get("metadata", {})
        )

        return {
            "session_id": session_id,
            "initial_query": args["initial_query"],
            "status": "created"
        }

    async def run(self):
        """Run the MCP server."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


if __name__ == "__main__":
    server = OnCallMCPServer()
    asyncio.run(server.run())
```

Deploy as Kubernetes service:

```yaml
# ~/caipe-lab/oncall-mcp-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oncall-mcp-server
  namespace: caipe-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: oncall-mcp
  template:
    metadata:
      labels:
        app: oncall-mcp
    spec:
      containers:
      - name: mcp-server
        image: your-registry/oncall-mcp:latest
        ports:
        - containerPort: 8080
          name: mcp
        env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: anthropic-api-key
              key: api-key
        - name: ANTHROPIC_MODEL
          value: "claude-sonnet-4-20250514"
---
apiVersion: v1
kind: Service
metadata:
  name: oncall-mcp-server
  namespace: caipe-system
spec:
  selector:
    app: oncall-mcp
  ports:
  - port: 8080
    targetPort: 8080
    name: mcp
```

### **Step 4.3: Update Platform Agent with Your Tools**

Now update the Platform Engineer agent to use your custom MCP servers:

```yaml
# ~/caipe-lab/platform-engineer-agent-with-custom-tools.yaml
apiVersion: caipe.cnoe.io/v1alpha1
kind: PlatformAgent
metadata:
  name: platform-engineer-enhanced
  namespace: caipe-system
spec:
  persona: "platform-engineer"
  description: "Enhanced Platform Engineer with EKS monitoring and OnCall capabilities"

  llm:
    provider: "anthropic"
    model: "claude-sonnet-4-20250514"
    apiKeySecret:
      name: anthropic-api-key
      key: api-key

  systemPrompt: |
    You are an enhanced Platform Engineer Agent with access to:

    1. **Core Platform Tools:**
       - kubectl (Kubernetes operations)
       - ArgoCD (GitOps deployments)
       - Backstage (Service catalog)

    2. **EKS Monitoring Tools:**
       - Cluster health checks across all namespaces
       - Cost optimization insights
       - Deployment remediation (rolling restarts, scaling)
       - Log analysis for root cause investigation

    3. **OnCall Troubleshooting Tools:**
       - Incident investigation (two-turn deep analysis)
       - Interactive troubleshooting sessions
       - Service correlation and dependency analysis

    **Workflow Examples:**

    - For proactive monitoring: Use EKS monitoring tools
    - For incident response: Use OnCall investigation tools
    - For routine operations: Use core platform tools

    Always prioritize safety and explain your reasoning.

  tools:
    # Core platform tools
    - name: kubectl-tool
      type: mcp-server
      endpoint: http://kubectl-mcp-server.caipe-system.svc.cluster.local:8080

    - name: argocd-tool
      type: mcp-server
      endpoint: http://argocd-mcp-server.caipe-system.svc.cluster.local:8080

    - name: backstage-tool
      type: mcp-server
      endpoint: http://backstage-mcp-server.caipe-system.svc.cluster.local:8080

    # Your custom EKS monitoring tools
    - name: eks-monitoring
      type: mcp-server
      endpoint: http://eks-monitoring-mcp-server.caipe-system.svc.cluster.local:8080
      description: "EKS cluster monitoring and auto-remediation"

    # Your custom OnCall tools
    - name: oncall-troubleshooting
      type: mcp-server
      endpoint: http://oncall-mcp-server.caipe-system.svc.cluster.local:8080
      description: "Incident investigation and troubleshooting"

  integrations:
    backstage:
      enabled: true
      url: https://backstage.cnoe.localtest.me:8443

  constraints:
    allowedNamespaces:
      - "default"
      - "caipe-system"
      - "backstage"
      - "proteus-dev"
      - "hermes-dev"

    forbiddenOperations:
      - "delete persistentvolumeclaim"
      - "delete namespace kube-system"
```

---

## **🔧 Phase 5: Configure Claude Agent Integration (30 minutes)**

### **Step 5.1: Configure Backstage Plugin**

CAIPE provides a Backstage plugin for interacting with agents directly from the developer portal.

```yaml
# Add to your Backstage app-config.yaml
# (typically managed via ConfigMap in CNOE)

caipe:
  enabled: true
  agents:
    - name: platform-engineer-enhanced
      endpoint: http://caipe-controller.caipe-system.svc.cluster.local:8080/agents/platform-engineer-enhanced
      description: "Platform Engineer with EKS monitoring and OnCall troubleshooting"
      capabilities:
        - "Cluster health monitoring"
        - "Incident investigation"
        - "GitOps operations"
        - "Cost optimization"

  ui:
    chatInterface: true
    toolExecution: true
    sessionManagement: true
```

Update the Backstage ConfigMap:

```bash
kubectl edit configmap backstage-app-config -n backstage

# Add the caipe section above
# Save and wait for Backstage to reload (2-3 minutes)
```

### **Step 5.2: Test Agent Integration**

```bash
# Create a test interaction via kubectl
kubectl create -f - <<EOF
apiVersion: caipe.cnoe.io/v1alpha1
kind: AgentInteraction
metadata:
  name: test-health-check
  namespace: caipe-system
spec:
  agentName: platform-engineer-enhanced
  query: "Check the health of all pods in the default namespace and identify any issues"
  waitForCompletion: true
EOF

# Watch the interaction
kubectl get agentinteraction test-health-check -n caipe-system -w

# Get results
kubectl get agentinteraction test-health-check -n caipe-system -o jsonpath='{.status.response}' | jq .
```

### **Step 5.3: Configure Scheduled Monitoring**

Create a CronJob for periodic cluster health checks:

```yaml
# ~/caipe-lab/scheduled-monitoring.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: caipe-health-check
  namespace: caipe-system
spec:
  schedule: "*/15 * * * *"  # Every 15 minutes
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: caipe-monitor
          containers:
          - name: trigger
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl create -f - <<EOF
              apiVersion: caipe.cnoe.io/v1alpha1
              kind: AgentInteraction
              metadata:
                generateName: scheduled-health-check-
                namespace: caipe-system
              spec:
                agentName: platform-engineer-enhanced
                query: "Perform a comprehensive health check of the cluster. Check for pod failures, resource constraints, and OOM kills. Create Jira tickets for any critical issues found."
                timeout: 300s
              EOF
          restartPolicy: OnFailure
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: caipe-monitor
  namespace: caipe-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: caipe-monitor
  namespace: caipe-system
rules:
- apiGroups: ["caipe.cnoe.io"]
  resources: ["agentinteractions"]
  verbs: ["create", "get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: caipe-monitor
  namespace: caipe-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: caipe-monitor
subjects:
- kind: ServiceAccount
  name: caipe-monitor
  namespace: caipe-system
```

Deploy:

```bash
kubectl apply -f ~/caipe-lab/scheduled-monitoring.yaml

# Verify CronJob
kubectl get cronjobs -n caipe-system

# Trigger manually for testing
kubectl create job --from=cronjob/caipe-health-check manual-test -n caipe-system
kubectl logs -n caipe-system -l job-name=manual-test
```

---

## **✅ Phase 6: Testing & Validation (20 minutes)**

### **Step 6.1: Test Core CAIPE Functionality**

```bash
# 1. Test agent listing
kubectl get platformagents -A

# 2. Test MCP server connectivity
kubectl run test-mcp --rm -it --image=curlimages/curl --restart=Never -- \
  curl http://kubectl-mcp-server.caipe-system.svc.cluster.local:8080/health

# 3. Test agent query via API
kubectl run test-agent --rm -it --image=curlimages/curl --restart=Never -- \
  curl -X POST http://caipe-controller.caipe-system.svc.cluster.local:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"agent":"platform-engineer-enhanced","query":"List all pods in the default namespace"}'
```

### **Step 6.2: Test EKS Monitoring Integration**

```bash
# Create a test interaction for cluster health
kubectl create -f - <<EOF
apiVersion: caipe.cnoe.io/v1alpha1
kind: AgentInteraction
metadata:
  name: test-eks-monitoring
  namespace: caipe-system
spec:
  agentName: platform-engineer-enhanced
  query: |
    Use the eks-monitoring tool to:
    1. Check cluster health for all namespaces
    2. Identify any pods in CrashLoopBackOff or Error state
    3. Provide cost optimization recommendations
  timeout: 180s
EOF

# Wait for completion
kubectl wait --for=condition=complete --timeout=300s agentinteraction/test-eks-monitoring -n caipe-system

# Get results
kubectl get agentinteraction test-eks-monitoring -n caipe-system -o yaml
```

### **Step 6.3: Test OnCall Troubleshooting**

```bash
# Simulate an incident
kubectl run failing-pod --image=busybox --restart=Never -- sh -c "exit 1"

# Wait for pod to fail
sleep 10

# Create troubleshooting interaction
kubectl create -f - <<EOF
apiVersion: caipe.cnoe.io/v1alpha1
kind: AgentInteraction
metadata:
  name: test-oncall
  namespace: caipe-system
spec:
  agentName: platform-engineer-enhanced
  query: |
    Use the oncall-troubleshooting tool to investigate why the pod 'failing-pod'
    in the default namespace failed. Provide root cause analysis and remediation steps.
  timeout: 180s
EOF

# Get results
kubectl wait --for=condition=complete --timeout=300s agentinteraction/test-oncall -n caipe-system
kubectl get agentinteraction test-oncall -n caipe-system -o jsonpath='{.status.response}' | jq .

# Cleanup
kubectl delete pod failing-pod
```

### **Step 6.4: Test Backstage Integration**

1. Open Backstage: https://backstage.cnoe.localtest.me:8443
2. Navigate to "CAIPE" tab in the sidebar
3. Select "platform-engineer-enhanced" agent
4. Send a test query: "What is the current cluster status?"
5. Verify you get a response with cluster information

### **Step 6.5: Validate Safety Constraints**

```bash
# Test that dangerous operations are blocked
kubectl create -f - <<EOF
apiVersion: caipe.cnoe.io/v1alpha1
kind: AgentInteraction
metadata:
  name: test-safety
  namespace: caipe-system
spec:
  agentName: platform-engineer-enhanced
  query: "Delete the kube-system namespace"
  timeout: 60s
EOF

# Should fail with safety constraint violation
kubectl get agentinteraction test-safety -n caipe-system -o jsonpath='{.status.error}'

# Expected: "Operation blocked by safety constraints: forbidden operation 'delete namespace kube-system'"
```

---

## **🚀 Phase 7: Production Readiness (Optional)**

### **Step 7.1: Configure Observability**

```bash
# Deploy Prometheus for metrics
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/bundle.yaml

# Deploy Grafana for visualization
kubectl apply -f https://raw.githubusercontent.com/grafana-operator/grafana-operator/master/deploy/manifests/latest/grafana-operator.yaml

# Configure CAIPE metrics scraping
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: caipe-controller
  namespace: caipe-system
spec:
  selector:
    matchLabels:
      app: caipe-controller
  endpoints:
  - port: metrics
    interval: 30s
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: mcp-servers
  namespace: caipe-system
spec:
  selector:
    matchLabels:
      app.kubernetes.io/component: mcp-server
  endpoints:
  - port: metrics
    interval: 30s
EOF
```

### **Step 7.2: Configure Alerting**

```yaml
# ~/caipe-lab/caipe-alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: caipe-alerts
  namespace: caipe-system
spec:
  groups:
  - name: caipe
    interval: 30s
    rules:
    - alert: CAIPEAgentDown
      expr: up{job="caipe-controller"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "CAIPE controller is down"
        description: "CAIPE controller has been down for more than 5 minutes"

    - alert: MCPServerDown
      expr: up{job=~".*-mcp-server"} == 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "MCP server {{ $labels.job }} is down"

    - alert: HighAgentErrorRate
      expr: rate(caipe_agent_errors_total[5m]) > 0.1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High error rate for agent {{ $labels.agent }}"
        description: "Error rate is {{ $value }} errors/sec"

    - alert: LLMAPIRateLimited
      expr: rate(caipe_llm_rate_limit_errors_total[5m]) > 0
      for: 1m
      labels:
        severity: warning
      annotations:
        summary: "LLM API rate limiting detected"
```

### **Step 7.3: Backup & Disaster Recovery**

```bash
# Backup CAIPE configuration
kubectl get platformagents -A -o yaml > ~/caipe-backup/agents.yaml
kubectl get agentinteractions -A -o yaml > ~/caipe-backup/interactions.yaml
kubectl get secrets -n caipe-system -o yaml > ~/caipe-backup/secrets.yaml

# Create restore script
cat > ~/caipe-backup/restore.sh <<'EOF'
#!/bin/bash
kubectl apply -f secrets.yaml
kubectl apply -f agents.yaml
kubectl apply -f interactions.yaml
EOF
chmod +x ~/caipe-backup/restore.sh
```

---

## **🔍 Troubleshooting Guide**

### **Common Issues**

#### **0. idpbuilder Command Flag Errors**

**Symptoms:**
- `Error: unknown flag: --package-dir`
- `Error: unknown flag: --build-name`

**Cause:**
You're using an older version of idpbuilder (< v0.10.0) or following outdated documentation.

**Solutions:**

```bash
# Check your idpbuilder version
idpbuilder version

# If version is < v0.10.1, update it
# macOS (Homebrew)
brew upgrade cnoe-io/tap/idpbuilder

# Or download latest manually
version=$(curl -Ls -o /dev/null -w %{url_effective} https://github.com/cnoe-io/idpbuilder/releases/latest)
version=${version##*/}
curl -L -o ./idpbuilder.tar.gz "https://github.com/cnoe-io/idpbuilder/releases/download/${version}/idpbuilder-darwin-arm64.tar.gz"
tar xvzf idpbuilder.tar.gz
sudo mv idpbuilder /usr/local/bin/

# Flag changes in v0.10.1:
# OLD: --package-dir → NEW: --package or -p
# OLD: --build-name → NEW: --name
```

#### **1. CAIPE Package Path Not Found**

**Symptoms:**
- `Error: getting yaml files from repo... no such file or directory`
- References to `ai-platform-engineering//examples/basic-setup`

**Cause:**
The CAIPE package path changed. The old path was in the `ai-platform-engineering` repository, but it's now in the `stacks` repository.

**Solutions:**

```bash
# INCORRECT (old path):
--package https://github.com/cnoe-io/ai-platform-engineering//examples/basic-setup

# CORRECT (new path):
--package https://github.com/cnoe-io/stacks//caipe/base
# Or: --package https://github.com/cnoe-io/stacks//caipe/complete
# Or: --package https://github.com/cnoe-io/stacks//caipe/complete-slim
```

#### **2. CAIPE Agent Pods Failing to Start**

**Symptoms:**
- Pods in `CreateContainerConfigError` state
- Error: `secret "llm-secret" not found`
- All agent pods stuck at 0/1 Ready

**Cause:**
CAIPE requires LLM provider credentials that must be configured in Vault.

**Solutions:**

See **Step 2.5: Configure LLM Provider Credentials** for complete instructions. Quick fix:

```bash
# 1. Get Vault token
export VAULT_ROOT_TOKEN=$(kubectl get secret -n vault vault-root-token \
  --context kind-caipe-local -o jsonpath='{.data.token}' | base64 -d)

# 2. Configure Anthropic in Vault
kubectl exec -n vault vault-0 --context kind-caipe-local -- sh -c "
export VAULT_TOKEN=$VAULT_ROOT_TOKEN
export VAULT_SKIP_VERIFY=true
vault kv put secret/ai-platform-engineering/global \
  LLM_PROVIDER=anthropic-claude \
  ANTHROPIC_API_KEY=your-api-key-here \
  ANTHROPIC_MODEL_NAME=claude-sonnet-4-20250514
"

# 3. Update ExternalSecret and restart (see Step 2.5.3-2.5.4)
```

#### **3. MCP Server Connection Failures**

**Symptoms:**
- Agent returns "Failed to connect to MCP server"
- Tools not available

**Solutions:**

```bash
# Check MCP server pod status
kubectl get pods -n caipe-system -l app.kubernetes.io/component=mcp-server

# Check MCP server logs
kubectl logs -n caipe-system -l app=kubectl-mcp-server --tail=100

# Test connectivity from agent pod
kubectl exec -it -n caipe-system deployment/caipe-controller -- \
  curl http://kubectl-mcp-server.caipe-system.svc.cluster.local:8080/health

# Restart MCP server
kubectl rollout restart deployment/kubectl-mcp-server -n caipe-system
```

#### **2. API Key Issues**

**Symptoms:**
- "Invalid API key" errors
- 401 Unauthorized responses

**Solutions:**

```bash
# Verify secret exists
kubectl get secret anthropic-api-key -n caipe-system

# Update API key
kubectl create secret generic anthropic-api-key \
  --from-literal=api-key="YOUR_NEW_API_KEY" \
  -n caipe-system \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart agent to pick up new key
kubectl rollout restart deployment/caipe-controller -n caipe-system
```

#### **3. Agent Not Responding**

**Symptoms:**
- AgentInteraction stuck in "Pending" state
- No response after timeout

**Solutions:**

```bash
# Check controller logs
kubectl logs -n caipe-system deployment/caipe-controller --tail=200

# Check for resource constraints
kubectl top pods -n caipe-system

# Increase timeout
kubectl patch agentinteraction test-query -n caipe-system --type=merge -p '{"spec":{"timeout":"600s"}}'

# Check LLM API rate limits
kubectl logs -n caipe-system deployment/caipe-controller | grep "rate_limit"
```

#### **4. Backstage Plugin Not Loading**

**Symptoms:**
- CAIPE tab not visible in Backstage
- "Plugin failed to load" error

**Solutions:**

```bash
# Verify Backstage configuration
kubectl get configmap backstage-app-config -n backstage -o yaml | grep -A 20 caipe

# Check Backstage logs
kubectl logs -n backstage deployment/backstage --tail=100

# Restart Backstage
kubectl rollout restart deployment/backstage -n backstage

# Clear browser cache and reload
```

#### **5. Getting 404 Not Found When Accessing Services**

**Symptoms:**
- Browser shows "404 Not Found" from nginx
- Trying to access `https://backstage.cnoe.localtest.me:8443`
- Trying to access `https://argocd.cnoe.localtest.me:8443`

**Cause:**
All services (except Vault) use **path-based routing** on the same domain `cnoe.localtest.me:8443`, not subdomain-based routing.

**Solutions:**

```bash
# ❌ INCORRECT URLs (subdomain-based):
https://backstage.cnoe.localtest.me:8443  # 404 error
https://argocd.cnoe.localtest.me:8443     # 404 error
https://gitea.cnoe.localtest.me:8443      # 404 error

# ✅ CORRECT URLs (path-based):
https://cnoe.localtest.me:8443                        # Backstage (root path)
https://cnoe.localtest.me:8443/argocd                 # ArgoCD
https://cnoe.localtest.me:8443/gitea                  # Gitea
https://cnoe.localtest.me:8443/keycloak               # Keycloak
https://cnoe.localtest.me:8443/argo-workflows         # Argo Workflows
https://cnoe.localtest.me:8443/ai-platform-engineering # AI Platform
https://vault.cnoe.localtest.me:8443                  # Vault (exception - uses subdomain)

# Verify ingress paths
kubectl get ingress --all-namespaces --context kind-caipe-local
```

**Quick Test:**
```bash
# Test Backstage (should return HTML)
curl -k -s https://cnoe.localtest.me:8443 | head -5

# Test ArgoCD (should return HTML or redirect)
curl -k -s https://cnoe.localtest.me:8443/argocd

# Test Gitea (should return HTML)
curl -k -s https://cnoe.localtest.me:8443/gitea
```

#### **6. Safety Constraints Too Restrictive**

**Symptoms:**
- Legitimate operations being blocked
- "Operation blocked by safety constraints" errors

**Solutions:**

```bash
# Review agent constraints
kubectl get platformagent platform-engineer-enhanced -n caipe-system -o jsonpath='{.spec.constraints}' | jq .

# Update constraints (add more allowed namespaces, etc.)
kubectl edit platformagent platform-engineer-enhanced -n caipe-system

# Or apply updated YAML
kubectl apply -f ~/caipe-lab/platform-engineer-agent-with-custom-tools.yaml
```

---

## **💰 Cost Optimization**

### **Estimated Monthly Costs (Local Laptop Deployment)**

| Component | Usage | Cost |
|-----------|-------|------|
| **Anthropic API** | ~500K tokens/day (monitoring) | $15-30/month |
| **Anthropic API** | ~100K tokens/day (interactive) | $3-10/month |
| **Total Cloud Costs** | | **$18-40/month** |

**Local Infrastructure:** FREE (runs on your laptop)

### **Cost Reduction Strategies**

1. **Use Haiku for Simple Tasks:**

```yaml
# Update agent to use Haiku for diagnostics, Sonnet for complex analysis
llm:
  provider: "anthropic"
  model: "claude-haiku-3-5-20250307"  # Cheaper for simple queries

  # Override per interaction
  modelOverrides:
    complex_analysis: "claude-sonnet-4-20250514"
    simple_queries: "claude-haiku-3-5-20250307"
```

2. **Implement Caching:**

```python
# Add caching to reduce duplicate LLM calls
from functools import lru_cache

@lru_cache(maxsize=100)
def cached_cluster_health_check(cluster_name: str, timestamp_hour: int):
    # Cache results for 1 hour
    pass
```

3. **Reduce Monitoring Frequency:**

```yaml
# Change from 15 minutes to 30 minutes
schedule: "*/30 * * * *"
```

4. **Batch Queries:**

```python
# Instead of separate queries per namespace, batch them
query = """
Check health for these namespaces in a single analysis:
- default
- caipe-system
- backstage
"""
```

---

## **📚 Next Steps**

### **Immediate (Week 1)**

1. ✅ Complete local deployment
2. ✅ Test all agent interactions
3. ✅ Validate safety constraints
4. 📖 Read CAIPE documentation thoroughly
5. 🧪 Experiment with different queries and tools

### **Short-term (Weeks 2-4)**

1. **Extend Agents:**
   - Add more specialized MCP servers (Prometheus, GitHub Actions, etc.)
   - Create domain-specific agents (security, compliance, etc.)

2. **Integrate External Systems:**
   - Connect to Slack for notifications
   - Integrate with PagerDuty for incident management
   - Connect to Jira for ticket automation

3. **Build Custom Workflows:**
   - Create runbooks as AgentWorkflow CRDs
   - Automate common operational tasks
   - Build approval workflows for sensitive operations

### **Long-term (Months 2-3)**

1. **Production Deployment:**
   - Deploy to EKS cluster (not just local)
   - Set up multi-cluster monitoring
   - Implement HA for CAIPE controller

2. **Advanced Features:**
   - Multi-agent collaboration (orchestrator + specialists)
   - Learning from past interactions
   - Autonomous remediation with approval gates

3. **Governance:**
   - Audit logging for all agent actions
   - RBAC for agent access
   - Cost tracking and budgets

---

## **🔗 Additional Resources**

### **Documentation**

- [CAIPE GitHub](https://github.com/cnoe-io/ai-platform-engineering)
- [CNOE idpbuilder](https://github.com/cnoe-io/idpbuilder)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/python)
- [Anthropic API Docs](https://docs.anthropic.com/)

### **Example Repositories**

- [CAIPE Examples](https://github.com/cnoe-io/ai-platform-engineering/tree/main/examples)
- [MCP Servers Collection](https://github.com/modelcontextprotocol/servers)
- [Backstage CAIPE Plugin](https://github.com/cnoe-io/backstage-plugins)

### **Community**

- [CNOE Slack](https://cloud-native.slack.com/archives/C05TN9WFN5S)
- [CAIPE Discussions](https://github.com/cnoe-io/ai-platform-engineering/discussions)
- [Anthropic Discord](https://discord.gg/anthropic)

---

## **📝 Summary Checklist**

Use this checklist to track your implementation progress:

- [ ] **Phase 1:** Environment Setup
  - [ ] Docker Desktop installed and configured
  - [ ] kubectl installed and working
  - [ ] Docker resources allocated (8GB+ RAM, 4+ CPUs)

- [ ] **Phase 2:** CNOE IDP Deployment
  - [ ] idpbuilder downloaded and installed
  - [ ] CNOE stack deployed (ArgoCD, Backstage, Gitea, Keycloak, CAIPE base)
  - [ ] All applications synced and healthy
  - [ ] Backstage accessible at https://backstage.cnoe.localtest.me:8443
  - [ ] LLM provider credentials configured in Vault
  - [ ] ExternalSecret updated with ANTHROPIC keys
  - [ ] CAIPE agent pods running (1/1 Ready)

- [ ] **Phase 3:** CAIPE Components (Skip if deployed via Step 2.2)
  - [ ] CAIPE repository cloned
  - [ ] CAIPE CRDs deployed
  - [ ] CAIPE controller running
  - [ ] Sample MCP servers deployed
  - [ ] First PlatformAgent created and running

- [ ] **Phase 4:** Custom Agent Integration
  - [ ] EKS monitoring MCP adapter created
  - [ ] OnCall troubleshooting MCP adapter created
  - [ ] Custom MCP servers deployed to Kubernetes
  - [ ] Platform agent updated with custom tools

- [ ] **Phase 5:** Claude Integration
  - [ ] Backstage plugin configured
  - [ ] Test interactions successful
  - [ ] Scheduled monitoring configured
  - [ ] Safety constraints validated

- [ ] **Phase 6:** Testing & Validation
  - [ ] Core CAIPE functionality tested
  - [ ] EKS monitoring integration tested
  - [ ] OnCall troubleshooting tested
  - [ ] Backstage UI tested
  - [ ] Safety constraints validated

- [ ] **Phase 7:** Production Readiness (Optional)
  - [ ] Observability configured (Prometheus, Grafana)
  - [ ] Alerting rules deployed
  - [ ] Backup strategy implemented

---

## **🎯 Success Criteria**

Your CAIPE deployment is successful when:

1. ✅ You can interact with agents via Backstage UI
2. ✅ Scheduled monitoring runs every 15 minutes without errors
3. ✅ Agent can successfully execute kubectl, ArgoCD, and custom tools
4. ✅ Safety constraints block dangerous operations
5. ✅ All MCP servers are healthy and responsive
6. ✅ Interactive troubleshooting sessions work end-to-end
7. ✅ Agent responses are helpful and contextually relevant
8. ✅ Token usage is within expected budget (~500K/day for monitoring)

---

**Good luck with your CAIPE deployment! 🚀**

For questions or issues, please refer to the [Troubleshooting Guide](#troubleshooting-guide) or reach out to the CNOE community on Slack.
