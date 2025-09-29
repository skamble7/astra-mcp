# File: servers/mcp-cobol-parser/mcp_cobol_parser/hashing.py
from __future__ import annotations
import hashlib

def sha256_file(path: str, bufsize: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
