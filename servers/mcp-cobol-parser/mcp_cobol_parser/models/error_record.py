# File: servers/mcp-cobol-parser/mcp_cobol_parser/models/error_record.py
from __future__ import annotations
from pydantic import BaseModel

class ErrorArtifact(BaseModel):
    kind: str = "error"
    key: str
    data: dict
