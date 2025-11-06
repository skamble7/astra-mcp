# File: servers/mcp-cobol-parser/mcp_cobol_parser/parsers/normalize/copybook_normalizer.py
from __future__ import annotations
from typing import Any, List, Optional, Union, Dict
from ...models.cam_copybook import CamCopybook, CopyItem
from ...models.common import SourceRef

def _walk_cb2xml(el: dict) -> List[CopyItem]:
    """
    Normalize cb2xml output to our CamCopybook tree.

    Notes:
    - Keep 'children' as the recursive property (schema expects it).
    - Do NOT force-cast 'occurs' to int; schema allows int|string|object|null.
    - Coerce 'level' to a zero-padded string when present, but accept ints/null.
    - Default 'picture' to "" if missing.
    """
    def _mk(node: dict) -> CopyItem:
        # level
        raw_level = node.get("@level", node.get("level"))
        if raw_level is None:
            level_val: Optional[Union[str, int]] = None
        else:
            # keep as string with zero-padding if it's numeric-ish; otherwise pass through
            try:
                level_val = str(int(str(raw_level).strip())).zfill(2)
            except Exception:
                level_val = str(raw_level)

        # name
        raw_name = node.get("@name", node.get("name"))
        name_val: Optional[str] = (str(raw_name).upper() if raw_name is not None else None)

        # picture
        pic = node.get("@picture", node.get("picture"))
        picture_val: Optional[str] = (pic if isinstance(pic, str) else "")
        if picture_val is None:
            picture_val = ""

        # occurs (int|string|object|null)
        occurs_val: Optional[Union[int, str, Dict[str, Any]]]
        occurs_raw = node.get("@occurs", node.get("occurs"))
        if occurs_raw is None:
            occurs_val = None
        else:
            # pass through object; keep strings as-is; convert purely numeric strings to int
            if isinstance(occurs_raw, dict):
                occurs_val = occurs_raw
            elif isinstance(occurs_raw, str):
                s = occurs_raw.strip()
                occurs_val = int(s) if s.isdigit() else s
            else:
                occurs_val = occurs_raw  # could already be int

        # children -> list of CopyItem | None
        children_raw = node.get("item") or node.get("children") or []
        if isinstance(children_raw, dict):
            children_raw = [children_raw]
        children_val = [_mk(c) for c in children_raw] if children_raw else None

        return CopyItem(
            level=level_val,
            name=name_val,
            picture=picture_val,
            occurs=occurs_val,
            children=children_val,
        )

    # locate top-level 'item' array inside cb2xml document
    doc = el
    if "COBOL-COPYBOOK" in doc:
        doc = doc["COBOL-COPYBOOK"]
    if "copybook" in doc:
        doc = doc["copybook"]

    items_section = doc.get("item")
    if items_section is None:
        return []

    top_nodes = items_section if isinstance(items_section, list) else [items_section]
    return [_mk(n) for n in top_nodes]

def _ensure_required_props_on_nodes(node: Dict[str, Any], relpath: str, sha256: str) -> None:
    """
    Recursively ensure each node carries schema-required properties:
      - items: list
      - source: object (we attach file-level source)
      - children: list
    """
    # items
    if "items" not in node or node["items"] is None or not isinstance(node["items"], list):
        node["items"] = []

    # source
    if "source" not in node or node["source"] is None or not isinstance(node["source"], dict):
        node["source"] = {"relpath": relpath, "sha256": sha256}

    # children
    children = node.get("children")
    if children is None or not isinstance(children, list):
        children = []
        node["children"] = children

    for ch in children:
        if isinstance(ch, dict):
            _ensure_required_props_on_nodes(ch, relpath, sha256)

def _postprocess_inject_required(copybook_dict: Dict[str, Any], relpath: str, sha256: str) -> Dict[str, Any]:
    """
    After model_dump, walk data.items[*] and ensure each nested node has
    'items' (list) and 'source' (object), and 'children' is always a list.
    """
    items = copybook_dict.get("items") or []
    if not isinstance(items, list):
        items = []
        copybook_dict["items"] = items

    for it in items:
        if isinstance(it, dict):
            _ensure_required_props_on_nodes(it, relpath, sha256)
    return copybook_dict

def normalize_cb2xml_tree(tree: dict, name: str, relpath: str, sha256: str) -> CamCopybook:
    items = _walk_cb2xml(tree)
    # Build the model first
    model = CamCopybook(
        name=name,
        source=SourceRef(relpath=relpath, sha256=sha256),
        items=items
    )
    # Convert to dict and inject required props expected by schema
    out = model.model_dump()
    out = _postprocess_inject_required(out, relpath=relpath, sha256=sha256)
    # Re-hydrate into the model type so callers can still .model_dump() consistently
    # (If your CamCopybook schema allows extra fields, this is optional. Safe to return as dict too.)
    return CamCopybook(**out)