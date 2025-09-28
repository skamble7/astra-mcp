#!/usr/bin/env python3
"""Example Python client for SSE MCP servers."""

import asyncio
import json
from typing import Any, Dict

try:
    import httpx
except ImportError:
    print("httpx is required for SSE client. Install with: pip install httpx")
    exit(1)


class SSEMCPClient:
    """Simple SSE MCP client for conductor service integration."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient()
        self.request_id = 0
    
    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a JSON-RPC request to the server."""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params
        }
        
        response = await self.client.post(
            f"{self.base_url}/mcp",
            json=request,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        
        result = response.json()
        
        if "error" in result:
            raise RuntimeError(f"Server error: {result['error']}")
        
        return result.get("result", {})
    
    async def health_check(self) -> Dict[str, Any]:
        """Check server health."""
        response = await self.client.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()


async def example_git_repo_snapshot_sse():
    """Example usage of the git-repo-snapshot server via SSE."""
    
    client = SSEMCPClient("http://localhost:8000")
    
    try:
        # Check server health
        print("Checking server health...")
        health = await client.health_check()
        print(f"Server status: {health}")
        
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
        
    except httpx.RequestError as e:
        print(f"HTTP request error: {e}")
    except Exception as e:
        print(f"Error: {e}")
    
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(example_git_repo_snapshot_sse())