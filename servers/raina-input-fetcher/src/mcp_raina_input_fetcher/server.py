from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from .models.params import FetchParams
from .models.raina_input import RainaInputDoc
from .settings import Settings
from .tools.fetch_input import fetch_and_validate
from mcp.server.transport_security import TransportSecuritySettings

log = logging.getLogger(os.getenv("SERVICE_NAME", "mcp.raina.input.fetcher"))
allowed_hosts = os.getenv("ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,host.docker.internal:*,*").split(",")
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:*,http://127.0.0.1:*,http://host.docker.internal:*,*").split(",")

# Single FastMCP instance
mcp = FastMCP(
    "mcp.mermaid.server",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    ),
)


@mcp.tool(name="raina.input.fetch", title="Fetch Raina Input (AVC/FSS/PSS) from URL")
async def raina_input_fetch(stories_url: str, auth_bearer: str | None = None) -> RainaInputDoc:
    """
    Fetches a Raina input JSON from `stories_url`, validates it against the
    raina_input schema (AVC/FSS/PSS structure), and returns the validated document.

    Returns an object with shape:
      { "inputs": { "avc": {...}, "fss": { "stories": [...] }, "pss": {...} } }
    """
    settings = Settings.from_env()
    params = FetchParams(url=stories_url, auth_bearer=auth_bearer)
    data = await fetch_and_validate(params, settings)
    return RainaInputDoc.model_validate(data)


try:
    @mcp.on_startup  # type: ignore[attr-defined]
    async def _on_start() -> None:
        s = Settings.from_env()
        cfg = {
            "transport": os.getenv("MCP_TRANSPORT", "stdio"),
            "timeout": s.http_timeout_seconds,
            "redirects": s.http_follow_redirects,
        }
        log.info("Raina Input Fetcher started cfg=%s", json.dumps(cfg, ensure_ascii=False))
except Exception:
    pass
