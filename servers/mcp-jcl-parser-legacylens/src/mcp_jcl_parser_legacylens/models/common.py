#servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/models/common.py
from __future__ import annotations
from pydantic import BaseModel

class SourceRef(BaseModel):
    relpath: str
    sha256: str