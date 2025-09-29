# File: servers/mcp-cobol-parser/mcp_cobol_parser/resources/file_preview.py
from __future__ import annotations
import os, json
from typing import Any
from ..settings import Settings
from ..cache import manifest_path, exists

_MAX_PREVIEW_BYTES = 128 * 1024  # 128 KiB preview cap

def _resolve_root_from_run(cfg: Settings, run_id: str) -> str:
    mp = manifest_path(cfg, run_id)
    if not exists(mp):
        raise FileNotFoundError(f"Run not found: {run_id}")
    with open(mp, "r", encoding="utf-8") as f:
        data = json.load(f)
    root = (data.get("run", {}) or {}).get("paths_root") or data.get("paths_root")
    if not root or not os.path.isdir(root):
        raise FileNotFoundError("paths_root missing or invalid in manifest.")
    return root

def register_file_preview_resources(mcp: Any) -> None:
    @mcp.resource(
        uri="file://{run_id}/{relpath}",   # ← no wildcard star in mcp>=1.0
        name="File Preview",
        description="Returns a safe text preview of a file from the run’s repo root.",
        mime_type="text/plain",
    )
    def read_file_preview(run_id: str, relpath: str) -> str:
        cfg = Settings()
        root = _resolve_root_from_run(cfg, run_id)
        relpath = relpath.replace("\\", "/").lstrip("/")
        abs_path = os.path.abspath(os.path.join(root, relpath))
        root_abs = os.path.abspath(root)
        if not (abs_path == root_abs or abs_path.startswith(root_abs + os.sep)):
            raise PermissionError("Path traversal detected.")
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"File not found: {relpath}")

        with open(abs_path, "rb") as f:
            blob = f.read(_MAX_PREVIEW_BYTES)
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError:
            return blob.decode("utf-8", errors="replace")
