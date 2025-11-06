#servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/__main__.py
from __future__ import annotations
import os, sys
from .server import mcp

def main() -> None:
    """
    Run the JCL LegacyLens MCP server using the official SDK runner.

    Examples:
      MCP_TRANSPORT=streamable-http MCP_PORT=8876 python -m mcp_jcl_parser_legacylens
      MCP_TRANSPORT=stdio python -m mcp_jcl_parser_legacylens
    """
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        sys.stderr.write("mcp-jcl-parser-legacylens: MCP server for JCL parsing (LegacyLens heuristics).\n")
        sys.stderr.flush()
        return

    transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()

    # Configure runner settings BEFORE run()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8876"))
    mcp.settings.host = host
    mcp.settings.port = port

    # Mount/path tuning (defaults match SDK docs)
    if transport == "streamable-http":
        mcp.settings.streamable_http_path = os.getenv("MCP_MOUNT_PATH", "/mcp")
    elif transport == "sse":
        mcp.settings.sse_path = os.getenv("MCP_SSE_PATH", "/sse")

    # Optional stateless JSON mode
    if os.getenv("MCP_STATELESS_JSON", "").lower() in {"1", "true", "yes"}:
        mcp.settings.stateless_http = True
        mcp.settings.json_response = True

    mcp.run(transport=transport)

if __name__ == "__main__":
    main()