from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

import httpx
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ..models.params import FetchParams
from ..models.raina_input import RainaInputDoc
from ..settings import Settings

log = logging.getLogger("mcp.raina.input.fetch")

def _load_schema() -> Dict[str, Any]:
    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "raina_input.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise RuntimeError("raina_input.json is not a valid JSON Schema object")
    return schema

_VALIDATOR = Draft202012Validator(_load_schema())


async def fetch_and_validate(params: FetchParams, settings: Settings) -> Dict[str, Any]:
    """
    Fetches the Raina input JSON from the given URL, validates it against the
    raina_input JSON Schema, and returns the validated data as-is.
    """
    headers: dict[str, str] = {"accept": "application/json"}
    bearer = (params.auth_bearer or settings.default_auth_bearer or "").strip()
    if bearer:
        headers["authorization"] = f"Bearer {bearer}"

    timeout = httpx.Timeout(settings.http_timeout_seconds)
    async with httpx.AsyncClient(follow_redirects=settings.http_follow_redirects, timeout=timeout) as client:
        log.info("http.get url=%s", params.url)
        resp = await client.get(str(params.url), headers=headers)
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception as e:
            raise RuntimeError(f"Endpoint did not return valid JSON: {e}") from e

    # JSON Schema validation
    errors = sorted(_VALIDATOR.iter_errors(data), key=lambda e: e.path)
    if errors:
        msgs = []
        for err in errors[:25]:
            loc = "/".join([str(p) for p in err.path]) or "<root>"
            msgs.append(f"{loc}: {err.message}")
        raise RuntimeError("Schema validation failed:\n- " + "\n- ".join(msgs))

    # Pydantic model validation (type-safety)
    try:
        RainaInputDoc.model_validate(data)
    except ValidationError as e:
        raise RuntimeError(f"Pydantic validation failed: {e}") from e

    return data
