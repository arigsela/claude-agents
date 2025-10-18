"""
On-Call Troubleshooting Agent
Main agent implementation using Claude Agent SDK
"""

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    tool,
    create_sdk_mcp_server
)
import asyncio
import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

# Import custom tools
from tools.k8s_analyzer import analyze_deployment, correlate_events, suggest_fix

# Import API custom tools (Python library based)
try:
    from api.custom_tools import (
        list_pods,
        get_pod_logs,
        get_pod_events,
        get_deployment_status,
        list_services,
        search_recent_deployments,
        get_recent_commits,
        check_secrets_manager,
        check_ecr_image,
        analyze_service_health,
        correlate_deployment_with_incidents
    )
    API_CUSTOM_TOOLS_AVAILABLE = True
except ImportError:
    API_CUSTOM_TOOLS_AVAILABLE = False
    logger.warning("API custom tools not available (api.custom_tools not found)")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


class OnCallTroubleshootingAgent:
    """
    Main on-call troubleshooting agent for ArtemisHealth DevOps.

    Responsibilities:
    - Monitor and analyze Kubernetes events in dev-eks cluster
    - Correlate incidents with recent GitHub deployments
    - Provide actionable remediation steps
    """

    # Tool name constants for maintainability
    K8S_TOOLS = [
        "list_pods",
        "describe_pod",
        "get_events",
        "get_logs",
        "list_deployments",
    ]

    GITHUB_TOOLS = [
        "list_workflow_runs",
        "get_workflow_run",
        "search_issues",
    ]

    CUSTOM_TOOLS = [
        # Original analysis tools
        "analyze_deployment",
        "correlate_events",
        "suggest_fix",
        # New Python library tools (added when API_CUSTOM_TOOLS_AVAILABLE)
        "list_pods",
        "get_pod_logs",
        "get_pod_events",
        "get_deployment_status",
        "list_services",
        "search_recent_deployments",
        "get_recent_commits",
        "check_secrets_manager",
        "check_ecr_image",
        "analyze_service_health",
        "correlate_deployment_with_incidents"
    ]

    BASIC_TOOLS = [
        "Read",
        "Write",
        "Bash",
        "WebSearch",
    ]

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the on-call troubleshooting agent.

        Args:
            config_path: Optional path to configuration directory
        """
        # Load environment variables
        load_dotenv()

        # Set configuration path
        self.config_path = Path(config_path) if config_path else Path(__file__).parent.parent.parent / "config"
        self.project_root = Path(__file__).parent.parent.parent

        # Load configurations
        self.mcp_config = self._load_mcp_config()
        self.monitoring_config = self._load_monitoring_config()

        # Initialize agent options
        self.options = ClaudeAgentOptions(
            system_prompt=self._get_system_prompt(),
            mcp_servers=self._configure_mcp_servers(),
            allowed_tools=self._get_allowed_tools(),
            permission_mode="acceptEdits",
            cwd=str(self.project_root)
        )

        # Initialize SDK client
        self.client = ClaudeSDKClient(self.options)

        logger.info("OnCallTroubleshootingAgent initialized")
        logger.info(f"Project root: {self.project_root}")
        logger.info(f"Config path: {self.config_path}")

    def _load_mcp_config(self) -> Dict:
        """Load MCP server configuration from config/mcp_servers.json"""
        config_file = self.config_path / "mcp_servers.json"
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"MCP config not found at {config_file}, using defaults")
            return {}

    def _load_monitoring_config(self) -> Dict:
        """Load K8s monitoring configuration from config/k8s_monitoring.yaml"""
        import yaml
        config_file = self.config_path / "k8s_monitoring.yaml"
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning(f"Monitoring config not found at {config_file}, using defaults")
            return {}
        except ImportError:
            logger.error("PyYAML not installed. Install with: pip install pyyaml")
            return {}

    def _get_system_prompt(self) -> str:
        """Generate system prompt with ArtemisHealth-specific context"""
        # Get service criticality from monitoring config
        service_criticality = self.monitoring_config.get('monitoring', {}).get('service_criticality', {})

        return f"""
        You are an expert on-call troubleshooting agent for ArtemisHealth's
        DevOps team. Your responsibilities include:

        1. Monitoring and analyzing Kubernetes events in the dev-eks cluster
        2. Correlating incidents with recent deployments via GitHub Actions
        3. Providing actionable remediation steps

        ## Key Context

        **Organization:** artemishealth (GitHub)
        **Deployment Tool:** Deploy GHA (manages PRs to deployments repo)
        **Kubernetes Context:** dev-eks (NEVER modify prod-eks without explicit confirmation)

        **Protected Clusters:** prod-eks, staging-eks
        **Allowed Clusters:** dev-eks only

        ## Service Criticality Mapping

        **Critical Services:** {service_criticality.get('critical', [])}
        - Require immediate response
        - Teams notifications sent immediately

        **High Priority Services:** {service_criticality.get('high', [])}
        - Require rapid response
        - Monitored for escalation

        **Medium Priority Services:** {service_criticality.get('medium', [])}
        - Queue for review
        - Manual escalation if needed

        **Low Priority Services:** {service_criticality.get('low', [])}
        - Document and learn
        - No immediate action required

        ## Troubleshooting Workflow

        When you receive an incident alert:

        1. **Triage**: Determine severity based on error type, restart count, service criticality
        2. **Diagnose**:
           - Check recent Kubernetes events in the affected namespace
           - Review pod logs for error patterns
           - Check resource utilization (CPU, memory)
        3. **Correlate**:
           - Query recent GitHub Actions workflow runs
           - Match deployment timestamps with incident start time
           - Check for recent configuration changes
        4. **Remediate**:
           - Provide clear, actionable steps
           - Suggest rollback if deployment-related
           - Send Teams notifications for critical incidents

        ## Safety Rules

        - NEVER take actions on prod-eks without explicit human confirmation
        - ALWAYS validate cluster context before any write operation
        - PROVIDE rollback recommendations with ≥0.8 confidence threshold
        - GitOps workflow: recommendations only, no automated rollbacks
        - ESCALATE to human for all critical incidents and deployment actions

        ## Available Tools

        You have access to these custom tools using Python libraries (NOT kubectl CLI):

        **Kubernetes Tools** (using kubernetes Python library):
        - list_pods: List pods in namespace with status and restart counts
        - get_pod_logs: Retrieve pod logs (last N lines)
        - get_pod_events: Get K8s events for troubleshooting
        - get_deployment_status: Check deployment health
        - list_services: List Services with their label selectors (supports filtering by specific labels)

        **GitHub Tools** (using PyGithub):
        - search_recent_deployments: Find recent workflow runs
        - get_recent_commits: Get commit history

        **AWS Tools** (using boto3):
        - check_secrets_manager: Verify secrets exist
        - check_ecr_image: Check container images

        **Analysis Tools**:
        - analyze_service_health: Comprehensive service health check
        - correlate_deployment_with_incidents: Link K8s issues to deployments
        - analyze_deployment, correlate_events, suggest_fix: Original analysis tools

        These tools use DIRECT PYTHON APIs - no kubectl or bash commands needed!

        Use these tools to gather information, diagnose issues, and provide
        actionable recommendations to the DevOps team.
        """

    def _configure_mcp_servers(self) -> Dict:
        """
        Configure MCP servers for K8s, GitHub, Memory, and custom tools.

        Loads server definitions from config/mcp_servers.json and merges
        with custom tools server.
        """
        # Start with servers from config file
        servers = self.mcp_config.get('mcpServers', {}).copy()

        # Add custom tools server
        servers['custom_tools'] = self._create_custom_tools()

        logger.info(f"Configured {len(servers)} MCP servers: {list(servers.keys())}")
        return servers

    def _create_custom_tools(self):
        """
        Create custom MCP server with agent-specific tools.

        Registers custom tools using Python libraries (kubernetes, PyGithub, boto3)
        instead of CLI commands for better reliability and performance.
        """
        # Start with original custom tools
        tool_list = [
            analyze_deployment,
            correlate_events,
            suggest_fix
        ]

        # Add API custom tools if available (Python library based)
        if API_CUSTOM_TOOLS_AVAILABLE:
            tool_list.extend([
                list_pods,
                get_pod_logs,
                get_pod_events,
                get_deployment_status,
                list_services,
                search_recent_deployments,
                get_recent_commits,
                check_secrets_manager,
                check_ecr_image,
                analyze_service_health,
                correlate_deployment_with_incidents
            ])
            logger.info(f"Registered {len(tool_list)} custom tools (including API Python library tools)")
        else:
            logger.info(f"Registered {len(tool_list)} custom tools (API tools not available)")

        return create_sdk_mcp_server(
            name="oncall_tools",
            version="1.0.0",
            tools=tool_list
        )

    def _get_allowed_tools(self) -> List[str]:
        """Define allowed tools for agent operations"""
        # Build tool lists with proper MCP prefixes
        k8s_tools = [f"mcp__kubernetes__{tool}" for tool in self.K8S_TOOLS]
        github_tools = [f"mcp__github__{tool}" for tool in self.GITHUB_TOOLS]
        custom_tools = [f"mcp__oncall_tools__{tool}" for tool in self.CUSTOM_TOOLS]

        return k8s_tools + github_tools + custom_tools + self.BASIC_TOOLS

    def _get_default_namespace(self) -> str:
        """
        Get default namespace for testing from monitoring config.

        Returns the first configured namespace, defaulting to 'default' if none found.
        """
        clusters = self.monitoring_config.get('monitoring', {}).get('clusters', [])
        if clusters and clusters[0].get('namespaces'):
            return clusters[0]['namespaces'][0]
        return 'default'

    async def handle_incident(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle an incident alert through the agent.

        Args:
            alert: Incident alert payload with service, error, pod info

        Returns:
            Agent's analysis and recommended actions
        """
        query = f"""
        Investigate the following Kubernetes incident:

        Service: {alert.get('service', 'unknown')}
        Namespace: {alert.get('namespace', 'default')}
        Error: {alert.get('error', 'unknown')}
        Pod: {alert.get('pod', 'unknown')}
        Restart Count: {alert.get('restart_count', 0)}

        Please:
        1. Check recent Kubernetes events for this service
        2. Review pod logs for error patterns
        3. Check for recent GitHub deployments that might have caused this
        4. Provide actionable remediation steps
        """

        logger.info(f"Handling incident for service: {alert.get('service')}")

        async with self.client as client:
            await client.query(query)

            response_parts = []
            async for message in client.receive_response():
                response_parts.append(message)

            return {
                "alert": alert,
                "agent_response": response_parts,
                "status": "analyzed"
            }

    async def query(self, prompt: str) -> List[Any]:
        """
        Send a query to the agent and receive response.

        Args:
            prompt: Query or instruction for the agent

        Returns:
            List of response messages from the agent
        """
        logger.info("=" * 60)
        logger.info(f"QUERY: {prompt}")
        logger.info("=" * 60)

        async with self.client as client:
            logger.info("Sending query to Claude Agent SDK...")
            await client.query(prompt)

            logger.info("Waiting for agent response...")
            responses = []
            message_count = 0

            async for message in client.receive_response():
                message_count += 1
                logger.info(f"Received message {message_count}: {type(message).__name__}")
                logger.debug(f"Message content: {message}")
                responses.append(message)

            logger.info(f"Query complete. Received {len(responses)} messages")
            logger.info("=" * 60)

            return responses


