# File: servers/mcp-cobol-parser/mcp_cobol_parser/__main__.py
from __future__ import annotations
import os
import sys
from .server import mcp

def main() -> None:
    """
    Run the COBOL parser MCP server using the official SDK runner.

    Examples:
      # default (recommended): streamable HTTP at 0.0.0.0:8765 mounted at /mcp
      MCP_TRANSPORT=streamable-http MCP_PORT=8765 python -m mcp_cobol_parser

      # stdio mode (e.g., for MCP Inspector)
      MCP_TRANSPORT=stdio python -m mcp_cobol_parser

      # optional stateless JSON for curl tests (not for production):
      # MCP_STATELESS_JSON=true
    """
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        sys.stderr.write("mcp-cobol-parser: MCP server for COBOL parsing (ProLeap + CB2XML).\n")
        sys.stderr.flush()
        return

    transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()

    # Configure runner settings BEFORE run()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8765"))
    mcp.settings.host = host
    mcp.settings.port = port

    # Mount/path tuning (defaults match SDK docs)
    if transport == "streamable-http":
        mcp.settings.streamable_http_path = os.getenv("MCP_MOUNT_PATH", "/mcp")
    elif transport == "sse":
        # still supported if you ever need to fall back
        mcp.settings.sse_path = os.getenv("MCP_SSE_PATH", "/sse")

    # Optional stateless JSON mode for simple curl/browser testing
    if os.getenv("MCP_STATELESS_JSON", "").lower() in {"1", "true", "yes"}:
        mcp.settings.stateless_http = True
        mcp.settings.json_response = True

    # Run using the SDK runner
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()