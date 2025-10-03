from __future__ import annotations

import contextlib
import logging
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse, PlainTextResponse

from ..server import mcp

logger = logging.getLogger("mcp.git-repo-snapshot.app")

# IMPORTANT:
# 1) Leave FastMCP's default streamable_http_path="/mcp"
# 2) Mount the app at "/" so the final URL is exactly "/mcp" (no double paths, no 307)
mcp_app = mcp.streamable_http_app()  # ASGI app provided by FastMCP

async def health(_request):
    return JSONResponse(
        {
            "status": "ok",
            "name": "mcp-git-repo-snapshot",
            "transport": "streamable-http",
            "endpoint": "/mcp",
        },
        status_code=200,
    )

async def root(_request):
    return PlainTextResponse("mcp-git-repo-snapshot\ntransport: streamable-http at /mcp")

# Lifespan: start/stop the MCP session manager so POST /mcp works
@contextlib.asynccontextmanager
async def lifespan(_app: Starlette):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield

routes = [
    # Mount at "/" so the MCP endpoint is "/mcp" (default internal path)
    Mount("/", app=mcp_app),
    Route("/health", endpoint=health, methods=["GET"]),
    Route("/", endpoint=root, methods=["GET"]),
]

app = Starlette(routes=routes, lifespan=lifespan)