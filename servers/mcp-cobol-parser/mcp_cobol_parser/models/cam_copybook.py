# File: servers/mcp-cobol-parser/mcp_cobol_parser/models/cam_copybook.py
from __future__ import annotations
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel
from .common import SourceRef

# Matches cam.cobol.copybook@1.0.0 schema:
# - level: string|integer|null
# - name: string|null
# - picture: string|null (default "")
# - occurs: integer|string|object|null
# - children: array|null (recursive)
class CopyItem(BaseModel):
    level: Optional[Union[str, int]] = None
    name: Optional[str] = None
    picture: Optional[str] = ""
    occurs: Optional[Union[int, str, Dict[str, Any]]] = None
    children: Optional[List["CopyItem"]] = None

CopyItem.model_rebuild()

class CamCopybook(BaseModel):
    # Top-level:
    # name: string|null
    # source: { relpath: string|null, sha256: string|null }  (we will provide concrete values)
    # items: array|null (we provide an array when we have nodes)
    name: Optional[str]
    source: SourceRef
    items: List[CopyItem]