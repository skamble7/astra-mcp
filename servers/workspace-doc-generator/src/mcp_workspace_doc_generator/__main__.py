# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/__main__.py
from __future__ import annotations
import os
import sys
import logging

from .server import mcp  # FastMCP instance
from .utils.logging import setup_logging

def main() -> None:
    setup_logging()
    log = logging.getLogger("mcp.workspace.doc.main")

    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        sys.stderr.write("mcp-workspace-doc-generator: FastMCP server runner.\n")
        return

    transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8002"))
    mcp.settings.host = host
    mcp.settings.port = port

    if transport == "streamable-http":
        mcp.settings.streamable_http_path = os.getenv("MCP_MOUNT_PATH", "/mcp")
    elif transport == "sse":
        mcp.settings.sse_path = os.getenv("MCP_SSE_PATH", "/sse")

    if os.getenv("MCP_STATELESS_JSON", "").lower() in {"1", "true", "yes"}:
        mcp.settings.stateless_http = True
        mcp.settings.json_response = True

    log.info(
        "server.start",
        extra={
            "transport": transport,
            "host": host,
            "port": port,
            "path": getattr(mcp.settings, "streamable_http_path", None) or getattr(mcp.settings, "sse_path", None),
        },
    )
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()