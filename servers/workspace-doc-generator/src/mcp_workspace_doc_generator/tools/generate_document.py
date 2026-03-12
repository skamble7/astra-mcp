# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/tools/generate_document.py
from __future__ import annotations

import datetime as dt
import json
import logging
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


def _recover_final_from_truncated_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Recovery path when the LLM's JSON response is truncated by max_tokens.
    Extracts the 'content' field value character-by-character, handling JSON
    escape sequences, even if the closing braces were never generated.
    Also extracts name/description/filename/tags from the pre-content preamble.
    """
    import re

    content_match = re.search(r'"content"\s*:\s*"', text)
    if not content_match:
        return None

    # Walk the JSON string byte-by-byte from the opening quote
    start = content_match.end()
    chars: List[str] = []
    i = start
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            n = text[i + 1]
            chars.append(
                {"\"": '"', "n": "\n", "t": "\t", "r": "\r",
                 "\\": "\\", "/": "/", "b": "\b", "f": "\f"}.get(n, n)
            )
            i += 2
        elif c == '"':
            break  # clean end of JSON string
        else:
            chars.append(c)
            i += 1

    content = "".join(chars).strip()
    if not content:
        return None

    # Extract small metadata fields from the preamble (before "content":)
    preamble = text[: content_match.start()]

    def _str_field(field: str) -> str:
        m = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:[^"\\]|\\.)*)"', preamble)
        if not m:
            return ""
        raw = m.group(1)
        return (raw.replace('\\"', '"').replace("\\n", "\n")
                .replace("\\t", "\t").replace("\\\\", "\\"))

    tags: List[str] = []
    tags_m = re.search(r'"tags"\s*:\s*(\[(?:[^\[\]]|\[.*?\])*?\])', preamble, re.DOTALL)
    if tags_m:
        try:
            tags = json.loads(tags_m.group(1))
        except Exception:
            pass

    log.info(
        "llm.recovery.truncated_json content_chars=%s name=%r "
        "— document was cut off by max_tokens; increase max_tokens in ConfigForge to avoid truncation",
        len(content), _str_field("name"),
    )
    return {
        "name": _str_field("name"),
        "description": _str_field("description"),
        "filename": _str_field("filename"),
        "mime_type": _str_field("mime_type") or "text/markdown",
        "tags": tags,
        "content": content,
    }


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
        "DIAGRAM RULES:\n"
        "- Each artifact slice may include a `diagrams` field containing pre-generated Mermaid diagrams.\n"
        "- Each diagram has an `instructions` field containing valid Mermaid syntax.\n"
        "- You MUST embed every diagram from every artifact into the final document as a fenced Mermaid code block:\n"
        "  ```mermaid\n"
        "  <instructions content here>\n"
        "  ```\n"
        "- Place each diagram immediately after the section that discusses the artifact it came from.\n"
        "- Do NOT summarize or omit diagrams — embed the full diagram code verbatim.\n\n"
        "CONTENT DEPTH RULES:\n"
        "- Write FULL PARAGRAPHS for every section — not bullet lists, not one-line summaries.\n"
        "- Each section must be at least 3-5 paragraphs of detailed prose covering the artifacts' specifics.\n"
        "- Include exact field names, types, constraints, event payloads, API request/response shapes, and entity relationships — do NOT compress or abstract them.\n"
        "- When describing a service: cover its responsibilities, every API endpoint (path, method, headers, request fields, response fields, error codes), every event it produces and consumes (with all payload fields), its data model (every entity with all fields), and its dependencies.\n"
        "- When describing data models: write out every field with type, constraints, and business meaning in full sentences.\n"
        "- When describing events: write out event name, producer, consumers, all payload fields and their types, and delivery guarantees.\n"
        "- If something is missing from the artifacts, write an explicit open-question paragraph naming the artifact(s) and what is unclear.\n"
        "- The document `content` field MUST be at least 6,000 words. Short responses are not acceptable.\n"
    )


_polyllm_client: list = [None]
_polyllm_lock: "asyncio.Lock | None" = None


def _get_polyllm_lock() -> "asyncio.Lock":
    import asyncio
    global _polyllm_lock
    if _polyllm_lock is None:
        _polyllm_lock = asyncio.Lock()
    return _polyllm_lock


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences (```json / ```) that Bedrock models add despite instructions."""
    import re
    text = text.strip()
    # Handle ```json\n...\n``` and ```\n...\n```
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


