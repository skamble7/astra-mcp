#!/usr/bin/env python3
"""Example Python client for STDIO MCP servers."""

import asyncio
import json
import subprocess
import sys
from typing import Any, Dict, Optional


class STDIOMCPClient:
    """Simple STDIO MCP client for conductor service integration."""
    
    def __init__(self, server_command: list[str]):
        self.server_command = server_command
        self.process: Optional[subprocess.Popen] = None
        self.request_id = 0
    
    async def start(self) -> None:
        """Start the MCP server process."""
        self.process = subprocess.Popen(
            self.server_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0
        )
    
    async def stop(self) -> None:
        """Stop the MCP server process."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
    
    async def send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request to the server."""
        if not self.process:
            raise RuntimeError("Server not started")
        
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params
        }
        
        # Send request
        request_json = json.dumps(request) + "\n"
        self.process.stdin.write(request_json)
        self.process.stdin.flush()
        
        # Read response
        response_line = self.process.stdout.readline()
        if not response_line:
            raise RuntimeError("No response from server")
        
        response = json.loads(response_line.strip())
        
        if "error" in response:
            raise RuntimeError(f"Server error: {response['error']}")
        
        return response.get("result", {})


async def example_git_repo_snapshot():
    """Example usage of the git-repo-snapshot server."""
    
    # Command to start the git-repo-snapshot server
    server_cmd = [
        "python", "-m", "mcp_git_repo_snapshot"
    ]
    
    client = STDIOMCPClient(server_cmd)
    
    try:
        print("Starting git-repo-snapshot server...")
        await client.start()
        
        # Initialize the server
        print("Initializing server...")
        await client.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "clientInfo": {
                "name": "conductor-service",
                "version": "1.0.0"
            }
        })
        
        # List available tools
        print("Listing available tools...")
        tools_result = await client.send_request("tools/list", {})
        print(f"Available tools: {[tool['name'] for tool in tools_result.get('tools', [])]}")
        
        # Clone a repository
        print("Cloning repository...")
        clone_result = await client.send_request("tools/call", {
            "name": "clone_repo",
            "arguments": {
                "repo_url": "https://github.com/octocat/Hello-World.git",
                "volume_path": "/tmp/mcp_repos",
                "branch": "master",
                "depth": 1
            }
        })
        
        print("Clone result:")
        print(json.dumps(clone_result, indent=2))
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
    
    finally:
        print("Stopping server...")
        await client.stop()


if __name__ == "__main__":
    asyncio.run(example_git_repo_snapshot())