# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/tools/generate_document.py
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..models.params import GenerateParams
from ..utils.artifacts_fetch import (
    fetch_workspace_artifacts,
    fetch_kind_definition,
    shortlist_by_kinds,
)
from ..utils.io_paths import ensure_output_dir
from ..utils.checksums import sha256_of_file
from ..settings import Settings

log = logging.getLogger("mcp.workspace.doc.generate")
MIME = "text/markdown"

# ----------------------- small helpers -----------------------
def _now_iso() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()

def _is_scalar(v: Any) -> bool:
    return isinstance(v, (str, int, float, bool)) or v is None

def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    try:
        return str(x)
    except Exception:
        return repr(x)

def _take(iterable: Iterable[Any], n: int) -> List[Any]:
    out: List[Any] = []
    for i, v in enumerate(iterable):
        if i >= n:
            break
        out.append(v)
    return out

def _flatten_scalar(value: Any, max_len: int = 120) -> str:
    if _is_scalar(value):
        s = _safe_str(value)
    elif isinstance(value, (list, dict)):
        s = json.dumps(value, ensure_ascii=False)
    else:
        s = _safe_str(value)
    s = s.replace("\n", " ").strip()
    return (s[: max_len - 1] + "…") if len(s) > max_len else s

def _json_size_bytes(obj: Any) -> int:
    try:
        return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return 0

# ----------------------- diagrams -----------------------
def _render_diagrams(diagrams: Any) -> str:
    if not isinstance(diagrams, list) or not diagrams:
        return ""
    lines: List[str] = []
    lines.append("#### Diagram(s)\n")
    for d in diagrams:
        if not isinstance(d, dict):
            continue
        language = (d.get("language") or d.get("type") or "mermaid") or "mermaid"
        payload = (
            d.get("content")
            or d.get("instructions")
            or d.get("diagram")
            or d.get("code")
            or ""
        ).strip()
        name = _safe_str(d.get("name")).strip()
        if not payload:
            continue
        if name:
            lines.append(f"*{name}*")
        lines.append(f"```{language}\n{payload}\n```")
    lines.append("")
    return "\n".join(lines)

# ---------------- descriptive renderers (generic) ----------------
def _summarize_scalar_props(data: Dict[str, Any]) -> str:
    scalars = {k: v for k, v in data.items() if _is_scalar(v)}
    if not scalars:
        return ""
    parts = [f"{k}={_flatten_scalar(v, 80)}" for k, v in scalars.items()]
    return "It exposes " + ", ".join(parts) + "."

def _summarize_source_block(data: Dict[str, Any]) -> str:
    src = data.get("source")
    if not isinstance(src, dict):
        return ""
    bits: List[str] = []
    rel = src.get("relpath") or src.get("path")
    if rel:
        bits.append(f"path `{rel}`")
    for key in ("sha256", "sha1", "md5", "checksum"):
        if key in src and _is_scalar(src[key]):
            bits.append(f"{key}={_flatten_scalar(src[key], 80)}")
    return "Source: " + ", ".join(bits) + "." if bits else "It includes a source descriptor with additional metadata."

def _bullet_list_from_scalar_list(values: List[Any], max_items: int = 12) -> List[str]:
    items = _take(values, max_items)
    out = [f"- {_flatten_scalar(v, 100)}" for v in items]
    if len(values) > max_items:
        out.append(f"- … {len(values) - max_items} more")
    return out

def _column_union(rows: List[Dict[str, Any]], max_cols: int = 6) -> List[str]:
    freq: Dict[str, int] = {}
    for r in rows:
        for k in r.keys():
            freq[k] = freq.get(k, 0) + 1
    cols = sorted(freq.keys(), key=lambda k: (-freq[k], k))
    return cols[:max_cols]

