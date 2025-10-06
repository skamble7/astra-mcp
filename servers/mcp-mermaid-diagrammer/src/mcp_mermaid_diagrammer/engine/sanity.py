# servers/mcp-mermaid-diagrammer/src/mcp_mermaid_diagrammer/engine/sanity.py
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple

def sanitize_mermaid(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def build_view_header(view: str) -> str:
    v = (view or "").strip().lower()
    if v in {"flow", "flowchart", ""}:
        return "flowchart TD"
    if v in {"sequence", "sequencediagram"}:
        return "sequenceDiagram"
    if v == "mindmap":
        return "mindmap"
    if v == "class":
        return "classDiagram"
    if v in {"state", "statediagram"}:
        return "stateDiagram"
    if v in {"er", "erdiagram"}:
        return "erDiagram"
    if v == "journey":
        return "journey"
    if v == "gantt":
        return "gantt"
    if v == "component":
        # not a native directive, but authors usually map to flowchart
        return "flowchart TD"
    if v == "deployment":
        return "flowchart TD"
    if v == "timeline":
        return "timeline"
    return "flowchart TD"

def is_valid_mermaid(text: str, view: Optional[str] = None) -> bool:
    s = sanitize_mermaid(text)
    if not s:
        return False
    v = (view or "").strip().lower()

    if v in {"sequence", "sequencediagram"}:
        return s.startswith("sequenceDiagram")
    if v in {"flow", "flowchart"}:
        return bool(re.match(r"^flowchart\s+(TD|LR|BT|RL)\b", s, flags=re.IGNORECASE))
    if v == "mindmap":
        if not s.startswith("mindmap"):
            return False
        if "-->" in s:
            return False
        return True
    if v in {"class", "statediagram", "state"}:
        return s.startswith("classDiagram") or s.startswith("stateDiagram")
    if v in {"er", "erdiagram"}:
        return s.startswith("erDiagram")
    if v == "journey":
        return s.startswith("journey")
    if v == "gantt":
        return s.startswith("gantt")
    if v == "timeline":
        return s.startswith("timeline")

    # Default acceptance: known directives at start
    return bool(re.match(r"^(flowchart|sequenceDiagram|mindmap|classDiagram|stateDiagram|erDiagram|journey|gantt|timeline)\b", s))

# -------- Normalizers --------

_EDGE_RE = re.compile(r'^\s*([^-\s].*?)\s*-->\s*([^-\s].*?)\s*$')
_ARROW_PATTERNS = ["-->>", "->>", "-->", "->"]  # longest first

def normalize_flowchart(instr: str) -> str:
    """
    Light repairs for Mermaid flowcharts:
      - Replace empty nodes like  X()  with  X([ ])
      - Leave all other content intact
    """
    s = sanitize_mermaid(instr)
    if not re.match(r"^flowchart\s+(TD|LR|BT|RL)\b", s, flags=re.IGNORECASE):
        return s

    lines = [ln.rstrip() for ln in s.splitlines()]
    fixed: List[str] = []
    # Replace any identifier followed immediately by "()" with a blank label shape
    empty_node_re = re.compile(r"(\b[A-Za-z_][\w-]*)$begin:math:text$$end:math:text$")
    for ln in lines:
        ln = empty_node_re.sub(r"\1([ ])", ln)
        fixed.append(ln)
    return "\n".join(fixed)

def normalize_mindmap(instr: str) -> str:
    s = sanitize_mermaid(instr)
    if not s.lower().startswith("mindmap"):
        return s

    lines = [ln.rstrip() for ln in s.splitlines()]
    content = [ln for ln in lines[1:] if ln.strip()]

    nodes: Set[str] = set()
    children: Dict[str, List[str]] = {}
    parents: Dict[str, Set[str]] = {}
    explicit_roots: List[str] = []

    stack: List[Tuple[int, str]] = []
    for ln in content:
        if "-->" in ln:
            # illegal in mindmap; drop the line
            continue
        m = re.match(r"^(\s*)(.+)$", ln)
        if not m:
            continue
        indent = len(m.group(1))
        name = m.group(2).strip()
        if not name:
            continue
        nodes.add(name)
        if indent == 0:
            explicit_roots.append(name)
            stack = [(indent, name)]
        else:
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack:
                parent = stack[-1][1]
                children.setdefault(parent, [])
                if name not in children[parent]:
                    children[parent].append(name)
                parents.setdefault(name, set()).add(parent)
            stack.append((indent, name))

    # keep a single root
    if "MAIN" in nodes:
        root = "MAIN"
    else:
        root_candidates = [n for n in nodes if not parents.get(n)]
        root = (
            explicit_roots[0]
            if explicit_roots
            else (root_candidates[0] if root_candidates else (sorted(nodes)[0] if nodes else "ROOT"))
        )

    out: List[str] = ["mindmap"]
    visited: Set[str] = set()

    def dfs(node: str, depth: int) -> None:
        visited.add(node)
        out.append(f"{'  ' * (depth + 1)}{node}")
        for child in children.get(node, []):
            if child in visited:
                continue
            dfs(child, depth + 1)

    if nodes:
        dfs(root, 0)
        # orphan nodes
        for n in sorted(nodes):
            if n not in visited and n != root:
                dfs(n, 0)
    else:
        out.append("  MAIN")

    return "\n".join(out)

def _safe_seq_id(name: str) -> str:
    raw = name.strip()
    cleaned = re.sub(r"\W+", "_", raw)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "P"
    if not re.match(r"[A-Za-z_]", cleaned):
        cleaned = f"P_{cleaned}"
    return cleaned

def normalize_sequence(instr: str) -> str:
    s = sanitize_mermaid(instr)
    if not s.startswith("sequenceDiagram"):
        return s

    lines = [ln.rstrip() for ln in s.splitlines()]
    body = lines[1:]

    msgs: List[str] = []
    extras: List[str] = []
    actors: List[str] = []
    alias_map: Dict[str, str] = {}

    def parse_message(ln: str) -> Optional[str]:
        idx = -1
        arrow = ""
        for pat in _ARROW_PATTERNS:
            i = ln.find(pat)
            if i != -1:
                idx = i
                arrow = pat
                break
        if idx == -1:
            return None
        left = ln[:idx].strip()
        rest = ln[idx + len(arrow):].strip()
        if not left:
            return None

        if ":" in rest:
            recv, msg = rest.split(":", 1)
            recv = recv.strip()
            msg = msg.strip()
        else:
            parts = rest.split()
            if not parts:
                recv, msg = "", ""
            elif len(parts) == 1:
                recv, msg = parts[0], ""
            else:
                recv, msg = parts[0], " ".join(parts[1:])

        if not recv:
            return None

        s_id = alias_map.setdefault(left, _safe_seq_id(left))
        r_id = alias_map.setdefault(recv, _safe_seq_id(recv))
        if s_id not in actors:
            actors.append(s_id)
        if r_id not in actors:
            actors.append(r_id)

        msg = msg if msg else "call"
        return f"{s_id}{arrow}{r_id}: {msg}"

    for ln in body:
        if not ln.strip():
            continue
        if ln.strip().startswith("participant "):
            continue
        mm = parse_message(ln)
        if mm:
            msgs.append(mm)
        else:
            extras.append(ln)

    decls: List[str] = ["sequenceDiagram"]
    for orig, sid in alias_map.items():
        if sid == orig:
            decls.append(f"participant {sid}")
        else:
            decls.append(f'participant {sid} as "{orig}"')

    out = decls + msgs + extras
    if len(out) == 1:
        out.extend(["participant A", "participant B", "A->>B: call"])
    return "\n".join(out)