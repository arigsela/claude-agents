#!/usr/bin/env python3
"""Test MCP server directly"""
import asyncio
import subprocess
import json

async def test_mcp_server():
    """Test if MCP server responds to initialize"""

    # Start the MCP server
    proc = subprocess.Popen(
        ["./bin/run-kubernetes-mcp.sh"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Send initialize request
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"}
        },
        "id": 1
    }

    print("Sending initialize request...")
    proc.stdin.write(json.dumps(init_request) + "\n")
    proc.stdin.flush()

    # Wait for response (with timeout)
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(proc.stdout.readline),
            timeout=5.0
        )
        print(f"Response: {response}")

        # Read stderr
        stderr = proc.stderr.read()
        if stderr:
            print(f"Stderr: {stderr}")

    except asyncio.TimeoutError:
        print("TIMEOUT - no response from MCP server")
        stderr = proc.stderr.read()
        if stderr:
            print(f"Stderr: {stderr}")
    finally:
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    asyncio.run(test_mcp_server())
