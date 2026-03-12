# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/tools/generate_document.py
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from ..models.params import GenerateParams
from ..settings import Settings
from ..utils.artifacts_fetch import (
    fetch_workspace_artifacts,
    fetch_kind_definition,
    resolve_kind_aliases,
    shortlist_by_kinds_alias_aware,
)
from ..utils.checksums import sha256_of_file
from ..utils.io_paths import ensure_output_dir
from ..utils.storage import (
    upload_file_to_s3,
    build_public_download_url,
    generate_presigned_get_url,
)

log = logging.getLogger("mcp.workspace.doc.generate")

FALLBACK_MIME = "text/markdown"
RUN_INPUTS_KIND = "cam.inputs.raina"


def _now_iso() -> str:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()


def _json_size_bytes(obj: Any) -> int:
    try:
        return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return 0


def _extract_last_json_object(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    decoder = json.JSONDecoder()
    idx = 0
    last_obj: Dict[str, Any] | None = None

    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                last_obj = obj
            idx = end
        except json.JSONDecodeError:
            idx += 1

    if last_obj is None:
        raise ValueError("No JSON object could be decoded from LLM response.")
    return last_obj


def _pick_best_run_inputs_artifact(all_arts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = [a for a in all_arts if a.get("kind") == RUN_INPUTS_KIND]
    if not candidates:
        return None

    def _ts(a: Dict[str, Any]) -> str:
        def _get_date(field: str) -> str:
            v = a.get(field)
            if isinstance(v, str):
                return v
            if isinstance(v, dict) and "$date" in v and isinstance(v["$date"], str):
                return v["$date"]
            return ""

        return _get_date("updated_at") or _get_date("created_at") or ""

    candidates.sort(key=_ts)
    return candidates[-1]


def _render_kind_prompt(system_prompt: str, *, run_inputs_obj: Any, dependencies_obj: Any) -> str:
    run_inputs_text = json.dumps(run_inputs_obj, ensure_ascii=False, indent=2)
    deps_text = json.dumps(dependencies_obj, ensure_ascii=False, indent=2)
    return system_prompt.replace("{{RUN_INPUTS}}", run_inputs_text).replace("{{DEPENDENCIES}}", deps_text)


def _present_kinds_set(all_arts: List[Dict[str, Any]]) -> Set[str]:
    return {k for k in (a.get("kind") for a in all_arts) if isinstance(k, str) and k.strip()}


def _missing_required_by_equivalence(present_kinds: Set[str], required_equivalence: Dict[str, Set[str]]) -> List[str]:
    missing: List[str] = []
    for canonical, eqset in (required_equivalence or {}).items():
        if not (present_kinds & set(eqset)):
            missing.append(canonical)
    return missing


# ---------------- Option C++: Retrieval helpers ----------------
def _truncate_preview(
    v: Any,
    *,
    max_chars: int,
    array_items: int,
    object_keys: int,
) -> Tuple[Any, bool]:
    truncated = False

    if v is None or isinstance(v, (str, int, float, bool)):
        if isinstance(v, str) and len(v) > max_chars:
            return v[:max_chars] + "…", True
        return v, False

    if isinstance(v, list):
        if len(v) > array_items:
            truncated = True
            v2 = v[:array_items]
        else:
            v2 = v
        out_list = []
        for item in v2:
            pv, t = _truncate_preview(item, max_chars=max_chars, array_items=array_items, object_keys=object_keys)
            truncated = truncated or t
            out_list.append(pv)
        if truncated:
            out_list.append({"_truncated": True, "_note": f"list truncated to {array_items} items"})
        return out_list, truncated

    if isinstance(v, dict):
        keys = list(v.keys())
        if len(keys) > object_keys:
            truncated = True
            keys2 = keys[:object_keys]
        else:
            keys2 = keys
        out: Dict[str, Any] = {}
        for k in keys2:
            pv, t = _truncate_preview(v.get(k), max_chars=max_chars, array_items=array_items, object_keys=object_keys)
            truncated = truncated or t
            out[str(k)] = pv
        if truncated:
            out["_truncated"] = True
            out["_note"] = f"object truncated to {object_keys} keys"
        return out, truncated

    try:
        s = str(v)
        if len(s) > max_chars:
            return s[:max_chars] + "…", True
        return s, False
    except Exception:
        return repr(v)[:max_chars] + "…", True


def _get_by_path(obj: Any, path: str) -> Any:
    if not path:
        return None

    cur: Any = obj
    parts = path.split(".")
    for part in parts:
        if cur is None:
            return None

        if "[" in part and part.endswith("]"):
            name, _, idx_part = part.partition("[")
            idx_str = idx_part[:-1]
            if name:
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(name)
            if not isinstance(cur, list):
                return None
            try:
                idx = int(idx_str)
            except Exception:
                return None
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
            continue

        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None

    return cur


def _artifact_index_record(a: Dict[str, Any], settings: Settings) -> Dict[str, Any]:
    data = a.get("data")
    top_keys: List[str] = []
    if isinstance(data, dict):
        top_keys = [str(k) for k in list(data.keys())[: settings.doc_index_top_keys_limit]]

    return {
        "artifact_id": a.get("artifact_id"),
        "kind": a.get("kind"),
        "name": a.get("name"),
        "version": a.get("version"),
        "approx_data_bytes": _json_size_bytes(data),
        "data_shape": {"top_keys": top_keys},
    }


def _find_artifact_by_id(all_arts: List[Dict[str, Any]], artifact_id: str) -> Optional[Dict[str, Any]]:
    aid = (artifact_id or "").strip()
    if not aid:
        return None
    for a in all_arts:
        if a.get("artifact_id") == aid:
            return a
    return None


def _fulfill_requests(
    *,
    requests: List[Dict[str, Any]],
    all_arts: List[Dict[str, Any]],
    settings: Settings,
) -> Tuple[List[Dict[str, Any]], Set[str], int]:
    retrieved: List[Dict[str, Any]] = []
    covered: Set[str] = set()
    total_chars = 0

    reqs = requests[: settings.doc_request_max_items]

    for r in reqs:
        aid = (r.get("artifact_id") or "").strip()
        if not aid:
            continue

        art = _find_artifact_by_id(all_arts, aid)
        if not art:
            retrieved.append({"artifact_id": aid, "error": "not_found"})
            continue

        paths = r.get("paths")
        if not isinstance(paths, list) or not paths:
            paths = ["data"]

        max_chars = r.get("max_chars")
        if not isinstance(max_chars, int) or max_chars <= 0:
            max_chars = settings.doc_slice_max_chars
        max_chars = min(max_chars, settings.doc_slice_max_chars)

        slices: Dict[str, Any] = {}
        trunc: Dict[str, bool] = {}

        for p in paths:
            if not isinstance(p, str) or not p.strip():
                continue
            raw_val = _get_by_path(art, p.strip())
            preview, was_trunc = _truncate_preview(
                raw_val,
                max_chars=max_chars,
                array_items=settings.doc_large_array_preview_items,
                object_keys=settings.doc_large_object_preview_keys,
            )
            try:
                s = json.dumps(preview, ensure_ascii=False)
                total_chars += len(s)
            except Exception:
                total_chars += min(max_chars, 256)

            slices[p.strip()] = preview
            trunc[p.strip()] = bool(was_trunc)

            if total_chars >= settings.doc_total_retrieved_max_chars:
                break

        retrieved.append(
            {
                "artifact_id": art.get("artifact_id"),
                "kind": art.get("kind"),
                "name": art.get("name"),
                "version": art.get("version"),
                "approx_data_bytes": _json_size_bytes(art.get("data")),
                "slices": slices,
                "truncated": trunc,
            }
        )
        if isinstance(art.get("artifact_id"), str):
            covered.add(art["artifact_id"])

        if total_chars >= settings.doc_total_retrieved_max_chars:
            break

    return retrieved, covered, total_chars


def _auto_page_requests(
    *,
    all_ids: List[str],
    already_seen: Set[str],
    settings: Settings,
) -> List[Dict[str, Any]]:
    """
    Server-driven paging: force the model to see every artifact at least once.
    This is generic and does not assume any domain.
    """
    if not settings.doc_auto_page_enabled:
        return []

    remaining = [aid for aid in all_ids if aid and aid not in already_seen]
    batch = remaining[: settings.doc_auto_page_batch_size]
    if not batch:
        return []

    return [
        {
            "artifact_id": aid,
            "paths": list(settings.doc_auto_page_paths),
            "max_chars": settings.doc_slice_max_chars,
        }
        for aid in batch
    ]


def _protocol_preamble() -> str:
    return (
        "You are generating a guidance document for a workspace, driven by the provided kind prompt.\n"
        "You will first receive an artifact_index. You will then receive artifact slices in batches.\n\n"
        "OUTPUT MUST ALWAYS BE ONE JSON OBJECT (no prose).\n\n"
        "Two allowed shapes:\n"
        "1) Ask for more details:\n"
        '{ "requests": [ { "artifact_id":"...", "paths":["data","diagrams"], "max_chars": 14000 } ], "notes":"..." }\n'
        "2) Produce final:\n"
        '{ "final": { "name":"...", "description":"...", "filename":"...", "mime_type":"text/markdown", '
        '"tags":[...], "content":"...markdown...", "covered_artifact_ids":[...], '
        '"coverage_map": { "<artifact_id>": { "kind":"...", "used_in_sections":[...], "key_points":[...] } } } }\n\n'
        "CRITICAL COVERAGE RULES:\n"
        "- You MUST base the document on ALL artifacts.\n"
        "- You may NOT produce final until you have been given slices for every artifact.\n"
        "- In final, `covered_artifact_ids` must match ALL artifact IDs exactly.\n"
        "- In final, `coverage_map` must contain an entry for every artifact_id.\n\n"
        "Write artifact-driven guidance: extract specifics (services, events, rules, data stores, workflows, boundaries) from artifacts.\n"
        "If something is missing, explicitly call it out as an open question tied to the artifact(s) you inspected.\n"
    )


async def _llm_chat_strict_json(*, messages: List[Dict[str, str]], settings: Settings) -> str:
    from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
    import httpx
    import asyncio as _asyncio

    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_APIKEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = AsyncOpenAI(api_key=api_key, timeout=settings.llm_request_timeout)

    req: Dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": settings.temperature,
        "messages": messages,
    }

    max_tokens_env = (os.getenv("LLM_MAX_TOKENS") or "").strip().lower()
    if max_tokens_env not in {"", "0", "-1", "none", "null"}:
        try:
            req["max_tokens"] = int(max_tokens_env)
        except Exception:
            req["max_tokens"] = settings.max_tokens

    backoff = settings.llm_retry_backoff_initial
    last_err: Exception | None = None

    for attempt in range(1, 1 + settings.llm_max_retries):
        try:
            log.info("llm.call.begin model=%s msg_count=%s", settings.llm_model, len(messages))
            resp = await client.chat.completions.create(**req)
            out = (resp.choices[0].message.content or "").strip()
            log.info("llm.call.success output_len=%s", len(out))
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
        backoff = min(backoff * 2.0, settings.llm_retry_backoff_max)

    raise last_err if last_err else RuntimeError("LLM call failed (retrieval mode)")


def _validate_final(
    *,
    final_obj: Dict[str, Any],
    all_ids: List[str],
    seen_ids: Set[str],
) -> Tuple[bool, str]:
    # Require content
    md = final_obj.get("content")
    if not isinstance(md, str) or not md.strip():
        return False, "final_missing_content"

    # Require strict coverage: declared must match actual workspace list
    covered = final_obj.get("covered_artifact_ids")
    if not isinstance(covered, list):
        return False, "final_missing_covered_artifact_ids"
    covered_set = {x for x in covered if isinstance(x, str) and x.strip()}

    all_set = {x for x in all_ids if isinstance(x, str) and x.strip()}
    if covered_set != all_set:
        return False, "final_covered_artifact_ids_mismatch"

    # Require the model to have actually seen every artifact slice at least once
    if seen_ids != all_set:
        return False, "final_not_allowed_until_all_slices_seen"

    # Require coverage_map per artifact_id
    cmap = final_obj.get("coverage_map")
    if not isinstance(cmap, dict):
        return False, "final_missing_coverage_map"
    cmap_keys = {k for k in cmap.keys() if isinstance(k, str) and k.strip()}
    if cmap_keys != all_set:
        return False, "final_coverage_map_keys_mismatch"

    return True, "ok"


# ------------------------------- main -------------------------------
async def generate_workspace_document(params: GenerateParams) -> Dict[str, Any]:
    settings = Settings.from_env()

    log.info(
        "gen.begin workspace_id=%s kind_id=%s llm_enabled=%s llm_model=%s artifact_service_url=%s",
        params.workspace_id,
        params.kind_id,
        settings.enable_real_llm,
        settings.llm_model,
        settings.artifact_service_url,
    )

    if not settings.enable_real_llm:
        raise RuntimeError("ENABLE_REAL_LLM is false; this server is prompt-driven and requires a live LLM.")

    # 1) Fetch workspace artifacts
    all_arts = await fetch_workspace_artifacts(params.workspace_id)
    if not all_arts:
        raise RuntimeError("No artifacts found for workspace; cannot generate a guidance document.")

    kind_counts = Counter([a.get("kind") for a in all_arts if a.get("kind")])
    log.info("gen.fetch.done artifact_count=%s kinds=%s", len(all_arts), dict(kind_counts))

    # 2) Fetch guidance kind definition
    kind_def = await fetch_kind_definition(params.kind_id)
    if not kind_def:
        raise RuntimeError(f"Kind not found: {params.kind_id}")

    versions = kind_def.get("schema_versions") or []
    latest_ver = kind_def.get("latest_schema_version")
    latest = next((v for v in versions if v.get("version") == latest_ver), versions[0] if versions else None)
    if latest is None:
        raise RuntimeError(f"No schema_versions available for kind: {params.kind_id}")

    prompt_block = latest.get("prompt") or {}
    base_system_prompt = (prompt_block.get("system") or "").strip()
    strict_json = bool(prompt_block.get("strict_json"))

    if not base_system_prompt:
        raise RuntimeError(f"Artifact kind '{params.kind_id}' does not provide prompt.system; cannot proceed.")
    if not strict_json:
        raise RuntimeError(f"Kind '{params.kind_id}' must declare strict_json=true for this generator.")

    # 3) Dependencies (alias-aware) validation
    depends_on = latest.get("depends_on") or {}
    hard_kinds: List[str] = depends_on.get("hard") or []
    soft_kinds: List[str] = depends_on.get("soft") or []

    hard_eq = await resolve_kind_aliases(hard_kinds)
    soft_eq = await resolve_kind_aliases(soft_kinds)

    present = _present_kinds_set(all_arts)
    missing_hard = _missing_required_by_equivalence(present, hard_eq)
    if missing_hard:
        raise RuntimeError(f"Missing hard dependency artifacts: {missing_hard}")

    selected_deps = shortlist_by_kinds_alias_aware(
        all_arts,
        hard_equivalence=hard_eq,
        soft_equivalence=soft_eq,
    )

    # 4) Run inputs
    run_inputs_art = _pick_best_run_inputs_artifact(all_arts)
    if not run_inputs_art:
        raise RuntimeError("RUN INPUTS missing: no cam.inputs.raina artifact found in workspace.")
    run_inputs_obj = run_inputs_art.get("data") or {}

    # 5) Artifact index
    artifact_index = [_artifact_index_record(a, settings) for a in all_arts]
    all_ids = [x.get("artifact_id") for x in artifact_index if isinstance(x, dict) and x.get("artifact_id")]
    all_set = {x for x in all_ids if isinstance(x, str) and x.strip()}

    dependencies_obj = {
        "workspace_id": params.workspace_id,
        "artifact_count": len(all_arts),
        "artifact_index": artifact_index,
        "dependency_index": {
            "hard_kinds": hard_kinds,
            "soft_kinds": soft_kinds,
            "hard_equivalence": {k: sorted(list(v)) for k, v in (hard_eq or {}).items()},
            "soft_equivalence": {k: sorted(list(v)) for k, v in (soft_eq or {}).items()},
            "selected_dependency_artifact_ids": [a.get("artifact_id") for a in selected_deps],
        },
    }

    # 6) System prompt (protocol + kind prompt)
    system_prompt = _render_kind_prompt(
        _protocol_preamble() + "\n\n" + base_system_prompt,
        run_inputs_obj=run_inputs_obj,
        dependencies_obj=dependencies_obj,
    )

    # 7) Retrieval conversation
    seen_ids: Set[str] = set()
    retrieved_chars_total = 0

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "context": {
                        "workspace": {"id": params.workspace_id},
                        "kind_id": params.kind_id,
                        "run_inputs_artifact_id": run_inputs_art.get("artifact_id"),
                        "artifact_summary": {"total": len(all_arts), "kinds": dict(kind_counts)},
                    },
                    "artifact_index": artifact_index,
                    "instruction": "Start by requesting any deep slices you need. You will also receive server-driven batches.",
                },
                ensure_ascii=False,
            ),
        },
    ]

    final_obj: Dict[str, Any] | None = None

    for turn in range(1, settings.doc_max_turns + 1):
        log.info("retrieval.turn.begin turn=%s seen=%s/%s", turn, len(seen_ids), len(all_set))

        llm_raw = await _llm_chat_strict_json(messages=messages, settings=settings)
        llm_obj = _extract_last_json_object(llm_raw)

        # Always store assistant output for transcript continuity
        messages.append({"role": "assistant", "content": llm_raw})

        # If model attempted final, validate hard
        if isinstance(llm_obj, dict) and isinstance(llm_obj.get("final"), dict):
            candidate = llm_obj["final"]
            ok, reason = _validate_final(final_obj=candidate, all_ids=all_ids, seen_ids=seen_ids)
            if ok:
                final_obj = candidate
                break

            # Force it back into retrieval until constraints satisfied
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "error": reason,
                            "seen_artifact_ids": sorted(list(seen_ids)),
                            "missing_artifact_ids": sorted(list(all_set - seen_ids)),
                            "instruction": "Do NOT return final yet. Request or accept more slices until all artifacts have been seen and coverage_map is complete.",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            continue

        # Parse explicit requests if any
        reqs = llm_obj.get("requests") if isinstance(llm_obj, dict) else None
        explicit_requests: List[Dict[str, Any]] = reqs if isinstance(reqs, list) else []

        # Add server-driven auto paging requests for unseen artifacts
        auto_requests = _auto_page_requests(all_ids=all_ids, already_seen=seen_ids, settings=settings)

        # Combine (explicit first so model can steer depth)
        combined = (explicit_requests or []) + (auto_requests or [])
        if not combined:
            # If model gave neither requests nor final, nudge
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "error": "protocol_violation",
                            "instruction": "Return JSON with either {requests:[...]} or {final:{...}}.",
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            continue

        retrieved, newly_seen, chars_used = _fulfill_requests(
            requests=combined,
            all_arts=all_arts,
            settings=settings,
        )
        retrieved_chars_total += chars_used
        seen_ids |= newly_seen

        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "retrieved": retrieved,
                        "seen_artifact_ids": sorted(list(seen_ids)),
                        "missing_artifact_ids": sorted(list(all_set - seen_ids)),
                        "retrieved_chars_total": retrieved_chars_total,
                        "instruction": "Incorporate these details. If anything is still unclear or truncated, request deeper slices. Otherwise produce final once missing_artifact_ids is empty.",
                    },
                    ensure_ascii=False,
                ),
            }
        )

    if final_obj is None:
        raise RuntimeError(f"LLM did not produce an acceptable final document within DOC_MAX_TURNS={settings.doc_max_turns}.")

    # 8) Final metadata
    md_content = final_obj.get("content")
    doc_name = final_obj.get("name") or (kind_def.get("title") or "Architecture Guidance")
    doc_desc = final_obj.get("description") or "Directive architecture guidance grounded on discovered artifacts."
    filename = final_obj.get("filename") or "architecture-guidance.md"
    mime_from_llm = final_obj.get("mime_type") or FALLBACK_MIME
    tags_from_llm = final_obj.get("tags") or ["architecture", "guidance"]

    # 9) Enforce narratives_spec max length if present
    narratives = latest.get("narratives_spec") or {}
    max_chars = narratives.get("max_length_chars")
    if isinstance(max_chars, int) and max_chars > 0 and isinstance(md_content, str) and len(md_content) > max_chars:
        md_content = md_content[:max_chars]

    # 10) Write file
    out_dir = ensure_output_dir()
    path = out_dir / filename
    path.write_text(md_content, encoding="utf-8")
    sha = sha256_of_file(path)
    size = path.stat().st_size
    log.info("gen.write.ok path=%s size_bytes=%s", path, size)

    # 11) Upload
    storage_uri = f"file://{path}"
    download_url: str | None = None
    download_expires_at: str | None = None

    if settings.s3_enabled and settings.s3_bucket:
        key = f"{(settings.s3_prefix or 'workspace-docs').strip('/')}/{params.workspace_id}/{filename}"
        ok = upload_file_to_s3(
            settings=settings,
            local_path=path,
            bucket=settings.s3_bucket,
            key=key,
            content_type=mime_from_llm,
        )
        if ok:
            storage_uri = f"s3://{settings.s3_bucket}/{key}"
            if settings.s3_force_signed or not settings.s3_public_base_url:
                dl = generate_presigned_get_url(settings, settings.s3_bucket, key, settings.s3_presign_ttl_seconds)
                if dl:
                    download_url = dl
            else:
                dl = build_public_download_url(settings, settings.s3_bucket, key)
                if dl:
                    download_url = dl

    # 12) Build CAM artifact payload
    data_payload: Dict[str, Any] = dict(final_obj)
    data_payload.setdefault("name", doc_name)
    data_payload.setdefault("description", doc_desc)
    data_payload.setdefault("filename", filename)
    data_payload.setdefault("mime_type", mime_from_llm)
    data_payload.setdefault("tags", tags_from_llm)

    data_payload["storage_uri"] = storage_uri
    data_payload["download_url"] = download_url
    data_payload["download_expires_at"] = data_payload.get("download_expires_at") or download_expires_at
    data_payload["size_bytes"] = data_payload.get("size_bytes") or size
    data_payload["encoding"] = data_payload.get("encoding") or "utf-8"
    data_payload["checksum"] = data_payload.get("checksum") or {"sha256": sha}

    data_payload["workspace_id"] = params.workspace_id
    data_payload["source"] = {
        "path": str(path),
        "storage_uri": storage_uri,
        "download_url": download_url,
        "mime_type": mime_from_llm,
        "encoding": "utf-8",
        "size_bytes": size,
        "sha256": sha,
        "run_inputs_artifact_id": run_inputs_art.get("artifact_id"),
        "dependency_selected_count": len(selected_deps),
        "dependency_total_artifacts": len(all_arts),
        "retrieval": {
            "seen_artifacts": len(seen_ids),
            "total_artifacts": len(all_set),
            "retrieved_chars_total": retrieved_chars_total,
        },
    }

    artifact: Dict[str, Any] = {
        "kind_id": params.kind_id,
        "name": f"{doc_name} (Workspace {params.workspace_id})",
        "data": data_payload,
        "preview": {"text_excerpt": (md_content or "")[:260]},
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

    log.info("gen.success workspace_id=%s driver_kind=%s uploaded=%s", params.workspace_id, params.kind_id, bool(download_url))
    return {"artifacts": [artifact]}