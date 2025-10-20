from __future__ import annotations
import os
import sys
import logging

from .server import mcp

def _setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

def main() -> None:
    _setup_logging()
    log = logging.getLogger(os.getenv("SERVICE_NAME", "mcp.raina.input.fetcher"))

    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        sys.stderr.write("mcp-raina-input-fetcher: FastMCP server runner.\n")
        return

    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8012"))

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
            "path": getattr(mcp.settings, "streamable_http_path", None)
                    or getattr(mcp.settings, "sse_path", None),
        },
    )
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()