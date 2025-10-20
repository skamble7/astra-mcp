from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import httpx
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ..models.params import FetchParams
from ..models.raina_input import RainaInputDoc
from ..settings import Settings

log = logging.getLogger("mcp.raina.input.fetch")

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _load_schema() -> Dict[str, Any]:
    here = Path(__file__).resolve().parent.parent / "artifact_kinds" / "cam.inputs.raina.json"
    spec = json.loads(here.read_text(encoding="utf-8"))
    versions = spec.get("schema_versions") or []
    latest = spec.get("latest_schema_version")
    if not versions:
        raise RuntimeError("cam.inputs.raina schema missing schema_versions")
    entry = next((v for v in versions if v.get("version") == latest), versions[0])
    schema = entry.get("json_schema")
    if not isinstance(schema, dict):
        raise RuntimeError("cam.inputs.raina schema missing json_schema")
    return schema

_VALIDATOR = Draft202012Validator(_load_schema())

async def fetch_and_validate(params: FetchParams, settings: Settings) -> Dict[str, Any]:
    """
    Fetches the remote JSON, validates strictly against cam.inputs.raina JSON Schema,
    also parses into Pydantic models. Returns the validated JSON object.
    """
    headers: dict[str, str] = {"accept": "application/json"}
    bearer = (params.auth_bearer or settings.default_auth_bearer or "").strip()
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"

    timeout = httpx.Timeout(settings.http_timeout_seconds)
    async with httpx.AsyncClient(follow_redirects=settings.http_follow_redirects, timeout=timeout) as client:
        log.info(f"http.get url={params.url}")
        resp = await client.get(str(params.url), headers=headers)
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Endpoint did not return valid JSON: {e}") from e

    # JSON Schema validation (strict)
    errors = sorted(_VALIDATOR.iter_errors(data), key=lambda e: e.path)
    if errors:
        # Build a compact error summary
        msgs = []
        for err in errors[:25]:
            loc = "/".join([str(p) for p in err.path]) or "<root>"
            msgs.append(f"{loc}: {err.message}")
        raise RuntimeError("Schema validation failed:\n- " + "\n- ".join(msgs))

    # Pydantic model validation (type-safety + useful errors)
    try:
        RainaInputDoc.model_validate(data)
    except ValidationError as e:
        raise RuntimeError(f"Pydantic validation failed: {e}") from e

    return data

def build_artifact(validated: Dict[str, Any], *, name: str | None, settings: Settings) -> Dict[str, Any]:
    # Title / name
    domain = (
        validated.get("inputs", {})
        .get("avc", {})
        .get("context", {})
        .get("domain", "")
    )
    title = name or f"{settings.artifact_name_prefix} ({domain or 'Unknown Domain'})"

    now = _now_iso()
    return {
        "kind_id": "cam.inputs.raina",
        "name": title,
        "data": validated,  # <- strictly: { inputs: { avc, fss, pss } }
        "preview": {"text_excerpt": domain[:240] if isinstance(domain, str) else None},
        "mime_type": "application/json",
        "encoding": "utf-8",
        "tags": settings.artifact_tags or ["inputs", "raina", "discovery"],
        "created_at": now,
        "updated_at": now,
    }