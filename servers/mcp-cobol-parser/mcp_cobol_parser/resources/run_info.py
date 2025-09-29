# File: servers/mcp-cobol-parser/mcp_cobol_parser/resources/run_info.py
from __future__ import annotations
import json
from typing import Any
from ..settings import Settings
from ..cache import manifest_path, exists

def register_run_info_resources(mcp: Any) -> None:
    @mcp.resource(
        uri="run://{run_id}",
        name="Run Manifest",
        description="Returns the manifest.json for a parse run.",
        mime_type="application/json",
    )
    def read_run_manifest(run_id: str) -> dict[str, Any]:
        cfg = Settings()
        mp = manifest_path(cfg, run_id)
        if not exists(mp):
            raise FileNotFoundError(f"Run not found: {run_id}")
        with open(mp, "r", encoding="utf-8") as f:
            return json.load(f)