async def _llm_chat_strict_json(*, messages: List[Dict[str, str]], settings: Settings) -> str:
    import asyncio

    lock = _get_polyllm_lock()
    async with lock:
        if _polyllm_client[0] is None:
            from polyllm import RemoteConfigLoader
            _polyllm_client[0] = await RemoteConfigLoader().load(settings.config_ref)

    client = _polyllm_client[0]
    backoff = settings.llm_retry_backoff_initial
    last_err: Exception | None = None

    for attempt in range(1, 1 + settings.llm_max_retries):
        try:
            log.info("llm.call.begin msg_count=%s", len(messages))
            result = await client.chat(messages)
            out = _strip_code_fences(result.text or "")
            log.info("llm.call.success output_len=%s", len(out))
            return out
        except Exception as e:
            last_err = e
            log.warning("llm.call.error attempt=%s detail=%s", attempt, e)

        await asyncio.sleep(backoff)
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


def _inject_artifact_diagrams(md_content: str, all_arts: List[Dict[str, Any]]) -> str:
    """
    Collect Mermaid diagrams from artifact diagrams[].instructions and append them
    to the document under an ## Artifact Diagrams section if not already present.
    Diagrams the LLM already embedded verbatim are de-duplicated.
    """
    sections: List[str] = []
    for art in all_arts:
        diagrams = art.get("diagrams") or []
        if not diagrams:
            continue
        art_name = art.get("name") or art.get("kind") or art.get("artifact_id", "unknown")
        for d in diagrams:
            instructions = (d.get("instructions") or "").strip()
            if not instructions:
                continue
            # Skip if this diagram is already embedded in the document
            if instructions in md_content:
                continue
            view = d.get("view") or "diagram"
            sections.append(f"### {art_name} ({view})\n\n```mermaid\n{instructions}\n```")

    if not sections:
        return md_content

    diagrams_block = "## Artifact Diagrams\n\n" + "\n\n".join(sections)

    # Append before Appendices if present, otherwise at the end
    appendix_marker = "\n## Appendices"
    if appendix_marker in md_content:
        return md_content.replace(appendix_marker, f"\n\n{diagrams_block}{appendix_marker}", 1)
    return md_content + f"\n\n{diagrams_block}"


