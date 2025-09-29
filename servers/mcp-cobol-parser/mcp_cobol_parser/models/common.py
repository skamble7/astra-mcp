# File: servers/mcp-cobol-parser/mcp_cobol_parser/models/common.py
from __future__ import annotations
from pydantic import BaseModel

class SourceRef(BaseModel):
    relpath: str
    sha256: str
