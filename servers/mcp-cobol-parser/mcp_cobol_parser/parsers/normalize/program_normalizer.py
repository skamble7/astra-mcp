# File: servers/mcp-cobol-parser/mcp_cobol_parser/parsers/normalize/program_normalizer.py
from __future__ import annotations
from typing import Any, List
from ...models.cam_program import CamProgram, ProgramDivisions, Paragraph, CallRef, IoOp
from ...models.common import SourceRef

def _as_note(key: str, val: Any) -> str:
    if val is None:
        return f"{key}=null"
    return f"{key}={val}"

def normalize_program_obj(obj: dict, relpath: str, sha256: str) -> CamProgram:
    """
    Normalize the JSON emitted by the Java bridge (JsonCli or CLI) into our CamProgram.
    We remain tolerant to different shapes and *do not* persist raw source.
    """
    # 1) Program id: prefer explicit 'program_id', fall back to Java 'programId'
    program_id = (obj.get("program_id") or obj.get("programId") or "").upper()

    # 2) Paragraphs / calls / io_ops if the upstream provides them (future-friendly)
    paragraphs: List[Paragraph] = []
    for p in obj.get("paragraphs", []):
        paragraphs.append(
            Paragraph(
                name=(p.get("name") or "").upper(),
                performs=[(s or "").upper() for s in p.get("performs", [])],
                calls=[CallRef(**c) for c in p.get("calls", [])],
                io_ops=[IoOp(**io) for io in p.get("io_ops", [])],
            )
        )

    # 3) Divisions – pass through dicts if present, else keep empty
    divs = obj.get("divisions", {}) or {}
    divs_model = ProgramDivisions(
        identification=divs.get("identification", {}) or {},
        environment=divs.get("environment", {}) or {},
        data=divs.get("data", {}) or {},
        procedure=divs.get("procedure", {}) or {},
    )

    # 4) Notes – capture “richer details” without changing schema
    notes: List[str] = []

    # Source format / engine markers from JsonCli
    if "sourceFormat" in obj:
        notes.append(_as_note("sourceFormat", obj.get("sourceFormat")))
    if "engine" in obj:
        notes.append(_as_note("engine", obj.get("engine")))

    # ASG counts if present
    if "cuCount" in obj:
        notes.append(_as_note("asg.cuCount", obj.get("cuCount")))
    if "progUnitCount" in obj:
        notes.append(_as_note("asg.progUnitCount", obj.get("progUnitCount")))

    # Keep a light fingerprint that raw source was embedded, but don't store it
    raw_src = obj.get("rawSource")
    if isinstance(raw_src, str):
        notes.append(_as_note("raw_source_embedded", True))
        notes.append(_as_note("raw_source_len", len(raw_src)))
    elif raw_src is not None:
        notes.append(_as_note("raw_source_embedded", True))
        # unknown type; don't compute length

    # 5) Copybooks – future-friendly passthrough to notes if present
    # (If you later extract copybooks on the Java side, you could switch to a structured field.)
    for k in ("copybooks", "copybooks_used"):
        if k in obj and isinstance(obj[k], list):
            notes.append(_as_note("copybooks.count", len(obj[k])))

    return CamProgram(
        program_id=program_id,
        source=SourceRef(relpath=relpath, sha256=sha256),
        divisions=divs_model,
        paragraphs=paragraphs,
        copybooks_used=[(c or "").upper() for c in obj.get("copybooks_used", [])],
        notes=notes,
    )