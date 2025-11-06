# File: servers/mcp-cobol-parser/mcp_cobol_parser/utils/artifacts.py
from __future__ import annotations

from typing import Any, Dict, Optional

_KIND_KEYS = ("kind_id", "kind", "_kind", "artifact_kind")

_DEFAULT_SCHEMA = "1.0.0"

def _pick(obj: Dict[str, Any], *keys: str) -> Optional[str]:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None

def ensure_enveloped_item(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure the item is in canonical envelope shape:
      { kind_id, schema_version?, key?, provenance?, data, diagrams?, narratives? }

    - Accepts legacy shapes like { kind|_kind|artifact_kind, payload|content }.
    - Does NOT mutate nested 'data' beyond basic dict check.
    """
    if not isinstance(obj, dict):
        raise ValueError("artifact item must be an object")

    # If it already looks enveloped, return as-is (with a light sanity check)
    if "kind_id" in obj and "data" in obj and isinstance(obj["data"], dict):
        return obj

    kind_id = _pick(obj, *_KIND_KEYS)
    if not kind_id:
        raise ValueError("artifact item missing kind/kind_id")

    # Find data-like payload
    data = obj.get("data")
    if not isinstance(data, dict):
        payload = obj.get("payload") or obj.get("content")
        if isinstance(payload, dict):
            data = payload
        else:
            raise ValueError("artifact item missing data{} object")

    out: Dict[str, Any] = {
        "kind_id": kind_id,
        "schema_version": obj.get("schema_version") or _DEFAULT_SCHEMA,
        "data": data,
    }

    # Optional conventional fields (pass-through if present)
    for k in ("key", "provenance", "diagrams", "narratives"):
        if k in obj:
            out[k] = obj[k]

    # Best-effort key if missing: prefer data.source.relpath
    if "key" not in out:
        try:
            rel = data.get("source", {}).get("relpath")
            if isinstance(rel, str) and rel.strip():
                out["key"] = rel.strip()
        except Exception:
            pass

    return out