# servers/git-repo-snapshot/src/mcp_git_repo_snapshot/__main__.py# servers/git-repo-snapshot/src/mcp_git_repo_snapshot/__main__.py
from __future__ import annotations
import os
import sys
from .server import mcp

def main() -> None:
    """
    Entry point for running the server directly via the official SDK runner.

    Examples:
      # default streamable HTTP on 0.0.0.0:8000, mounted at /mcp
      MCP_TRANSPORT=streamable-http python -m mcp_git_repo_snapshot

      # stdio mode (for MCP Inspector / local dev)
      MCP_TRANSPORT=stdio python -m mcp_git_repo_snapshot
    """
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        sys.stderr.write(
            "mcp-git-repo-snapshot: runs an MCP server using the official SDK runner.\n"
        )
        sys.stderr.flush()
        return

    transport = os.getenv("MCP_TRANSPORT", "streamable-http").strip().lower()

    # Configure settings BEFORE run()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    mcp.settings.host = host
    mcp.settings.port = port

    # Path tuning (defaults match SDK docs)
    if transport == "streamable-http":
        mcp.settings.streamable_http_path = os.getenv("MCP_MOUNT_PATH", "/mcp")
    elif transport == "sse":
        mcp.settings.sse_path = os.getenv("MCP_SSE_PATH", "/sse")

    # Optional stateless JSON mode for curl/browser testing
    if os.getenv("MCP_STATELESS_JSON", "").lower() in {"1", "true", "yes"}:
        mcp.settings.stateless_http = True
        mcp.settings.json_response = True

    # Run using the SDK runner
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()