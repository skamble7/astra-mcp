# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/tools/generate_document.py
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from typing import Any, Dict, Iterable, List, Tuple

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

# We will honor mime_type from the LLM payload per kind prompt; this is only a fallback.
FALLBACK_MIME = "text/markdown"

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

# ------------------------ JSON parsing helpers ------------------------
def _extract_last_json_object(text: str) -> Dict[str, Any]:
    """
    Best-effort parser for cases where the model returns multiple JSON objects
    back-to-back. We walk the string and decode repeatedly; the last successful
    decode is returned.
    """
    text = text.strip()
    decoder = json.JSONDecoder()
    idx = 0
    last_obj: Dict[str, Any] | None = None
    while idx < len(text):
        # Skip leading non-json noise if any (should not occur with strict kinds)
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                last_obj = obj  # keep the last one
            idx = end
        except json.JSONDecodeError:
            # Move forward one char and try again (defensive)
            idx += 1
    if last_obj is None:
        raise ValueError("No JSON object could be decoded from LLM response.")
    return last_obj

# ------------------------ LLM (STRICTLY use kind's prompt.system) ------------------------
async def _llm_generate_with_kind_prompt_single_json(
    system_prompt: str,
    selected_artifacts: List[Dict[str, Any]],
    work_meta: Dict[str, Any],
    settings: Settings,
) -> str:
    """
    STRICT-JSON mode: send one request with full context and expect exactly one JSON object back.
    """
    from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
    import httpx
    import asyncio as _asyncio

    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = AsyncOpenAI(api_key=api_key, timeout=settings.llm_request_timeout)

    # Build one big context
    context = {
        "workspace": {"id": work_meta.get("workspace_id"), "part": 1, "of": 1},
        "artifacts": [_artifact_record_for_llm(a) for a in selected_artifacts],
    }
    user_payload = {"context": context}
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]

    req: Dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": settings.temperature,
        "messages": messages,
    }
    # Respect optional max tokens if user/environment configured
    max_tokens_env = (os.getenv("LLM_MAX_TOKENS") or "").strip().lower()
    if max_tokens_env not in {"", "0", "-1", "none", "null"}:
        try:
            req["max_tokens"] = int(max_tokens_env)
        except Exception:
            req["max_tokens"] = settings.max_tokens

    # Simple retry loop
    backoff = 0.8
    last_err: Exception | None = None
    for attempt in range(1, 1 + 4):
        try:
            jb = _json_size_bytes(user_payload)
            log.info(
                "llm.call.begin (strict) model=%s json_bytes=%s timeout_sec=%s",
                settings.llm_model, jb, settings.llm_request_timeout
            )
            resp = await client.chat.completions.create(**req)
            out = (resp.choices[0].message.content or "").strip()
            log.info("llm.call.success (strict) output_len=%s", len(out))
            return out
        except (APITimeoutError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            last_err = e
            log.warning("llm.timeout attempt=%s", attempt)
        except (RateLimitError,) as e:
            last_err = e
            log.warning("llm.rate_limited attempt=%s", attempt)
        except (APIError, httpx.HTTPError) as e:
            last_err = e
            log.warning("llm.api_error attempt=%s detail=%s", attempt, e)
        await _asyncio.sleep(backoff)
        backoff = min(backoff * 2.0, 10.0)
    raise last_err if last_err else RuntimeError("LLM call failed (strict mode)")

async def _llm_generate_with_kind_prompt_chunked_markdown(
    system_prompt: str,
    selected_artifacts: List[Dict[str, Any]],
    work_meta: Dict[str, Any],
    settings: Settings,
) -> str:
    """
    Non-strict mode (for kinds that want freeform/markdown and allow multi-part concatenation).
    """
    from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
    import httpx
    import asyncio as _asyncio

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
        user_payload = {"context": context}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]

        req: Dict[str, Any] = {
            "model": settings.llm_model,
            "temperature": settings.temperature,
            "messages": messages,
        }
        if set_max_tokens is not None and set_max_tokens > 0:
            req["max_tokens"] = set_max_tokens

        json_bytes = _json_size_bytes(user_payload)
        log.info(
            "llm.call.begin model=%s part=%s/%s artifacts_in_chunk=%s json_bytes=%s timeout_sec=%s",
            settings.llm_model, idx, total_parts, len(chunk), json_bytes, settings.llm_request_timeout
        )
        try:
            text = await _call_with_retries(req, part_idx=idx, json_bytes=json_bytes)
            log.info("llm.call.success part=%s/%s output_len=%s", idx, total_parts, len(text))
        except Exception as e:
            log.error(
                "llm.call.failed_after_retries part=%s/%s error=%s: %s",
                idx, total_parts, e.__class__.__name__, e
            )
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

    # 1) Resolve workspace artifacts (the *data* the prompt will operate on)
    all_arts = await fetch_workspace_artifacts(params.workspace_id)
    log.info(f"gen.fetch.done artifact_count={len(all_arts)}")

    # 2) Resolve kind declaration (the *instructions* live here)
    kind_def = await fetch_kind_definition(params.kind_id)
    if not kind_def:
        raise RuntimeError(f"Kind not found: {params.kind_id}")

    # 3) Latest schema version
    versions = kind_def.get("schema_versions") or []
    latest_ver = kind_def.get("latest_schema_version")
    latest = next((v for v in versions if v.get("version") == latest_ver), versions[0] if versions else None)
    if latest is None:
        raise RuntimeError(f"No schema_versions available for kind: {params.kind_id}")

    # 4) Shortlist the artifacts as directed by the kind's dependency declaration
    depends_on = latest.get("depends_on") or {}
    hard_kinds = depends_on.get("hard") or []
    soft_kinds = depends_on.get("soft") or []
    selected = shortlist_by_kinds(all_arts, hard_kinds, soft_kinds)

    # 5) Generate the document STRICTLY per the kind's prompt
    prompt_block = (latest.get("prompt") or {})
    system_prompt = prompt_block.get("system") or ""
    strict_json = bool(prompt_block.get("strict_json"))

    if not system_prompt.strip():
        # This server must NOT invent prompts. If none provided, fail clearly.
        raise RuntimeError(
            f"Artifact kind '{params.kind_id}' does not provide prompt.system; "
            "document generation is prompt-driven and cannot proceed without it."
        )
    if not settings.enable_real_llm:
        raise RuntimeError(
            "ENABLE_REAL_LLM is false; this server is prompt-driven and requires a live LLM."
        )

    try:
        if strict_json:
            llm_raw = await _llm_generate_with_kind_prompt_single_json(
                system_prompt=system_prompt,
                selected_artifacts=selected,
                work_meta={"workspace_id": params.workspace_id, "selected_count": len(selected)},
                settings=settings,
            )
        else:
            llm_raw = await _llm_generate_with_kind_prompt_chunked_markdown(
                system_prompt=system_prompt,
                selected_artifacts=selected,
                work_meta={"workspace_id": params.workspace_id, "selected_count": len(selected)},
                settings=settings,
            )
    except Exception:
        log.exception("llm.generation.failed")
        raise

    if not llm_raw or not isinstance(llm_raw, str):
        raise RuntimeError("Document generation produced no text.")

    # 6) Parse strict JSON envelope from the LLM and extract Markdown + metadata
    try:
        # For strict kinds, we still attempt recovery if multiple JSON objects appear.
        llm_obj = _extract_last_json_object(llm_raw) if strict_json else json.loads(llm_raw)
    except Exception as e:
        log.error("llm.json.parse.failed strict=%s raw_prefix=%s…", strict_json, llm_raw[:200].replace("\n", " "))
        raise RuntimeError(
            "Artifact kind declared strict_json, but LLM did not return a valid single JSON object."
        ) from e

    md_content = llm_obj.get("content")
    if not isinstance(md_content, str) or not md_content.strip():
        raise RuntimeError("LLM JSON missing non-empty string field `content`.")

    # Optional validation to help catch prompt deviations
    if not md_content.lstrip().startswith("# Data Pipeline Architecture Guidance"):
        log.warning("markdown.title.mismatch: content does not start with expected H1")

    # Adopt metadata from the LLM JSON, with sensible fallbacks
    doc_name = llm_obj.get("name") or "Data Pipeline Architecture Guidance"
    doc_desc = llm_obj.get("description") or "Architecture guidance document"
    filename_from_llm = llm_obj.get("filename") or f"workspace_{params.workspace_id}_data-pipeline-architecture-guidance.md"
    mime_from_llm = llm_obj.get("mime_type") or FALLBACK_MIME
    tags_from_llm = llm_obj.get("tags") or ["architecture", "guidance", "data-pipeline"]

    # 7) Optional length limit (still enforced if present in narratives_spec)
    narratives = latest.get("narratives_spec") or {}
    max_chars = narratives.get("max_length_chars")
    if isinstance(max_chars, int) and max_chars > 0 and len(md_content) > max_chars:
        md_content = md_content[:max_chars]

    # 8) Write file locally (use the filename from the LLM JSON when present)
    out_dir = ensure_output_dir()
    driver_title = kind_def.get("title") or params.kind_id
    driver_kind = params.kind_id  # e.g., cam.documents.data-pipeline-arch-guidance
    filename = filename_from_llm
    path = out_dir / filename
    path.write_text(md_content, encoding="utf-8")
    sha = sha256_of_file(path)
    size = path.stat().st_size
    log.info("gen.write.ok path=%s size_bytes=%s", path, len(md_content.encode("utf-8")))

    # 9) Upload to Garage (S3) if configured
    storage_uri = f"file://{path}"
    download_url: str | None = None
    if settings.s3_enabled and settings.s3_bucket:
        key = f"{(settings.s3_prefix or 'workspace-docs').strip('/')}/{params.workspace_id}/{filename}"
        log.info("s3.plan bucket=%s key=%s", settings.s3_bucket, key)
        ok = upload_file_to_s3(
            settings=settings,
            local_path=path,
            bucket=settings.s3_bucket,
            key=key,
            content_type=mime_from_llm,
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
                    log.info("s3.download_url url=%s", dl)

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
        log.info(
            "s3.skip_upload upload_skipped missing=%s s3_enabled=%s",
            ",".join(missing) if missing else "unknown",
            settings.s3_enabled,
        )

    # 10) Build CAM artifact payload
    #     The kind's json_schema applies to the **data** object; include LLM JSON + source hints.
    data_payload: Dict[str, Any] = dict(llm_obj)  # start with the model's JSON (name/filename/content/etc.)
    # Ensure key fields are present/normalized
    data_payload.setdefault("name", doc_name)
    data_payload.setdefault("description", doc_desc)
    data_payload.setdefault("filename", filename)
    data_payload.setdefault("mime_type", mime_from_llm)
    data_payload.setdefault("tags", tags_from_llm)

    # Add generator/source hints (schema allows additional properties)
    data_payload["workspace_id"] = params.workspace_id
    data_payload["source"] = {
        "path": str(path),
        "storage_uri": storage_uri,
        "download_url": download_url,
        "mime_type": mime_from_llm,
        "encoding": "utf-8",
        "size_bytes": size,
        "sha256": sha,
    }

    artifact: Dict[str, Any] = {
        "kind_id": driver_kind,  # e.g., cam.documents.data-pipeline-arch-guidance
        "name": f"{doc_name} (Workspace {params.workspace_id})",
        "data": data_payload,  # <-- matches the kind's json_schema
        # Convenience preview/metadata for UIs
        "preview": {"text_excerpt": md_content[:260]},
        "mime_type": mime_from_llm,
        "encoding": "utf-8",
        "filename": filename,
        "path": str(path),
        "storage_uri": storage_uri,
        "download_url": download_url,
        "checksum": {"sha256": sha},
        "tags": tags_from_llm,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }

    log.info(
        "gen.success workspace_id=%s driver_kind=%s uploaded=%s download_url=%s",
        params.workspace_id, driver_kind, bool(download_url), download_url
    )
    # IMPORTANT: wrap in artifacts[] so the conductor (artifacts_prop=artifacts) persists it
    return {"artifacts": [artifact]}