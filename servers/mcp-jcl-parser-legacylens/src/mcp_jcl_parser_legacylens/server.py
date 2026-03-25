# servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/server.py
from __future__ import annotations

import logging
from mcp.server.fastmcp import FastMCP

from .settings import Settings
from .tools.parse_repo import register_tool
from .resources.run_info import register_run_info_resources
from .resources.file_preview import register_file_preview_resources
from .resources.artifact_preview import register_artifact_preview_resources
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger("mcp.jcl.server")

allowed_hosts = os.getenv("ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,host.docker.internal:*,*").split(",")
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*,http://host.docker.internal:*,*").split(",")

# Single FastMCP instance
mcp = FastMCP(
    "mcp.mermaid.server",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    ),
)

# Register tools & resources
register_tool(mcp)
register_run_info_resources(mcp)
register_file_preview_resources(mcp)
register_artifact_preview_resources(mcp)

# Eager settings init for visibility
try:
    _ = Settings()
except Exception as e:
    logger.warning("Settings initialization warning: %s", e)

# Pretty startup log (if supported)
try:
    @mcp.on_startup  # type: ignore[attr-defined]
    async def _on_startup() -> None:
        logger.info(
            "JCL LegacyLens FastMCP is up. Tools: %s | Resources: %s",
            [t.name for t in mcp.tools],
            [r.name for r in mcp.resources],
        )
except Exception:
    pass