# servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/models/cam_jcl_step.py
from __future__ import annotations
from pydantic import BaseModel
from typing import List, Optional
from .jcl_shared import JclDD

class CamJclStep(BaseModel):
    job_name: Optional[str] = None
    step_name: Optional[str] = None
    seq: Optional[int | str] = None
    program: Optional[str] = None
    dds: Optional[List[JclDD]] = None