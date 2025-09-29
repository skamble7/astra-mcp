# File: servers/mcp-cobol-parser/mcp_cobol_parser/models/cam_copybook.py
from __future__ import annotations
from pydantic import BaseModel
from typing import List, Optional
from .common import SourceRef

class CopyItem(BaseModel):
    level: str
    name: str
    picture: str
    occurs: Optional[int] = None
    children: Optional[List["CopyItem"]] = None

CopyItem.model_rebuild()

class CamCopybook(BaseModel):
    name: str
    source: SourceRef
    items: list[CopyItem]
