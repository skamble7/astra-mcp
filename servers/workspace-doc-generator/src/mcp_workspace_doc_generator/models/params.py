# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/models/params.py
from __future__ import annotations
from pydantic import BaseModel, Field, field_validator

class GenerateParams(BaseModel):
    workspace_id: str = Field(..., description="Workspace ID")
    prompt: str = Field(..., description="Instruction used to shape the document")

    @field_validator("workspace_id", mode="before")
    @classmethod
    def _strip_ws_id(cls, v: str) -> str:
        # Normalize incoming ids (trim whitespace & control chars)
        return (v or "").strip()

    @field_validator("prompt", mode="before")
    @classmethod
    def _strip_prompt(cls, v: str) -> str:
        return (v or "").strip()