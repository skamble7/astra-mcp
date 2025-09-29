# File: servers/mcp-cobol-parser/mcp_cobol_parser/parsers/normalize/copybook_normalizer.py
from __future__ import annotations
from typing import Any, List, Optional
from ...models.cam_copybook import CamCopybook, CopyItem
from ...models.common import SourceRef

def _walk_cb2xml(el: dict) -> List[CopyItem]:
    # cb2xml structures vary by version; we try common shapes
    items = []
    # Typical: COBOL-COPYBOOK -> copybook -> item (recursive)
    # Fallback heuristic
    def mk(node: dict) -> CopyItem:
        level = str(node.get("@level", node.get("level", ""))).zfill(2)
        name = node.get("@name", node.get("name", "")).upper()
        pic = node.get("@picture", node.get("picture", "")) or ""
        occurs = node.get("@occurs") or node.get("occurs")
        children_raw = node.get("item") or node.get("children") or []
        if isinstance(children_raw, dict):
            children_raw = [children_raw]
        children = [_mk(c) for c in children_raw] if children_raw else None
        return CopyItem(level=level, name=name, picture=pic, occurs=(int(occurs) if occurs else None), children=children)

    def _mk(n):  # guard inner for recursion
        return mk(n)

    root_items = []
    # Find a plausible list of top-level items
    possible = []
    if "COBOL-COPYBOOK" in el:
        el = el["COBOL-COPYBOOK"]
    if "copybook" in el:
        el = el["copybook"]
    if "item" in el:
        possible = el["item"] if isinstance(el["item"], list) else [el["item"]]
    for node in possible:
        root_items.append(mk(node))
    return root_items

def normalize_cb2xml_tree(tree: dict, name: str, relpath: str, sha256: str) -> CamCopybook:
    items = _walk_cb2xml(tree)
    return CamCopybook(
        name=name,
        source=SourceRef(relpath=relpath, sha256=sha256),
        items=items
    )
