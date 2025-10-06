#  servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/models/artifact_kind.py#  servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/models/artifact_kind.py
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

DiagramLanguage = Literal["mermaid", "plantuml", "graphviz", "d2", "nomnoml", "dot"]
DiagramView = Literal[
    "sequence", "flowchart", "class", "component", "deployment",
    "state", "activity", "mindmap", "er", "gantt", "timeline", "journey",
]

class PromptVariantSpec(BaseModel):
    name: str
    when: Optional[Dict[str, Any]] = None
    system: Optional[str] = None
    user_template: Optional[str] = None

class DiagramPromptSpec(BaseModel):
    system: str
    user_template: Optional[str] = None
    variants: List[PromptVariantSpec] = Field(default_factory=list)
    strict_text: bool = True
    prompt_rev: int = 1
    io_hints: Optional[Dict[str, Any]] = None

class DiagramRecipeSpec(BaseModel):
    id: str
    title: str
    view: DiagramView
    language: DiagramLanguage = "mermaid"
    description: Optional[str] = None
    # template intentionally omitted in LLM-only server
    prompt: Optional[DiagramPromptSpec] = None
    renderer_hints: Optional[Dict[str, Any]] = None
    examples: List[Dict[str, Any]] = Field(default_factory=list)
    depends_on: Optional[Dict[str, Any]] = None

class SchemaVersionSpec(BaseModel):
    version: str
    json_schema: Dict[str, Any]
    additional_props_policy: Literal["forbid", "allow"] = "forbid"
    # JSON data generation prompt omitted
    diagram_recipes: List[DiagramRecipeSpec] = Field(default_factory=list)

class KindRegistryDoc(BaseModel):
    id: str = Field(alias="_id")
    title: Optional[str] = None
    category: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    status: Literal["active", "deprecated"] = "active"
    latest_schema_version: str
    schema_versions: List[SchemaVersionSpec]
    policies: Optional[Dict[str, Any]] = None
