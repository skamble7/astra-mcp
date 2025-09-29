# File: servers/mcp-cobol-parser/mcp_cobol_parser/utils/fs.py
from __future__ import annotations
import os, typing as t
from ..hashing import sha256_file

KIND_MAP = {
    ".cbl": "cobol",
    ".cob": "cobol",
    ".cpy": "copybook",
    ".cpyb": "copybook",
    ".jcl": "jcl",
    ".bms": "bms",
    ".ddl": "ddl",
}

def detect_kind(relpath: str) -> str:
    _, ext = os.path.splitext(relpath.lower())
    return KIND_MAP.get(ext, "other")

def walk_index(root: str) -> list[dict]:
    files = []
    for base, _, names in os.walk(root):
        for n in names:
            ap = os.path.join(base, n)
            try:
                st = os.stat(ap)
            except FileNotFoundError:
                continue
            rel = os.path.relpath(ap, root)
            k = detect_kind(rel)
            files.append({
                "relpath": rel.replace("\\", "/"),
                "size_bytes": int(st.st_size),
                "sha256": sha256_file(ap),
                "kind": k,
            })
    return files
