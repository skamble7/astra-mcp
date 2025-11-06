#servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/hashing.py
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

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()