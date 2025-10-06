# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/models/diagram_instance.py# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/models/diagram_instance.py
from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class DiagramInstanceLike(BaseModel):
    recipe_id: Optional[str] = Field(default=None)
    view: Optional[str] = Field(default=None)
    language: str = Field(default="mermaid")
    instructions: str
    renderer_hints: Optional[Dict[str, Any]] = Field(default_factory=lambda: {"wrap": True})
    generated_from_fingerprint: Optional[str] = None
    prompt_rev: Optional[int] = None
    provenance: Optional[Dict[str, Any]] = None
