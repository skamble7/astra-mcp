# File: servers/mcp-cobol-parser/mcp_cobol_parser/server.py
from __future__ import annotations

import logging
from mcp.server.fastmcp import FastMCP

from .settings import Settings
from .tools.parse_repo import register_tool
from .resources.run_info import register_run_info_resources
from .resources.file_preview import register_file_preview_resources
from .resources.artifact_preview import register_artifact_preview_resources

logger = logging.getLogger("mcp.cobol.server")

# Create a single FastMCP instance. The official SDK runner (__main__.py) will run it
# via streamable HTTP (or stdio) based on MCP_TRANSPORT and other env vars.
mcp = FastMCP("mcp.cobol.parser")

# Register tools & resources (keeps the same navigation behavior as before)
register_tool(mcp)
register_run_info_resources(mcp)
register_file_preview_resources(mcp)
register_artifact_preview_resources(mcp)

# Eagerly load Settings once for visibility (cache dir, jar existence, etc.)
try:
    _ = Settings()
except Exception as e:
    logger.warning("Settings initialization warning: %s", e)

# Nice startup log (supported in mcp>=1.x; guarded for older builds)
try:
    @mcp.on_startup  # type: ignore[attr-defined]
    async def _on_startup() -> None:
        logger.info(
            "COBOL parser FastMCP is up. Tools: %s | Resources: %s",
            [t.name for t in mcp.tools],
            [r.name for r in mcp.resources],
        )
except Exception:
    pass