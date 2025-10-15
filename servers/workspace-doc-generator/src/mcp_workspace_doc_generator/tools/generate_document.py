# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/tools/generate_document.py
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import Any, Dict, Iterable, List, Tuple

from ..models.params import GenerateParams
from ..models.file_detail import FileDetail, Checksum
from ..utils.artifacts_fetch import fetch_workspace_artifacts
from ..utils.io_paths import ensure_output_dir
from ..utils.checksums import sha256_of_file
from ..settings import Settings

log = logging.getLogger("mcp.workspace.doc.generate")
MIME = "text/markdown"


# ---------------------------------------------------------------------
# Small generic helpers
# ---------------------------------------------------------------------
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

def _count_by_key(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        val = _safe_str(it.get(key, "")).lower()
        out[val] = out.get(val, 0) + 1
    return out

def _take(iterable: Iterable[Any], n: int) -> List[Any]:
    out: List[Any] = []
    for i, v in enumerate(iterable):
        if i >= n: break
        out.append(v)
    return out

def _flatten_scalar(value: Any, max_len: int = 120) -> str:
    """Render any value to a single-line scalar preview."""
    if _is_scalar(value):
        s = _safe_str(value)
    elif isinstance(value, (list, dict)):
        s = json.dumps(value, ensure_ascii=False)
    else:
        s = _safe_str(value)
    s = s.replace("\n", " ").strip()
    return (s[: max_len - 1] + "…") if len(s) > max_len else s


# ---------------------------------------------------------------------
# Diagram rendering (generic)
# ---------------------------------------------------------------------
def _render_diagrams(diagrams: Any) -> str:
    """
    Accept list of dicts; each dict can include:
      - language/type (e.g., 'mermaid', 'plantuml', 'dot', ...)
      - content/instructions/diagram/code (string payload)
      - name (caption)
    Render as fenced code blocks; default language = 'mermaid'.
    """
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
        )
        payload = _safe_str(payload).strip()
        name = _safe_str(d.get("name")).strip()
        if not payload:
            continue
        if name:
            lines.append(f"*{name}*")
        lines.append(f"```{language}\n{payload}\n```")
    lines.append("")  # trailing newline
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Descriptive English renderers (schema-agnostic)
# ---------------------------------------------------------------------
def _summarize_scalar_props(data: Dict[str, Any]) -> str:
    """
    Turn top-level scalar fields into a flowing sentence paragraph, e.g.:
    "It has foo=bar, count=3, enabled=true."
    """
    scalars = {k: v for k, v in data.items() if _is_scalar(v)}
    if not scalars:
        return ""
    parts = []
    for k, v in scalars.items():
        val = _flatten_scalar(v, 80)
        parts.append(f"{k}={val!s}")
    return "It exposes " + ", ".join(parts) + "."

def _summarize_source_block(data: Dict[str, Any]) -> str:
    """
    If a 'source' object exists, describe common fields (relpath, sha*, etc.) generically.
    """
    source = data.get("source")
    if not isinstance(source, dict):
        return ""
    bits: List[str] = []
    rel = source.get("relpath") or source.get("path")
    if rel:
        bits.append(f"path `{rel}`")
    # include any hash-like scalars
    for key in ("sha256", "sha1", "md5", "checksum"):
        if key in source and _is_scalar(source[key]):
            bits.append(f"{key}={_flatten_scalar(source[key], 80)}")
    if not bits:
        # fallback: mention presence
        return "It includes a source descriptor with additional metadata."
    return "Source: " + ", ".join(bits) + "."

def _bullet_list_from_scalar_list(values: List[Any], max_items: int = 12) -> List[str]:
    items = _take(values, max_items)
    out = [f"- { _flatten_scalar(v, 100) }" for v in items]
    if len(values) > max_items:
        out.append(f"- … {len(values) - max_items} more")
    return out

def _column_union(rows: List[Dict[str, Any]], max_cols: int = 6) -> List[str]:
    """Pick up to max_cols most frequent keys across row dicts for a compact table."""
    freq: Dict[str, int] = {}
    for r in rows:
        for k in r.keys():
            freq[k] = freq.get(k, 0) + 1
    # sort by frequency desc then name
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
        line_vals = []
        for c in cols:
            v = r.get(c)
            line_vals.append(_flatten_scalar(v, 60))
        lines.append("| " + " | ".join(line_vals) + " |")
    if len(rows) > max_rows:
        lines.append(f"| … {len(rows) - max_rows} more |" + " |" * (len(cols) - 1))
    return "\n".join(lines)