def _format_responses_for_human(responses: List[Any]) -> None:
    """
    Format agent responses for human readability.

    Extracts the actual content from SDK message objects and displays
    it in a clean, readable format.
    """
    for response in responses:
        response_type = type(response).__name__

        # SystemMessage - show initialization info
        if response_type == "SystemMessage":
            if hasattr(response, 'data'):
                mcp_servers = response.data.get('mcp_servers', [])
                connected = [s for s in mcp_servers if s.get('status') == 'connected']
                failed = [s for s in mcp_servers if s.get('status') == 'failed']

                print("🔌 MCP Server Status:")
                if connected:
                    print(f"   ✅ Connected: {', '.join(s['name'] for s in connected)}")
                if failed:
                    print(f"   ⚠️  Failed: {', '.join(s['name'] for s in failed)}")
                print()

        # AssistantMessage - show the actual agent response
        elif response_type == "AssistantMessage":
            if hasattr(response, 'content'):
                for content_block in response.content:
                    block_type = type(content_block).__name__

                    # TextBlock - the actual text response
                    if block_type == "TextBlock":
                        print(content_block.text)
                        print()

                    # ToolUseBlock - show what tool the agent is using
                    elif block_type == "ToolUseBlock":
                        tool_name = getattr(content_block, 'name', 'unknown')
                        tool_input = getattr(content_block, 'input', {})

                        print(f"🔧 Using tool: {tool_name}")
                        if 'description' in tool_input:
                            print(f"   Purpose: {tool_input['description']}")
                        if 'command' in tool_input:
                            print(f"   Command: {tool_input['command']}")
                        print()

        # UserMessage - tool results (usually internal)
        elif response_type == "UserMessage":
            # Skip tool results for cleaner output unless in debug mode
            if logger.level == logging.DEBUG:
                print(f"[DEBUG] Tool result received")

        # ResultMessage - final summary with metadata
        elif response_type == "ResultMessage":
            if hasattr(response, 'total_cost_usd'):
                print(f"\n💰 Cost: ${response.total_cost_usd:.4f}")

            if hasattr(response, 'duration_ms'):
                print(f"⏱️  Duration: {response.duration_ms/1000:.1f}s")

            if hasattr(response, 'num_turns'):
                print(f"🔄 Agent turns: {response.num_turns}")


