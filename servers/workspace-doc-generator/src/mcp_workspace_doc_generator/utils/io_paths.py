# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/utils/io_paths.py
from __future__ import annotations
import os
from pathlib import Path

def ensure_output_dir() -> Path:
    base = os.getenv("OUTPUT_DIR", "/tmp/mcp-workspace-docs")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p