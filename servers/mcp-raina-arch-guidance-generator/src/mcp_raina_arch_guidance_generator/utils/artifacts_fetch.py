# utils/artifacts_fetch.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

import httpx

from ..settings import Settings

log = logging.getLogger("mcp.raina.arch.guidance.fetch")


def _find_local_artifacts_json(workspace_id: str) -> Path | None:
    p = Path("/workspace") / workspace_id / "artifacts.json"
    return p if p.exists() else None


def _normalize_artifacts_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [a for a in payload if isinstance(a, dict)]
    if isinstance(payload, dict):
        arts = payload.get("artifacts")
        if isinstance(arts, list):
            return [a for a in arts if isinstance(a, dict)]
    return []


async def fetch_workspace_artifacts(
    workspace_id: str,
    settings: Settings | None = None,
) -> List[Dict[str, Any]]:
    """
    GET {ARTIFACT_SERVICE_URL}/artifact/{workspace_id}?include_deleted=false&limit=50&offset=0
    Accepts either a top-level list or {"artifacts":[...]}.
    Paginates until all artifacts are fetched.
    """
    if settings is None:
        settings = Settings.from_env()

    wid = (workspace_id or "").strip()
    wid_enc = quote(wid, safe="")
    base = settings.artifact_service_url.rstrip("/")

    limit = 50
    offset = 0
    all_arts: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                url = f"{base}/artifact/{wid_enc}?include_deleted=false&limit={limit}&offset={offset}"
                log.info(
                    "fetch.remote.begin",
                    extra={"url": url, "workspace_id": wid, "limit": limit, "offset": offset},
                )
                r = await client.get(url)
                log.info("fetch.remote.status", extra={"status": r.status_code, "url": url})
                r.raise_for_status()

                payload = r.json()
                page = _normalize_artifacts_payload(payload)
                log.info("fetch.remote.success", extra={"count": len(page), "offset": offset})

                if not page:
                    break

                all_arts.extend(page)

                if len(page) < limit:
                    break

                offset += limit

        return all_arts

    except Exception as e:
        log.warning("fetch.remote.failed", extra={"error": str(e), "workspace_id": wid})

    fpath = _find_local_artifacts_json(wid)
    if fpath:
        try:
            log.info("fetch.local.begin", extra={"path": str(fpath)})
            data = json.loads(fpath.read_text())
            arts = _normalize_artifacts_payload(data)
            log.info("fetch.local.success", extra={"count": len(arts)})
            return arts
        except Exception as e:
            log.warning("fetch.local.failed", extra={"error": str(e), "path": str(fpath)})

    log.info("fetch.none", extra={"workspace_id": wid})
    return []


async def fetch_kind_definition(
    kind_id: str,
    settings: Settings | None = None,
) -> Optional[Dict[str, Any]]:
    """GET {ARTIFACT_SERVICE_URL}/registry/kinds/{kind_id}"""
    if settings is None:
        settings = Settings.from_env()

    kid = (kind_id or "").strip()
    kid_enc = quote(kid, safe="")
    base = settings.artifact_service_url.rstrip("/")
    url = f"{base}/registry/kinds/{kid_enc}"

    try:
        log.info("kind.fetch.begin", extra={"url": url, "kind": kid})
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            log.info("kind.fetch.status", extra={"status": r.status_code, "url": url})
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.warning("kind.fetch.failed", extra={"error": str(e), "kind": kid, "url": url})
        return None


async def resolve_kind_aliases(
    kind_ids: List[str],
    settings: Settings | None = None,
) -> Dict[str, Set[str]]:
    """
    For each canonical kind id, fetch its registry doc and return a set of identifiers
    that should be treated as equivalent for matching (canonical + aliases).
    """
    out: Dict[str, Set[str]] = {}
    unique = [k.strip() for k in (kind_ids or []) if (k or "").strip()]

    for kid in unique:
        ids: Set[str] = {kid}
        kd = await fetch_kind_definition(kid, settings=settings)
        if isinstance(kd, dict):
            aliases = kd.get("aliases")
            if isinstance(aliases, list):
                for a in aliases:
                    if isinstance(a, str) and a.strip():
                        ids.add(a.strip())
        out[kid] = ids

    return out


def shortlist_by_kinds_alias_aware(
    artifacts: List[Dict[str, Any]],
    *,
    hard_equivalence: Dict[str, Set[str]],
    soft_equivalence: Dict[str, Set[str]],
    also_include: List[str] | None = None,
) -> List[Dict[str, Any]]:
    wanted: Set[str] = set()
    for s in (hard_equivalence or {}).values():
        wanted |= set(s)
    for s in (soft_equivalence or {}).values():
        wanted |= set(s)
    wanted |= set([x.strip() for x in (also_include or []) if isinstance(x, str) and x.strip()])

    if not wanted:
        return artifacts

    return [a for a in artifacts if (a.get("kind") in wanted)]
