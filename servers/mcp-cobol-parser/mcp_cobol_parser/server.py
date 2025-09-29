# File: servers/mcp-cobol-parser/mcp_cobol_parser/server.py
from __future__ import annotations

import uvicorn

# New SDK path (mcp>=1.0)
from mcp.server.fastmcp import FastMCP

from .tools.parse_repo import register_tool
from .settings import Settings
from .resources.run_info import register_run_info_resources
from .resources.file_preview import register_file_preview_resources
from .resources.artifact_preview import register_artifact_preview_resources


def build_app():
    mcp = FastMCP("mcp.cobol.parser")

    # Register the single tool and resources
    register_tool(mcp)
    register_run_info_resources(mcp)
    register_file_preview_resources(mcp)
    register_artifact_preview_resources(mcp)

    # ---- Compatibility across SDK variants ----
    # 1) Newer mcp server exposes an ASGI app attribute/property
    if hasattr(mcp, "app") and mcp.app is not None:          # e.g., mcp.app
        return mcp.app
    if hasattr(mcp, "sse_app") and mcp.sse_app is not None:  # some pre-release builds
        return mcp.sse_app
    if hasattr(mcp, "create_app"):                           # factory method in some builds
        return mcp.create_app()
    if hasattr(mcp, "create_sse_app"):                       # legacy modelcontextprotocol SDK
        return mcp.create_sse_app()

    # Last-resort: construct SSE server manually if provided by the SDK
    try:
        from mcp.server.sse import SseServer  # mcp>=1.0
        return SseServer(mcp).app
    except Exception:
        pass
    try:
        # legacy path
        from modelcontextprotocol.sse import SseServer  # noqa
        return SseServer(mcp).app
    except Exception as e:
        raise RuntimeError(
            "Unable to construct an ASGI app from FastMCP. "
            "Upgrade the `mcp` package or adjust the server glue."
        ) from e


def main():
    # Load settings (ensures cache dir exists; logs missing jar warnings)
    _ = Settings()
    app = build_app()
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")


if __name__ == "__main__":
    main()