def _summarize_nested(data: Dict[str, Any]) -> str:
    """
    Describe non-scalar top-level fields:
      - lists of scalars → bulleted list
      - lists of objects → compact table
      - dicts → list keys & counts
    """
    lines: List[str] = []
    for key, val in data.items():
        if key == "source":  # handled separately
            continue
        if isinstance(val, list):
            lines.append(f"**`{key}`**: {len(val)} item(s).")
            if not val:
                continue
            if all(_is_scalar(x) for x in val):
                lines.extend(_bullet_list_from_scalar_list(val))
                lines.append("")  # spacing
            elif all(isinstance(x, dict) for x in val):
                tbl = _render_table(val)
                if tbl:
                    lines.append(tbl)
                    lines.append("")
                else:
                    # fallback bullets
                    lines.extend(_bullet_list_from_scalar_list(val))
                    lines.append("")
            else:
                # mixed list
                lines.extend(_bullet_list_from_scalar_list(val))
                lines.append("")
        elif isinstance(val, dict) and val:
            # summarize object keys
            kcount = len(val.keys())
            preview = ", ".join(f"`{k}`" for k in _take(val.keys(), 10))
            more = " …" if kcount > 10 else ""
            lines.append(f"**`{key}`**: object with {kcount} key(s): {preview}{more}")
    return "\n".join(lines).strip()

def _render_artifact_section(art: Dict[str, Any]) -> str:
    """
    Generic per-artifact, descriptive English. No schema assumptions.
    """
    name = _safe_str(art.get("name") or "(unnamed)")
    kind = _safe_str(art.get("kind") or "")
    aid  = _safe_str(art.get("artifact_id") or "")

    data = art.get("data") if isinstance(art.get("data"), dict) else {}
    lines: List[str] = []

    # Heading
    lines.append(f"### {name}\n")

    # Intro sentence
    intro_bits: List[str] = []
    if kind:
        intro_bits.append(f"kind `{kind}`")
    if aid:
        intro_bits.append(f"id `{aid}`")
    if intro_bits:
        lines.append(f"This artifact is {', '.join(intro_bits)}.")
    else:
        lines.append("This artifact is described by the fields below.")

    # Scalar properties paragraph
    scalar_para = _summarize_scalar_props(data)
    if scalar_para:
        lines.append(scalar_para)

    # Source paragraph (if present)
    src_para = _summarize_source_block(data)
    if src_para:
        lines.append(src_para)

    # Nested sections (lists/dicts)
    nested = _summarize_nested(data)
    if nested:
        lines.append(nested)

    # Diagrams
    diagrams_md = _render_diagrams(art.get("diagrams"))
    if diagrams_md.strip():
        lines.append(diagrams_md)

    # Spacing between artifacts
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Deterministic document (no JSON dumps)
# ---------------------------------------------------------------------
def _render_markdown_structured(workspace_id: str, prompt: str, artifacts: List[Dict[str, Any]]) -> str:
    total = len(artifacts)
    by_kind = _count_by_key(artifacts, "kind")

    lines: List[str] = []
    lines.append("# Overview\n")
    if total == 0:
        lines.append("This workspace contains **no artifacts**.\n")
        return "\n".join(lines)

    lines.append(f"This workspace contains **{total}** artifact(s).")
    if by_kind:
        parts = [f"{cnt} × `{k or '(empty-kind)'}`" for k, cnt in sorted(by_kind.items())]
        lines.append("- " + " · ".join(parts))
    if prompt.strip():
        lines.append(f"- **Prompt:** {prompt.strip()}")
    lines.append("")

    # Bucket by kind for readability (display original casing)
    kind_buckets: Dict[str, List[Dict[str, Any]]] = {}
    kind_display: Dict[str, str] = {}
    for art in artifacts:
        k_raw = _safe_str(art.get("kind"))
        k_key = k_raw.lower()
        kind_buckets.setdefault(k_key, []).append(art)
        if k_key not in kind_display:
            kind_display[k_key] = k_raw or "(empty-kind)"

    for k_key, bucket in sorted(kind_buckets.items(), key=lambda x: kind_display[x[0]].lower()):
        lines.append(f"## {kind_display[k_key]}\n")
        for art in bucket:
            lines.append(_render_artifact_section(art))

    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------------
