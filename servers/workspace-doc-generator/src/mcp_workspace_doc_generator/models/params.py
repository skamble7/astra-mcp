# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/models/params.py
from __future__ import annotations
from pydantic import BaseModel, Field, field_validator

class GenerateParams(BaseModel):
    workspace_id: str = Field(..., description="Workspace ID whose artifacts are the source context")
    kind_id: str = Field(..., description="Registry kind id (e.g., cam.asset.*). Determines prompt, dependencies, and output schema.")

    @field_validator("workspace_id", mode="before")
    @classmethod
    def _strip_ws_id(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("kind_id", mode="before")
    @classmethod
    def _strip_kind_id(cls, v: str) -> str:
        return (v or "").strip()