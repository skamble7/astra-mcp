# servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/models/cam_jcl_job.py
from __future__ import annotations
from pydantic import BaseModel
from typing import List, Optional
from .common import SourceRef
from .jcl_shared import JclDD

class JclStep(BaseModel):
    step_name: Optional[str] = None
    seq: Optional[int | str] = None
    program: Optional[str] = None
    condition: Optional[str] = None
    dds: Optional[List[JclDD]] = None

class CamJclJob(BaseModel):
    job_name: Optional[str] = None
    source: SourceRef | None = None
    steps: Optional[List[JclStep]] = None