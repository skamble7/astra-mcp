# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/engine/json_utils.py# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/engine/json_utils.py
from __future__ import annotations

import json
from itertools import islice
from typing import Any, Dict, List, Tuple

_CHUNK_TARGET = 9000
_MIN_CHUNK = 4000

def minify_json(obj: Any) -> str:
    try:
        return json.dumps(obj or {}, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return "{}"

def _chunk_list(items: List[Any], approx_budget: int) -> List[List[Any]]:
    sample = items[:50]
    try:
        avg_len = max(1, len(minify_json(sample)) // max(1, len(sample) or 1))
    except Exception:
        avg_len = 512
    per_chunk = max(10, min(200, (approx_budget // max(1, avg_len)) or 50))
    out: List[List[Any]] = []
    it = iter(items)
    while True:
        batch = list(islice(it, per_chunk))
        if not batch:
            break
        out.append(batch)
    return out or [items]

def split_artifact_for_prompt(data: Dict[str, Any], view: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Heuristic chunking that keeps prompts within budget. Special-cases artifacts
    with 'paragraphs' lists to chunk on that boundary for COBOL-like inputs.
    """
    full = minify_json(data)
    if len(full) <= _CHUNK_TARGET or len(full) < _MIN_CHUNK:
        return [("chunk-1", data)]

    if isinstance(data.get("paragraphs"), list) and data["paragraphs"]:
        base = {k: v for k, v in data.items() if k != "paragraphs"}
        budget = max(1024, _CHUNK_TARGET - len(minify_json(base)) - 1000)
        groups = _chunk_list(data["paragraphs"], budget)
        chunks = []
        for i, grp in enumerate(groups, 1):
            chunk = dict(base)
            chunk["paragraphs"] = grp
            chunks.append((f"paragraphs-{i}", chunk))
        return chunks

    # fallback: slice by length
    slices: List[Tuple[str, Dict[str, Any]]] = []
    s = full
    idx = 0
    while s:
        part, s = s[:_CHUNK_TARGET], s[_CHUNK_TARGET:]
        idx += 1
        slices.append((f"slice-{idx}", {"_slice": part}))
    return slices
