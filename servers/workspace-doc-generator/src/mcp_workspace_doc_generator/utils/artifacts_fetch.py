# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/utils/artifacts_fetch.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

import httpx

from ..settings import Settings

log = logging.getLogger("mcp.workspace.doc.fetch")

def _find_local_artifacts_json(workspace_id: str) -> Path | None:
    p = Path("/workspace") / workspace_id / "artifacts.json"
    return p if p.exists() else None

def _normalize_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if isinstance(payload, dict):
        arts = payload.get("artifacts")
        if isinstance(arts, list):
            return [a for a in arts if isinstance(a, dict)]
    return []

async def fetch_workspace_artifacts(workspace_id: str) -> List[Dict[str, Any]]:
    """
    Calls: {ARTIFACT_SERVICE_URL}/artifact/{workspace_id}?include_deleted=false&limit=50&offset=0
    Accepts either a top-level list or {"artifacts": [...]}
    """
    raw_id = workspace_id
    # Safety: strip whitespace/control chars; URL-encode as a path segment
    wid = (raw_id or "").strip()
    wid_enc = quote(wid, safe="")  # encode anything funky (spaces, slashes, newlines, etc.)

    settings = Settings.from_env()
    base = settings.artifact_service_url.rstrip("/")
    url = f"{base}/artifact/{wid_enc}?include_deleted=false&limit=50&offset=0"

    try:
        log.info("fetch.remote.begin", extra={"url": url, "workspace_id_raw": raw_id, "workspace_id": wid})
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            log.info("fetch.remote.status", extra={"status": r.status_code, "url": url})
            r.raise_for_status()
            payload = r.json()
            arts = _normalize_payload(payload)
            log.info("fetch.remote.success", extra={"count": len(arts)})
            return arts
    except Exception as e:
        log.warning("fetch.remote.failed", extra={"error": str(e), "url": url, "workspace_id": wid})

    # Optional local fallback (mounted dev data)
    fpath = _find_local_artifacts_json(wid)
    if fpath:
        try:
            log.info("fetch.local.begin", extra={"path": str(fpath)})
            data = json.loads(fpath.read_text())
            arts = _normalize_payload(data)
            log.info("fetch.local.success", extra={"count": len(arts)})
            return arts
        except Exception as e:
            log.warning("fetch.local.failed", extra={"error": str(e), "path": str(fpath)})

    log.info("fetch.none", extra={"workspace_id": wid})
    return []