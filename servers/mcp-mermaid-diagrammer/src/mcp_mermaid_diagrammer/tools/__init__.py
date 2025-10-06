# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/tools/__init__.py# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/tools/__init__.py
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .mermaid_generate import register_mermaid_generate

def register(mcp: FastMCP) -> None:
    register_mermaid_generate(mcp)
