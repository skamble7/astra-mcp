# servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/utils/fs.py
from __future__ import annotations
import os
from typing import List, Dict

KIND_MAP = {
    ".jcl": "jcl",
    ".txt": "other",   # allow .txt for quick tests
}

def detect_kind(relpath: str) -> str:
    _, ext = os.path.splitext(relpath.lower())
    return KIND_MAP.get(ext, "other")

def walk_index(root: str) -> List[Dict]:
    files = []
    for base, _, names in os.walk(root):
        for n in names:
            ap = os.path.join(base, n)
            try:
                st = os.stat(ap)
            except FileNotFoundError:
                continue
            rel = os.path.relpath(ap, root).replace("\\", "/")
            k = detect_kind(rel)
            if k != "jcl":
                continue
            files.append({
                "relpath": rel,
                "size_bytes": int(st.st_size),
                # sha is computed later when needed; keep a stable placeholder to match tool logic
                "sha256": "placeholder",  
            })
    return files

def safe_join(root: str, relpath: str) -> str:
    relpath = relpath.replace("\\", "/").lstrip("/")
    abs_path = os.path.abspath(os.path.join(root, relpath))
    root_abs = os.path.abspath(root)
    if not (abs_path == root_abs or abs_path.startswith(root_abs + os.sep)):
        raise PermissionError("Path traversal detected.")
    return abs_path