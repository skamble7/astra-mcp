from __future__ import annotations
import os
import sys
from .server import mcp  # import the FastMCP instance
from .utils.logging import setup_logging
import logging

def main() -> None:
    """
    Entry point for running the server via the official SDK runner.

    Examples:
      MCP_TRANSPORT=streamable-http python -m mcp_mermaid_diagrammer
      MCP_TRANSPORT=stdio           python -m mcp_mermaid_diagrammer
    """
    setup_logging()
    log = logging.getLogger("mcp.mermaid.main")

    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        sys.stderr.write("mcp-mermaid-diagrammer: runs an MCP server using the official SDK runner.\n")
        sys.stderr.flush()
        return

    transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()

    # Configure settings BEFORE run()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8001"))
    mcp.settings.host = host
    mcp.settings.port = port

    # Paths (align with SDK defaults)
    if transport == "streamable-http":
        mcp.settings.streamable_http_path = os.getenv("MCP_MOUNT_PATH", "/mcp")
    elif transport == "sse":
        mcp.settings.sse_path = os.getenv("MCP_SSE_PATH", "/sse")

    # Optional: stateless JSON mode for quick curl/browser tests
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

    # Run using the SDK runner
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()