# ------------------------------- main -------------------------------
async def generate_workspace_document(params: GenerateParams) -> Dict[str, Any]:
    settings = Settings.from_env()

    log.info(
        "gen.begin workspace_id=%s kind_id=%s llm_enabled=%s config_ref=%s artifact_service_url=%s",
        params.workspace_id,
        params.kind_id,
        settings.enable_real_llm,
        settings.config_ref,
        settings.artifact_service_url,
    )

    if not settings.enable_real_llm:
        raise RuntimeError("LLM_CONFIG_REF is not set; this server requires a live LLM via ConfigForge.")

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
        "_retrieval_note": (
            "INDEX ONLY — this section lists artifact IDs and kinds but does NOT contain artifact data or diagrams. "
            "You MUST use the retrieval protocol (request slices via {\"requests\":[...]}) to obtain full artifact data "
            "including diagrams before producing the final document. Do NOT generate the final document until you have "
            "retrieved and reviewed slices for every artifact_id listed below."
        ),
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
    all_retrieved_artifacts: List[Dict[str, Any]] = []  # accumulated across all turns for final call

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

        # Once all artifacts are seen, make the final generation call using a compact
        # 2-message context instead of the accumulated conversation history.
        # This avoids sending 4-6 large messages (with redundant back-and-forth) to
        # Bedrock's invoke_model endpoint, which causes read timeouts on large contexts.
        if seen_ids == all_set and all_retrieved_artifacts:
            log.info("retrieval.all_seen turn=%s — using compact context for final generation", turn)
            final_messages = [
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
                            "all_retrieved_artifacts": all_retrieved_artifacts,
                            "artifact_ids": sorted(list(seen_ids)),
                            "instruction": (
                                "All artifacts have been retrieved. Produce the final document now. "
                                "Return {\"final\": {...}} with complete coverage of every artifact listed in artifact_ids. "
                                "Write FULL PARAGRAPHS — not bullet points or one-line summaries. "
                                "The content field must be at least 6,000 words."
                            ),
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            llm_raw = await _llm_chat_strict_json(messages=final_messages, settings=settings)
            try:
                llm_obj = _extract_last_json_object(llm_raw)
            except ValueError:
                # JSON is truncated by max_tokens — try to recover content from the partial output
                recovered = _recover_final_from_truncated_json(llm_raw)
                if recovered and recovered.get("content"):
                    llm_obj = {"final": recovered}
                else:
                    log.error("llm.parse.failed turn=%s raw_prefix=%r", turn, llm_raw[:500])
                    raise

            if isinstance(llm_obj, dict) and isinstance(llm_obj.get("final"), dict):
                candidate = llm_obj["final"]
                # Server-side: patch coverage fields so LLM ID-mismatch doesn't discard a
                # valid document. We already verified seen_ids == all_set above.
                if not isinstance(candidate.get("covered_artifact_ids"), list) or \
                        set(candidate.get("covered_artifact_ids", [])) != set(all_ids):
                    log.info("retrieval.compact.patching_coverage all_ids=%s", len(all_ids))
                    candidate["covered_artifact_ids"] = list(all_ids)
                if not isinstance(candidate.get("coverage_map"), dict):
                    candidate["coverage_map"] = {
                        aid: {"kind": next((a.get("kind", "") for a in all_arts if a.get("artifact_id") == aid), ""),
                              "used_in_sections": ["document"], "key_points": []}
                        for aid in all_ids
                    }
                ok, reason = _validate_final(final_obj=candidate, all_ids=all_ids, seen_ids=seen_ids)
                if ok:
                    final_obj = candidate
                    break
                # Only fall through if content itself is missing/empty
                log.warning("retrieval.final.invalid reason=%s (content issue — NOT retrying with full history)", reason)
                # Don't fall through to the full-history call; break with no final_obj
                break

        llm_raw = await _llm_chat_strict_json(messages=messages, settings=settings)
        try:
            llm_obj = _extract_last_json_object(llm_raw)
        except ValueError:
            log.error("llm.parse.failed turn=%s raw_prefix=%r", turn, llm_raw[:500])
            raise

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
        all_retrieved_artifacts.extend(retrieved)  # accumulate for compact final call

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
    if isinstance(md_content, str):
        word_count = len(md_content.split())
        log.info("gen.content.stats chars=%s words=%s", len(md_content), word_count)
        if word_count < 3000:
            log.warning(
                "gen.content.too_short words=%s — LLM produced compressed output. "
                "Consider increasing max_tokens in the ConfigForge LLM profile (e.g. dev.llm.bedrock.explicit-creds).",
                word_count,
            )
    doc_name = final_obj.get("name") or (kind_def.get("title") or "Architecture Guidance")
    doc_desc = final_obj.get("description") or "Directive architecture guidance grounded on discovered artifacts."
    filename = final_obj.get("filename") or "architecture-guidance.md"
    mime_from_llm = final_obj.get("mime_type") or FALLBACK_MIME
    tags_from_llm = final_obj.get("tags") or ["architecture", "guidance"]

    # 8b) Enforce narratives_spec max length on LLM prose BEFORE diagram injection.
    # Applying the limit after injection causes diagrams to eat the prose budget.
    narratives = latest.get("narratives_spec") or {}
    max_chars = narratives.get("max_length_chars")
    if isinstance(max_chars, int) and max_chars > 0 and isinstance(md_content, str) and len(md_content) > max_chars:
        log.warning(
            "gen.prose.truncated limit=%s actual=%s (truncation applied before diagram injection)",
            max_chars, len(md_content),
        )
        md_content = md_content[:max_chars]

    # 8c) Programmatically inject artifact diagrams (appended after prose, not subject to char limit)
    if isinstance(md_content, str):
        md_content = _inject_artifact_diagrams(md_content, all_arts)

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