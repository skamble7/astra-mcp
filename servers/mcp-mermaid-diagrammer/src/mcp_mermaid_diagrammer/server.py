from __future__ import annotations
import logging
from mcp.server.fastmcp import FastMCP
from .tools import register as register_tools
from mcp.server.transport_security import TransportSecuritySettings
import os

logger = logging.getLogger("mcp.mermaid.server")

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

# Register tools once at import time
register_tools(mcp)

# Optional: startup log
try:
    @mcp.on_startup  # type: ignore[attr-defined]
    async def _on_start() -> None:
        logger.info("FastMCP mermaid-diagrammer started with tools: %s", [t.name for t in mcp.tools])
except Exception:
    pass