# servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/models/jcl_shared.py
from __future__ import annotations
from pydantic import BaseModel
from typing import Optional

class JclDD(BaseModel):
    ddname: Optional[str] = None
    dataset: Optional[str] = None
    direction: Optional[str] = None  # IN | OUT | INOUT | SYS