def main() -> None:
    """
    CLI entry point for the on-call troubleshooting agent.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="On-Call Troubleshooting Agent for ArtemisHealth DevOps"
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run in development mode with verbose logging"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress INFO logs for cleaner output"
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration directory"
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Send a query to the agent"
    )
    parser.add_argument(
        "--incident",
        type=str,
        help="Path to JSON file with incident alert data"
    )

    args = parser.parse_args()

    # Set log level
    if args.dev:
        logging.getLogger().setLevel(logging.DEBUG)
        print("\n🔧 Development mode: Verbose logging enabled\n")
    elif args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # Initialize agent
    print("🚀 Initializing On-Call Troubleshooting Agent...")
    print()

    try:
        print("📂 Loading configurations...")
        agent = OnCallTroubleshootingAgent(config_path=args.config)

        print(f"✅ Agent initialized successfully")
        print(f"   - Config path: {agent.config_path}")
        print(f"   - Project root: {agent.project_root}")
        print(f"   - MCP servers: {list(agent.mcp_config.get('mcpServers', {}).keys())}")
        print(f"   - Allowed tools: {len(agent.options.allowed_tools)} tools")
        print()

        # Handle different modes
        if args.query:
            # Direct query mode
            asyncio.run(_run_query(agent, args.query))
        elif args.incident:
            # Incident handling mode
            asyncio.run(_run_incident_handler(agent, args.incident))
        else:
            # Interactive mode
            logger.info("Starting interactive mode...")
            asyncio.run(_run_interactive(agent))

    except Exception as e:
        logger.error(f"Failed to initialize agent: {e}")
        raise


async def _run_query(agent: OnCallTroubleshootingAgent, query: str) -> None:
    """Run a single query and print response in human-readable format"""
    print(f"\n{'='*60}")
    print(f"🔍 QUERY: {query}")
    print(f"{'='*60}\n")

    print("📡 Initializing agent connection...")
    print(f"📋 System prompt loaded ({len(agent.options.system_prompt)} chars)")
    print(f"🔧 MCP servers configured: {len(agent.mcp_config.get('mcpServers', {}))}")
    print(f"🛠️  Allowed tools: {len(agent.options.allowed_tools)}")
    print()

    print("⏳ Sending query to agent...\n")

    responses = await agent.query(query)

    print(f"\n{'='*60}")
    print(f"📨 AGENT RESPONSE")
    print(f"{'='*60}\n")

    # Parse and format responses for human readability
    _format_responses_for_human(responses)


async def _run_incident_handler(agent: OnCallTroubleshootingAgent, incident_file: str) -> None:
    """Handle an incident from JSON file"""
    print(f"\n{'='*60}")
    print(f"🚨 INCIDENT PROCESSING")
    print(f"{'='*60}\n")

    print(f"📄 Loading incident from: {incident_file}")
    with open(incident_file, 'r') as f:
        alert = json.load(f)

    print(f"\n📊 Incident Details:")
    print(f"   Service: {alert.get('service', 'unknown')}")
    print(f"   Namespace: {alert.get('namespace', 'unknown')}")
    print(f"   Error: {alert.get('error', 'unknown')}")
    print(f"   Restart Count: {alert.get('restart_count', 0)}")
    print(f"   Cluster: {alert.get('cluster', 'dev-eks')}")
    print()

    print("⏳ Sending to agent for analysis...\n")
    result = await agent.handle_incident(alert)

    print(f"\n{'='*60}")
    print(f"📋 ANALYSIS COMPLETE")
    print(f"{'='*60}\n")

    # Use consistent formatting
    _format_responses_for_human(result['agent_response'])


async def _run_interactive(agent: OnCallTroubleshootingAgent) -> None:
    """Run interactive mode"""
    print("\n" + "="*60)
    print("On-Call Troubleshooting Agent - Interactive Mode")
    print("="*60)
    print("\nType 'help' for available commands, 'quit' to exit\n")

    while True:
        try:
            user_input = input("oncall-agent> ").strip()

            if not user_input:
                continue

            if user_input.lower() in ['quit', 'exit']:
                print("\nShutting down agent...")
                break

            if user_input.lower() == 'help':
                print("""
