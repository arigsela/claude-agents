#!/usr/bin/env python3
"""
Minimal Kubernetes MCP Server using low-level Server API
Provides kubectl-based Kubernetes operations via MCP protocol
"""
import asyncio
import sys
import subprocess
import json
from mcp.server.stdio import stdio_server
from mcp.server import Server
from mcp.types import Tool, TextContent

# Create server
app = Server("kubernetes-mcp")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available Kubernetes tools"""
    return [
        Tool(
            name="kubernetes_pods_list",
            description="List pods in a namespace or across all namespaces",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Namespace to list pods from (optional)"
                    }
                }
            }
        ),
        Tool(
            name="kubernetes_pods_get",
            description="Get details of a specific pod",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"}
                },
                "required": ["name", "namespace"]
            }
        ),
        Tool(
            name="kubernetes_pods_logs",
            description="Get logs from a pod",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "namespace": {"type": "string"},
                    "tail": {"type": "integer", "default": 100}
                },
                "required": ["name", "namespace"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute Kubernetes operations"""

    if name == "kubernetes_pods_list":
        namespace = arguments.get("namespace")
        cmd = ["kubectl", "get", "pods", "-o", "json"]
        if namespace:
            cmd.extend(["-n", namespace])
        else:
            cmd.append("--all-namespaces")

    elif name == "kubernetes_pods_get":
        cmd = ["kubectl", "get", "pod", arguments["name"],
               "-n", arguments["namespace"], "-o", "json"]

    elif name == "kubernetes_pods_logs":
        tail = arguments.get("tail", 100)
        cmd = ["kubectl", "logs", arguments["name"],
               "-n", arguments["namespace"], f"--tail={tail}"]
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return [TextContent(type="text", text=result.stdout)]
    except subprocess.CalledProcessError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e), "stderr": e.stderr}))]

async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
