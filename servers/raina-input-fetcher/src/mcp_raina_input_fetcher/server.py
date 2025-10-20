from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from .models.params import FetchParams
from .settings import Settings
from .tools.fetch_input import fetch_and_validate, build_artifact

log = logging.getLogger(os.getenv("SERVICE_NAME", "mcp.raina.input.fetcher"))
mcp = FastMCP("raina-input-fetcher")

@mcp.tool(name="raina.input.fetch", title="Fetch Raina Input (AVC/FSS/PSS) from URL")
async def raina_input_fetch(url: str, name: str | None = None, auth_bearer: str | None = None) -> Dict[str, Any]:
    """
    Fetches a Raina input JSON from `url`, validates it against cam.inputs.raina, and returns an artifact.
    """
    settings = Settings.from_env()
    params = FetchParams(url=url, name=name, auth_bearer=auth_bearer)
    validated = await fetch_and_validate(params, settings)
    artifact = build_artifact(validated, name=params.name, settings=settings)
    # Wrap for conductor (expects `artifacts` top-level)
    return {"artifacts": [artifact]}

try:
    @mcp.on_startup  # type: ignore[attr-defined]
    async def _on_start() -> None:
        s = Settings.from_env()
        cfg = {
            "transport": os.getenv("MCP_TRANSPORT", "stdio"),
            "timeout": s.http_timeout_seconds,
            "redirects": s.http_follow_redirects,
            "artifact_name_prefix": s.artifact_name_prefix,
        }
        log.info("Raina Input Fetcher started cfg=%s", json.dumps(cfg, ensure_ascii=False))
except Exception:
    pass