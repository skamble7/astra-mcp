from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

DiagramView = Literal[
    "sequence", "flowchart", "class", "component", "deployment",
    "state", "activity", "mindmap", "er", "gantt", "timeline", "journey",
]

class GenerateRequest(BaseModel):
    artifact: Dict[str, Any]
    views: Optional[List[DiagramView]] = None  # defaults in tool: ["flowchart"]
    prompt: Optional[str] = None               # extra user guidance (optional)

class DiagramOut(BaseModel):
    view: DiagramView
    language: Literal["mermaid"] = "mermaid"
    instructions: str
    renderer_hints: Dict[str, Any] = Field(default_factory=lambda: {"wrap": True})

class GenerateResponse(BaseModel):
    diagrams: List[Dict[str, Any]] = Field(default_factory=list)