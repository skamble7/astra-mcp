from __future__ import annotations
import logging
from mcp.server.fastmcp import FastMCP
from .tools import register as register_tools

logger = logging.getLogger("mcp.mermaid.server")

# Create the FastMCP instance at module scope (like your git server)
mcp = FastMCP("mermaid-diagrammer")

# Register tools once at import time
register_tools(mcp)

# Optional: startup log
try:
    @mcp.on_startup  # type: ignore[attr-defined]
    async def _on_start() -> None:
        logger.info("FastMCP mermaid-diagrammer started with tools: %s", [t.name for t in mcp.tools])
except Exception:
    pass