Available commands:
  help              - Show this help message
  status            - Show agent status
  config            - Show current configuration
  test <service>    - Test with a sample incident
  query <text>      - Send a query to the agent
  quit/exit         - Exit the agent
                """)
                continue

            if user_input.lower() == 'status':
                print(f"Agent Status: Active")
                print(f"Config Path: {agent.config_path}")
                print(f"MCP Servers: {len(agent.mcp_config.get('mcpServers', {}))}")
                continue

            if user_input.lower() == 'config':
                print(json.dumps(agent.mcp_config, indent=2))
                continue

            if user_input.startswith('test '):
                service = user_input.split(' ', 1)[1]
                # Use namespace from config file
                default_namespace = agent._get_default_namespace()
                test_alert = {
                    "service": service,
                    "namespace": default_namespace,
                    "error": "CrashLoopBackOff",
                    "pod": f"{service}-test-pod",
                    "restart_count": 5
                }
                print(f"Testing with namespace: {default_namespace}")
                result = await agent.handle_incident(test_alert)
                _format_responses_for_human(result['agent_response'])
                continue

            # Default: treat as query
            responses = await agent.query(user_input)
            _format_responses_for_human(responses)

        except KeyboardInterrupt:
            print("\n\nInterrupted. Type 'quit' to exit.")
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
