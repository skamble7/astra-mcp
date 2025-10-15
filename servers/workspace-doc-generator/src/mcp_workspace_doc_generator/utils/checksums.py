# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/utils/checksums.py
from __future__ import annotations
import hashlib
from pathlib import Path

def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()