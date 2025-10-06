# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/engine/selector.py# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/engine/selector.py
from __future__ import annotations

from typing import List, Optional

from ..models.artifact_kind import KindRegistryDoc, SchemaVersionSpec, DiagramRecipeSpec

def _resolve_latest(kind: KindRegistryDoc) -> SchemaVersionSpec:
    latest = str(kind.latest_schema_version)
    for sv in kind.schema_versions:
        if str(sv.version) == latest:
            return sv
    # fallback to the first entry
    return kind.schema_versions[0]

def select_mermaid_recipes(
    kind: KindRegistryDoc,
    *,
    views: Optional[List[str]] = None,
    max_count: Optional[int] = None,
) -> List[DiagramRecipeSpec]:
    sv = _resolve_latest(kind)
    recipes = [r for r in (sv.diagram_recipes or []) if (r.language or "mermaid") == "mermaid"]
    if views:
        views_lower = {v.lower() for v in views}
        recipes = [r for r in recipes if r.view.lower() in views_lower]
    if max_count is not None and max_count > 0:
        recipes = recipes[: max_count]
    return recipes
