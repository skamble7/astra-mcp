# File: servers/git-repo-snapshot/src/mcp_git_repo_snapshot/transports/sse.py
from __future__ import annotations

import os
import uvicorn

# Your FastMCP instance
from ..server import mcp


def build_app():
    # Prefer attributes/factories if the FastMCP instance exposes them
    if hasattr(mcp, "app") and getattr(mcp, "app") is not None:
        return mcp.app
    if hasattr(mcp, "sse_app") and getattr(mcp, "sse_app") is not None:
        return mcp.sse_app
    if hasattr(mcp, "create_app"):
        return mcp.create_app()
    if hasattr(mcp, "create_sse_app"):
        return mcp.create_sse_app()

    # Fallback to the SDK’s SSE server (works with mcp>=1.0)
    try:
        from mcp.server.sse import SseServer  # ✅ present in new SDKs
        return SseServer(mcp).app
    except Exception:
        pass

    # Last-ditch legacy fallback
    try:
        from modelcontextprotocol.sse import SseServer  # legacy package name
        return SseServer(mcp).app
    except Exception as e:
        raise RuntimeError(
            "Unable to construct an ASGI app from FastMCP. "
            "Upgrade the `mcp` package or adjust the server glue."
        ) from e


# Starlette/FastAPI-compatible ASGI app for uvicorn
app = build_app()

# Optional local run: `python -m mcp_git_repo_snapshot.transports.sse`
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("MCP_PORT", "8000")), log_level="info")