def _render_table(rows: List[Dict[str, Any]], max_rows: int = 15) -> str:
    if not rows:
        return ""
    cols = _column_union(rows)
    if not cols:
        return ""
    lines = []
    lines.append("| " + " | ".join(f"`{c}`" for c in cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for r in _take(rows, max_rows):
        lines.append("| " + " | ".join(_flatten_scalar(r.get(c), 60) for c in cols) + " |")
    if len(rows) > max_rows:
        lines.append(f"| … {len(rows) - max_rows} more |" + " |" * (len(cols) - 1))
    return "\n".join(lines)

def _summarize_nested(data: Dict[str, Any]) -> str:
    lines: List[str] = []
    for key, val in data.items():
        if key == "source":
            continue
        if isinstance(val, list):
            lines.append(f"**`{key}`**: {len(val)} item(s).")
            if not val:
                continue
            if all(_is_scalar(x) for x in val):
                lines.extend(_bullet_list_from_scalar_list(val))
                lines.append("")
            elif all(isinstance(x, dict) for x in val):
                tbl = _render_table(val)
                lines.append(tbl or "")
                lines.append("")
            else:
                lines.extend(_bullet_list_from_scalar_list(val))
                lines.append("")
        elif isinstance(val, dict) and val:
            kcount = len(val.keys())
            preview = ", ".join(f"`{k}`" for k in _take(val.keys(), 10))
            more = " …" if kcount > 10 else ""
            lines.append(f"**`{key}`**: object with {kcount} key(s): {preview}{more}")
    return "\n".join(lines).strip()

def _render_artifact_section(art: Dict[str, Any]) -> str:
    name = _safe_str(art.get("name") or "(unnamed)")
    kind = _safe_str(art.get("kind") or "")
    aid = _safe_str(art.get("artifact_id") or "")
    data = art.get("data") if isinstance(art.get("data"), dict) else {}

    lines: List[str] = []
    lines.append(f"### {name}\n")

    intro_bits: List[str] = []
    if kind:
        intro_bits.append(f"kind `{kind}`")
    if aid:
        intro_bits.append(f"id `{aid}`")
    lines.append(
        f"This artifact is {', '.join(intro_bits)}."
        if intro_bits
        else "This artifact is described by the fields below."
    )

    scalar_para = _summarize_scalar_props(data)
    if scalar_para:
        lines.append(scalar_para)

    src_para = _summarize_source_block(data)
    if src_para:
        lines.append(src_para)

    nested = _summarize_nested(data)
    if nested:
        lines.append(nested)

    diagrams_md = _render_diagrams(art.get("diagrams"))
    if diagrams_md.strip():
        lines.append(diagrams_md)

    lines.append("")
    return "\n".join(lines)

def _render_markdown_structured(
    workspace_id: str,
    driver_title: str,
    driver_kind: str,
    selected: List[Dict[str, Any]],
) -> str:
    total = len(selected)
    lines: List[str] = []
    lines.append("# Overview\n")
    lines.append(
        f"This document was generated for **`{driver_title}`** (kind `{driver_kind}`) in workspace `{workspace_id}`."
    )
    lines.append(
        f"It summarizes **{total}** related artifact(s) selected via the kind’s dependency rules.\n"
    )

    # group by kind
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    display: Dict[str, str] = {}
    for a in selected:
        k_raw = _safe_str(a.get("kind"))
        k_key = k_raw.lower()
        buckets.setdefault(k_key, []).append(a)
        if k_key not in display:
            display[k_key] = k_raw or "(empty-kind)"

    for k_key, items in sorted(buckets.items(), key=lambda x: display[x[0]].lower()):
        lines.append(f"## {display[k_key]}\n")
        for art in items:
            lines.append(_render_artifact_section(art))

    return "\n".join(lines).strip() + "\n"

# ------------------------ LLM CHUNKING SUPPORT ------------------------
def _artifact_record_for_llm(a: Dict[str, Any]) -> Dict[str, Any]:
    """Pass full data + diagrams so the model can write accurate summaries and include Mermaid blocks."""
    return {
        "artifact_id": a.get("artifact_id"),
        "kind": a.get("kind"),
        "name": a.get("name"),
        "data": a.get("data"),
        "diagrams": a.get("diagrams"),
    }

def _chunk_artifacts_for_llm(
    artifacts: List[Dict[str, Any]],
    target_bytes: int,
    hard_cap_items: int,
) -> List[List[Dict[str, Any]]]:
    """
    Greedy chunker: groups artifact records so that the JSON size of each chunk is <= target_bytes
    and item count per chunk <= hard_cap_items.
    """
    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_size = 2  # for surrounding []
    for art in artifacts:
        record = _artifact_record_for_llm(art)
        rec_size = _json_size_bytes(record) + 1  # comma
        # Start a new chunk if adding this overflows byte budget or item cap
        if current and (current_size + rec_size > target_bytes or len(current) >= hard_cap_items):
            chunks.append(current)
            current = []
            current_size = 2
        current.append(record)
        current_size += rec_size
    if current:
        chunks.append(current)
    return chunks

# ------------------------ LLM (use kind's prompt.system) ------------------------
async def _llm_generate_with_kind_prompt(
    system_prompt: str,
    selected_artifacts: List[Dict[str, Any]],
    work_meta: Dict[str, Any],
    settings: Settings,
) -> str:
    """
    Uses the kind's 'prompt.system' as the system message to generate descriptive Markdown.
    Sends full artifact 'data' and 'diagrams' to the LLM. If the payload is large, we split into
    chunks and call the model per-chunk, concatenating the results.
    """
    from openai import AsyncOpenAI

    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    # Chunking parameters (tunable via env)
    # Budget is approximate since we use JSON byte size; defaults are conservative.
    target_bytes = int(os.getenv("LLM_CHUNK_TARGET_BYTES", "110000"))  # ~110 KB JSON per chunk
    hard_cap_items = int(os.getenv("LLM_CHUNK_MAX_ITEMS", "12"))       # at most 12 artifacts per chunk

    # Prepare chunks
    chunks = _chunk_artifacts_for_llm(selected_artifacts, target_bytes, hard_cap_items)
    total_parts = len(chunks) or 1

    client = AsyncOpenAI(api_key=api_key, timeout=120.0)

    # Token limit handling
    max_tokens_env = (os.getenv("LLM_MAX_TOKENS") or "").strip().lower()
    set_max_tokens = None
    if max_tokens_env not in {"", "0", "-1", "none", "null"}:
        try:
            set_max_tokens = int(max_tokens_env)
        except Exception:
            set_max_tokens = settings.max_tokens

    # Compose common instructions
    user_preamble = (
        "Create a descriptive **Markdown** document summarizing the COBOL-specific artifacts in this workspace. "
        "For each artifact:\n"
        "- Write a brief English summary using the fields found in its `data` object (e.g., divisions, paragraphs, copybooks, source path/hashes).\n"
        "- If the artifact includes any diagram instructions, include them exactly as fenced code blocks using the correct language "
        "(default to `mermaid` if unspecified). Do not alter the diagram code.\n"
        "- Do not invent fields; only describe what's present in the provided JSON.\n"
        "- Keep the structure clean with headings per artifact.\n\n"
        "You will receive the artifacts in one or more parts. Summarize only the artifacts present in the current part."
    )

    outputs: List[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        context = {
            "workspace": {"id": work_meta.get("workspace_id"), "part": idx, "of": total_parts},
            "artifacts": chunk,
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_preamble
                + "\n\nJSON Context:\n"
                + json.dumps(context, ensure_ascii=False),
            },
        ]
        req: Dict[str, Any] = {
            "model": settings.llm_model,
            "temperature": settings.temperature,
            "messages": messages,
        }
        if set_max_tokens is not None and set_max_tokens > 0:
            req["max_tokens"] = set_max_tokens

        log.info(
            "llm.call.begin",
            extra={
                "model": settings.llm_model,
                "part": idx,
                "of": total_parts,
                "artifacts_in_chunk": len(chunk),
                "json_bytes": _json_size_bytes(context),
            },
        )
        resp = await client.chat.completions.create(**req)
        text = (resp.choices[0].message.content or "").strip()
        log.info("llm.call.success", extra={"output_len": len(text), "part": idx, "of": total_parts})
        if text:
            # Add a small separator to avoid header collisions across parts
            if idx > 1 and not text.startswith("\n"):
                outputs.append("\n")
            outputs.append(text)

    return "\n".join(outputs).strip()

# ------------------------------- main -------------------------------
async def generate_workspace_document(params: GenerateParams) -> Dict[str, Any]:
    settings = Settings.from_env()
    log.info(
        "gen.begin",
        extra={
            "workspace_id": params.workspace_id,
            "kind_id": params.kind_id,
            "llm_enabled": settings.enable_real_llm,
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "artifact_service_url": settings.artifact_service_url,
        },
    )

    # 1) Resolve workspace artifacts (actual instances)
    all_arts = await fetch_workspace_artifacts(params.workspace_id)
    log.info("gen.fetch.done", extra={"artifact_count": len(all_arts)})

    # 2) Resolve kind declaration (template)
    kind_def = await fetch_kind_definition(params.kind_id)
    if not kind_def:
        raise RuntimeError(f"Kind not found: {params.kind_id}")

    # 3) Pick latest schema version block
    versions = kind_def.get("schema_versions") or []
    latest_ver = kind_def.get("latest_schema_version")
    latest = None
    for v in versions:
        if v.get("version") == latest_ver:
            latest = v
            break
    if latest is None and versions:
        latest = versions[0]
    if latest is None:
        raise RuntimeError(f"No schema_versions available for kind: {params.kind_id}")

    # 4) Dependency shortlist
    depends_on = latest.get("depends_on") or {}
    hard_kinds = depends_on.get("hard") or []
    soft_kinds = depends_on.get("soft") or []
    selected = shortlist_by_kinds(all_arts, hard_kinds, soft_kinds)

    # 5) Generate Markdown
    driver_title = kind_def.get("title") or params.kind_id
    driver_kind = params.kind_id
    deterministic_md = _render_markdown_structured(
        params.workspace_id, driver_title, driver_kind, selected
    )

    final_md = deterministic_md
    system_prompt = (latest.get("prompt") or {}).get("system") or ""
    if settings.enable_real_llm and system_prompt.strip():
        try:
            llm_md = await _llm_generate_with_kind_prompt(
                system_prompt=system_prompt,
                selected_artifacts=selected,
                work_meta={"workspace_id": params.workspace_id, "selected_count": len(selected)},
                settings=settings,
            )
            # Prefer LLM content if it exists; otherwise keep deterministic
            if llm_md:
                final_md = llm_md
        except Exception:
            log.exception("llm.generation.failed")

    # 6) (Optional) enforce narratives_spec limits
    narratives = latest.get("narratives_spec") or {}
    max_chars = narratives.get("max_length_chars")
    if isinstance(max_chars, int) and max_chars > 0 and len(final_md) > max_chars:
        final_md = final_md[:max_chars]

    # 7) Write file (we still materialize a Markdown file for convenience)
    out_dir = ensure_output_dir()
    filename = f"workspace_{params.workspace_id}_{driver_kind}_summary.md"
    path = out_dir / filename
    path.write_text(final_md, encoding="utf-8")
    sha = sha256_of_file(path)
    size = path.stat().st_size
    log.info("gen.write.ok", extra={"path": str(path), "size_bytes": len(final_md.encode('utf-8'))})

    # 8) Return value MUST conform to the kind's schema (usually permissive).
    result: Dict[str, Any] = {
        "name": f"{driver_title} (Workspace {params.workspace_id})",
        "description": f"Generated descriptive document for {driver_kind}; based on depends_on hard/soft kinds over workspace artifacts.",
        "filename": filename,
        "path": str(path),
        "storage_uri": f"file://{path}",
        "size_bytes": size,
        "mime_type": MIME,
        "encoding": "utf-8",
        "checksum": {"sha256": sha},
        "source_system": "Astra Workspace Doc Generator",
        "tags": ["workspace", "summary", "markdown", "generic", "diagrams"],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "preview": {"text_excerpt": final_md[:260]},
        "metadata": {
            "workspace_id": params.workspace_id,
            "kind_id": params.kind_id,
            "selected_count": len(selected),
            "llm": settings.llm_model if settings.enable_real_llm and system_prompt.strip() else "disabled",
        },
    }

    log.info("gen.success", extra={"workspace_id": params.workspace_id, "driver_kind": driver_kind})
    return result