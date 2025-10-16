# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/tools/generate_document.py
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from typing import Any, Dict, Iterable, List

from ..models.params import GenerateParams
from ..utils.artifacts_fetch import (
    fetch_workspace_artifacts,
    fetch_kind_definition,
    shortlist_by_kinds,
)
from ..utils.io_paths import ensure_output_dir
from ..utils.checksums import sha256_of_file
from ..settings import Settings
from ..utils.storage import (
    upload_file_to_s3,
    build_public_download_url,
    generate_presigned_get_url,
)

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

# ----------------------- diagrams & renderers ----------------
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

# ------------------------ LLM chunking ------------------------
def _artifact_record_for_llm(a: Dict[str, Any]) -> Dict[str, Any]:
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
    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_size = 2  # for surrounding []
    for art in artifacts:
        record = _artifact_record_for_llm(art)
        rec_size = _json_size_bytes(record) + 1  # comma
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
    import asyncio as _asyncio
    from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
    import httpx

    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    target_bytes = int(os.getenv("LLM_CHUNK_TARGET_BYTES", "90000"))
    hard_cap_items = int(os.getenv("LLM_CHUNK_MAX_ITEMS", "10"))

    chunks = _chunk_artifacts_for_llm(selected_artifacts, target_bytes, hard_cap_items)
    total_parts = len(chunks) or 1

    client = AsyncOpenAI(api_key=api_key, timeout=settings.llm_request_timeout)

    max_tokens_env = (os.getenv("LLM_MAX_TOKENS") or "").strip().lower()
    set_max_tokens = None
    if max_tokens_env not in {"", "0", "-1", "none", "null"}:
        try:
            set_max_tokens = int(max_tokens_env)
        except Exception:
            set_max_tokens = settings.max_tokens

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

    async def _call_with_retries(req: Dict[str, Any], *, part_idx: int, json_bytes: int) -> str:
        backoff = 0.8
        last_err: Exception | None = None
        for attempt in range(1, 1 + 4):
            try:
                resp = await client.chat.completions.create(**req)
                return (resp.choices[0].message.content or "").strip()
            except (APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                last_err = e
                log.warning(f"llm.timeout part={part_idx} attempt={attempt} json_bytes={json_bytes}")
            except (RateLimitError,) as e:
                last_err = e
                log.warning(f"llm.rate_limited part={part_idx} attempt={attempt}")
            except (APIError, httpx.HTTPError) as e:
                last_err = e
                log.warning(f"llm.api_error part={part_idx} attempt={attempt} detail={e}")
            await _asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 10.0)
        raise last_err if last_err else RuntimeError("LLM call failed with unknown error")

    outputs: List[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        context = {
            "workspace": {"id": work_meta.get("workspace_id"), "part": idx, "of": total_parts},
            "artifacts": chunk,
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_preamble + "\n\nJSON Context:\n" + json.dumps(context, ensure_ascii=False)},
        ]
        req: Dict[str, Any] = {
            "model": settings.llm_model,
            "temperature": settings.temperature,
            "messages": messages,
        }
        if set_max_tokens is not None and set_max_tokens > 0:
            req["max_tokens"] = set_max_tokens

        json_bytes = _json_size_bytes(context)
        log.info(f"llm.call.begin model={settings.llm_model} part={idx}/{total_parts} artifacts_in_chunk={len(chunk)} json_bytes={json_bytes} timeout_sec={settings.llm_request_timeout}")
        try:
            text = await _call_with_retries(req, part_idx=idx, json_bytes=json_bytes)
            log.info(f"llm.call.success part={idx}/{total_parts} output_len={len(text)}")
        except Exception as e:
            log.error(f"llm.call.failed_after_retries part={idx}/{total_parts} error={e.__class__.__name__}: {e}")
            text = f"\n> _Note: generation for part {idx}/{total_parts} failed after retries ({e.__class__.__name__}). Skipping this part._\n"

        if text:
            if idx > 1 and not text.startswith("\n"):
                outputs.append("\n")
            outputs.append(text)

    return "\n".join(outputs).strip()