# Optional LLM appendix (kept generic; safe to disable)
# ---------------------------------------------------------------------
async def _llm_generate_markdown_openai(
    prompt: str, workspace_id: str, context: List[Dict[str, Any]], settings: Settings
) -> str:
    from openai import AsyncOpenAI

    api_key = None
    for k in ("OPENAI_API_KEY", "OPENAI_APIKEY"):
        if not api_key:
            api_key = (os.getenv(k) or "").strip() or None
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    # Keep context lean and generic
    ctx_obj = {"workspace_id": workspace_id, "artifacts": context}
    ctx_str = json.dumps(ctx_obj, separators=(",", ":"), ensure_ascii=False)
    log.info("llm.context.size", extra={"bytes": len(ctx_str.encode('utf-8')), "artifacts": len(context)})

    client = AsyncOpenAI(api_key=api_key, timeout=120.0)
    max_tokens_env = (os.getenv("LLM_MAX_TOKENS") or "").strip().lower()
    omit_max_tokens = max_tokens_env in {"", "0", "-1", "none", "null"}
    effective_max_tokens = settings.max_tokens if not omit_max_tokens else None

    system = (
        "Append a short analytical section titled '## LLM Summary' that synthesizes patterns "
        "across artifacts without repeating lists verbatim. Do not invent facts."
    )
    user = f"User Prompt:\n{prompt.strip()}\n\nContext (truncated if large):\n{ctx_str}"

    req: Dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": settings.temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if effective_max_tokens is not None and effective_max_tokens > 0:
        req["max_tokens"] = effective_max_tokens

    log.info("llm.call.begin", extra={"model": settings.llm_model, "max_tokens": req.get("max_tokens", "omitted")})
    resp = await client.chat.completions.create(**req)
    text = (resp.choices[0].message.content or "").strip()
    log.info("llm.call.success", extra={"output_len": len(text)})
    return text


# ---------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------
async def generate_workspace_document(params: GenerateParams) -> Dict[str, Any]:
    settings = Settings.from_env()
    log.info(
        "gen.begin",
        extra={
            "workspace_id": params.workspace_id,
            "llm_enabled": settings.enable_real_llm,
            "llm_provider": settings.llm_provider,
            "artifact_service_url": settings.artifact_service_url,
        },
    )

    # 1) Fetch artifacts
    artifacts = await fetch_workspace_artifacts(params.workspace_id)
    log.info("gen.fetch.done", extra={"artifact_count": len(artifacts)})

    # 2) Deterministic, descriptive Markdown (no raw JSON anywhere)
    content = _render_markdown_structured(params.workspace_id, params.prompt, artifacts)

    # 3) Optional LLM appendix (generic; can be disabled via ENABLE_REAL_LLM)
    if settings.enable_real_llm and (settings.llm_provider or "").lower() == "openai":
        try:
            context_data = [
                {
                    "artifact_id": a.get("artifact_id"),
                    "kind": a.get("kind"),
                    "name": a.get("name"),
                    # keep it lean; LLM appendix is optional polish
                    "data_keys": list(a.get("data", {}).keys()) if isinstance(a.get("data"), dict) else [],
                    "has_diagrams": bool(a.get("diagrams")),
                }
                for a in artifacts
            ]
            appendix = await _llm_generate_markdown_openai(
                prompt=params.prompt,
                workspace_id=params.workspace_id,
                context=context_data,
                settings=settings,
            )
            if appendix:
                content += "\n" + appendix + "\n"
        except Exception:
            log.exception("gen.llm.failed")

    # 4) Write to disk
    out_dir = ensure_output_dir()
    filename = f"workspace_{params.workspace_id}_summary.md"
    fpath = out_dir / filename
    fpath.write_text(content, encoding="utf-8")
    log.info("gen.write.ok", extra={"path": str(fpath), "size_bytes": len(content.encode('utf-8'))})

    # 5) Metadata
    sha = sha256_of_file(fpath)
    size = fpath.stat().st_size
    file_detail = FileDetail(
        name=f"Workspace Summary ({params.workspace_id})",
        description="Generic descriptive workspace summary (Markdown) with diagram blocks; no raw JSON.",
        filename=filename,
        path=str(fpath),
        storage_uri=f"file://{fpath}",
        download_url=None,
        size_bytes=size,
        mime_type=MIME,
        encoding="utf-8",
        checksum=Checksum(sha256=sha),
        source_system="Astra Workspace Doc Generator",
        tags=["workspace", "summary", "markdown", "generic", "diagrams", "english"],
        created_at=_now_iso(),
        updated_at=_now_iso(),
        preview={"text_excerpt": content[:260]},
        metadata={
            "artifact_count": len(artifacts),
            "llm": settings.llm_model if settings.enable_real_llm else "disabled",
        },
    )
    log.info("gen.success", extra={"workspace_id": params.workspace_id})
    return file_detail.as_cam()