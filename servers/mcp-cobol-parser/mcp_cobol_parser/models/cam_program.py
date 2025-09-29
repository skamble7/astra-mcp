# File: servers/mcp-cobol-parser/mcp_cobol_parser/models/cam_program.py
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional
from .common import SourceRef

class ProgramDivisions(BaseModel):
    identification: dict = Field(default_factory=dict)
    environment: dict = Field(default_factory=dict)
    data: dict = Field(default_factory=dict)
    procedure: dict = Field(default_factory=dict)

class CallRef(BaseModel):
    target: str
    dynamic: bool = False

class IoOp(BaseModel):
    op: str  # READ/WRITE/OPEN/CLOSE/REWRITE
    dataset_ref: str
    fields: List[str] = []

class Paragraph(BaseModel):
    name: str
    performs: List[str] = []
    calls: List[CallRef] = []
    io_ops: List[IoOp] = []

class CamProgram(BaseModel):
    program_id: str
    source: SourceRef
    divisions: ProgramDivisions
    paragraphs: List[Paragraph]
    copybooks_used: List[str] = []
    notes: List[str] = []
