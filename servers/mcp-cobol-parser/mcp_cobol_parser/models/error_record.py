# File: servers/mcp-cobol-parser/mcp_cobol_parser/models/error_record.py
from __future__ import annotations
from pydantic import BaseModel
from typing import Any, Dict, Optional

class ErrorArtifact(BaseModel):
    # Envelope-friendly error record used when a parse step fails
    kind_id: str = "cam.error"
    schema_version: str = "1.0.0"
    key: str
    data: Dict[str, Any]
    provenance: Optional[Dict[str, Any]] = None