# ------------------------------- main -------------------------------
async def generate_workspace_document(params: GenerateParams) -> Dict[str, Any]:
    settings = Settings.from_env()

    # Print a clear S3 snapshot that survives basic formatters
    s3_snapshot = {
        "enabled": settings.s3_enabled,
        "endpoint": settings.s3_endpoint_url,
        "bucket": settings.s3_bucket,
        "prefix": settings.s3_prefix,
        "public_base": settings.s3_public_base_url,
        "public_read": settings.s3_public_read,
        "force_signed": settings.s3_force_signed,
        "presign_ttl": settings.s3_presign_ttl_seconds,
        "presign_base": settings.s3_presign_base_url,
    }
    log.info(
        "gen.begin "
        f"workspace_id={params.workspace_id} kind_id={params.kind_id} "
        f"llm_enabled={settings.enable_real_llm} llm_model={settings.llm_model} "
        f"artifact_service_url={settings.artifact_service_url} "
        f"s3={json.dumps(s3_snapshot, ensure_ascii=False)}"
    )

    # 1) Resolve workspace artifacts
    all_arts = await fetch_workspace_artifacts(params.workspace_id)
    log.info(f"gen.fetch.done artifact_count={len(all_arts)}")

    # 2) Resolve kind declaration
    kind_def = await fetch_kind_definition(params.kind_id)
    if not kind_def:
        raise RuntimeError(f"Kind not found: {params.kind_id}")

    # 3) Latest schema version
    versions = kind_def.get("schema_versions") or []
    latest_ver = kind_def.get("latest_schema_version")
    latest = next((v for v in versions if v.get("version") == latest_ver), versions[0] if versions else None)
    if latest is None:
        raise RuntimeError(f"No schema_versions available for kind: {params.kind_id}")

    # 4) Shortlist
    depends_on = latest.get("depends_on") or {}
    hard_kinds = depends_on.get("hard") or []
    soft_kinds = depends_on.get("soft") or []
    selected = shortlist_by_kinds(all_arts, hard_kinds, soft_kinds)

    # 5) Generate Markdown (deterministic, maybe replaced by LLM)
    driver_title = kind_def.get("title") or params.kind_id
    driver_kind = params.kind_id
    deterministic_md = _render_markdown_structured(params.workspace_id, driver_title, driver_kind, selected)

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
            if llm_md:
                final_md = llm_md
        except Exception:
            log.exception("llm.generation.failed")

    # 6) Optional length limit
    narratives = latest.get("narratives_spec") or {}
    max_chars = narratives.get("max_length_chars")
    if isinstance(max_chars, int) and max_chars > 0 and len(final_md) > max_chars:
        final_md = final_md[:max_chars]

    # 7) Write file locally
    out_dir = ensure_output_dir()
    filename = f"workspace_{params.workspace_id}_{driver_kind}_summary.md"
    path = out_dir / filename
    path.write_text(final_md, encoding="utf-8")
    sha = sha256_of_file(path)
    size = path.stat().st_size
    log.info(f"gen.write.ok path={path} size_bytes={len(final_md.encode('utf-8'))}")

    # 7b) Upload to Garage (S3) if configured
    storage_uri = f"file://{path}"
    download_url: str | None = None
    if settings.s3_enabled and settings.s3_bucket:
        key = f"{(settings.s3_prefix or 'workspace-docs').strip('/')}/{params.workspace_id}/{filename}"
        log.info(f"s3.plan bucket={settings.s3_bucket} key={key}")
        ok = upload_file_to_s3(
            settings=settings,
            local_path=path,
            bucket=settings.s3_bucket,
            key=key,
            content_type=MIME,
        )
        if ok:
            storage_uri = f"s3://{settings.s3_bucket}/{key}"

            # Choose link strategy: presign if forced OR no public base configured
            dl: str | None = None
            if settings.s3_force_signed or not settings.s3_public_base_url:
                dl = generate_presigned_get_url(
                    settings,
                    settings.s3_bucket,
                    key,
                    settings.s3_presign_ttl_seconds,
                )
                if dl:
                    log.info("s3.download_url.signed", extra={"ttl_sec": settings.s3_presign_ttl_seconds})
            else:
                dl = build_public_download_url(settings, settings.s3_bucket, key)
                if dl:
                    log.info(f"s3.download_url url={dl}")

            if dl:
                download_url = dl
            else:
                log.info("s3.download_url.unset", extra={"reason": "no public base and presign failed"})
    else:
        missing = []
        if not (settings.s3_endpoint_url or "").strip():
            missing.append("S3_ENDPOINT_URL")
        if not (settings.s3_access_key or "").strip():
            missing.append("S3_ACCESS_KEY")
        if not (settings.s3_secret_key or "").strip():
            missing.append("S3_SECRET_KEY")
        if not (settings.s3_bucket or "").strip():
            missing.append("S3_BUCKET")
        log.info(f"s3.skip_upload upload_skipped missing={','.join(missing) if missing else 'unknown'} s3_enabled={settings.s3_enabled}")

    # 8) Return artifact
    result: Dict[str, Any] = {
        "name": f"{driver_title} (Workspace {params.workspace_id})",
        "description": f"Generated descriptive document for {driver_kind}; based on depends_on hard/soft kinds over workspace artifacts.",
        "filename": filename,
        "path": str(path),
        "storage_uri": storage_uri,
        "download_url": download_url,
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
            "s3_bucket": settings.s3_bucket,
            "s3_key_prefix": settings.s3_prefix,
            "s3_endpoint": settings.s3_endpoint_url,
        },
    }

    log.info(f"gen.success workspace_id={params.workspace_id} driver_kind={driver_kind} uploaded={bool(download_url)} download_url={download_url}")
    return result