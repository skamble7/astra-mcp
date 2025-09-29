# File: servers/mcp-cobol-parser/mcp_cobol_parser/models/cam_source_index.py
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal

Kind = Literal["cobol","copybook","jcl","ddl","bms","other"]

class SourceIndexFile(BaseModel):
    relpath: str
    size_bytes: int
    sha256: str
    kind: Kind
    language_hint: str | None = None
    encoding: str | None = None
    program_id_guess: str | None = None

class CamSourceIndex(BaseModel):
    root: str
    files: list[SourceIndexFile]
