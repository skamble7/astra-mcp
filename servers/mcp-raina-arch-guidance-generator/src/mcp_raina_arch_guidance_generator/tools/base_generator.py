# tools/base_generator.py
#
# ArchGuidanceGenerator — the reusable base for all architecture-style guidance generators.
#
# To add a new architecture style (e.g., data engineering):
#   1. Create arch_styles/data_engineering/config.yaml  (output kind, depends_on, tags, etc.)
#   2. Create arch_styles/data_engineering/prompts.yaml (protocol_preamble + system prompt)
#   3. Instantiate ArchGuidanceGenerator with the new style_dir in your tool function.
#
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from ..settings import Settings
from ..utils.artifacts_fetch import (
    fetch_workspace_artifacts,
    resolve_kind_aliases,
    shortlist_by_kinds_alias_aware,
)
from ..utils.checksums import sha256_of_file
from ..utils.io_paths import ensure_output_dir
from ..utils.storage import (
    build_public_download_url,
    generate_presigned_get_url,
    upload_file_to_s3,
)

log = logging.getLogger("mcp.raina.arch.guidance.generator")

FALLBACK_MIME = "text/markdown"

# ---------------------------------------------------------------------------
# Module-level polyllm singleton (shared across all ArchGuidanceGenerator instances)
# ---------------------------------------------------------------------------
_polyllm_client: list = [None]
_polyllm_lock: "asyncio.Lock | None" = None


def _get_polyllm_lock() -> "asyncio.Lock":
    global _polyllm_lock
    if _polyllm_lock is None:
        _polyllm_lock = asyncio.Lock()
    return _polyllm_lock


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences that Bedrock models add despite instructions."""
    import re
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


async def _llm_chat_strict_json(*, messages: List[Dict[str, str]], settings: Settings) -> str:
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

    raise last_err if last_err else RuntimeError("LLM call failed")


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
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
    Extracts the 'content' field value character-by-character plus metadata preamble.
    """
    import re

    content_match = re.search(r'"content"\s*:\s*"', text)
    if not content_match:
        return None

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
            break
        else:
            chars.append(c)
            i += 1

    content = "".join(chars).strip()
    if not content:
        return None

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

    log.warning(
        "llm.truncated_by_max_tokens content_chars=%s name=%r "
        "— LLM hit max_tokens mid-generation; document is INCOMPLETE. "
        "Increase max_tokens in your ConfigForge LLM profile to fix this.",
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


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------
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
    for part in path.split("."):
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
    """Server-driven paging: force the model to see every artifact at least once."""
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


def _validate_final(
    *,
    final_obj: Dict[str, Any],
    all_ids: List[str],
    seen_ids: Set[str],
) -> Tuple[bool, str]:
    md = final_obj.get("content")
    if not isinstance(md, str) or not md.strip():
        return False, "final_missing_content"

    covered = final_obj.get("covered_artifact_ids")
    if not isinstance(covered, list):
        return False, "final_missing_covered_artifact_ids"
    covered_set = {x for x in covered if isinstance(x, str) and x.strip()}

    all_set = {x for x in all_ids if isinstance(x, str) and x.strip()}
    if covered_set != all_set:
        return False, "final_covered_artifact_ids_mismatch"

    if seen_ids != all_set:
        return False, "final_not_allowed_until_all_slices_seen"

    cmap = final_obj.get("coverage_map")
    if not isinstance(cmap, dict):
        return False, "final_missing_coverage_map"
    cmap_keys = {k for k in cmap.keys() if isinstance(k, str) and k.strip()}
    if cmap_keys != all_set:
        return False, "final_coverage_map_keys_mismatch"

    return True, "ok"


def _collect_diagrams_from_artifact(art: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return the diagram list for a single artifact, checking multiple locations:
    1. art["diagrams"]                         — top-level diagrams field (raw API response)
    2. art["data"]["diagrams"]                 — diagrams nested inside data
    3. art["slices"]["diagrams"]               — diagrams from a retrieved slice
    4. art["slices"]["data"]["diagrams"]       — diagrams nested inside a retrieved data slice
    """
    candidates: List[Any] = []

    def _extend(v: Any) -> None:
        if isinstance(v, list):
            candidates.extend(v)

    _extend(art.get("diagrams"))
    if isinstance(art.get("data"), dict):
        _extend(art["data"].get("diagrams"))
    if isinstance(art.get("slices"), dict):
        _extend(art["slices"].get("diagrams"))
        if isinstance(art["slices"].get("data"), dict):
            _extend(art["slices"]["data"].get("diagrams"))

    return [d for d in candidates if isinstance(d, dict)]


def _inject_artifact_diagrams(
    md_content: str,
    all_arts: List[Dict[str, Any]],
    retrieved_slices: List[Dict[str, Any]] | None = None,
) -> str:
    """
    Collect Mermaid diagrams from artifact diagrams[].instructions and append them
    to the document. Diagrams the LLM already embedded are de-duplicated.

    Checks both the raw artifact objects (all_arts) AND the retrieved slices from
    the retrieval loop (retrieved_slices), so diagrams are captured regardless of
    whether they appear on the top-level artifact or only in the fetched slice data.
    """
    # Build a lookup of artifact_id -> art_name from raw artifacts
    id_to_name: Dict[str, str] = {}
    for art in all_arts:
        aid = art.get("artifact_id") or ""
        if aid:
            id_to_name[aid] = (
                art.get("name") or art.get("kind") or aid
            )

    seen_instructions: set = set()
    sections: List[str] = []

    def _process_diagram_list(diagrams: List[Dict[str, Any]], art_name: str) -> None:
        for d in diagrams:
            instructions = (d.get("instructions") or "").strip()
            if not instructions or instructions in seen_instructions:
                continue
            if instructions in md_content:
                seen_instructions.add(instructions)
                continue
            seen_instructions.add(instructions)
            view = d.get("view") or "diagram"
            sections.append(f"### {art_name} ({view})\n\n```mermaid\n{instructions}\n```")

    # 1. Check raw artifact objects (top-level API response)
    for art in all_arts:
        diagrams = _collect_diagrams_from_artifact(art)
        if diagrams:
            art_name = art.get("name") or art.get("kind") or art.get("artifact_id", "unknown")
            _process_diagram_list(diagrams, art_name)

    # 2. Check retrieved slices from the retrieval loop (fallback / additional source)
    for sliced in (retrieved_slices or []):
        aid = sliced.get("artifact_id") or ""
        art_name = sliced.get("name") or id_to_name.get(aid) or sliced.get("kind") or aid or "unknown"
        diagrams = _collect_diagrams_from_artifact(sliced)
        if diagrams:
            _process_diagram_list(diagrams, art_name)

    if not sections:
        log.info("diagram.inject.none — no diagrams found in artifacts or slices")
        return md_content

    log.info("diagram.inject.count=%s", len(sections))
    diagrams_block = "## Artifact Diagrams\n\n" + "\n\n".join(sections)

    appendix_marker = "\n## Appendices"
    if appendix_marker in md_content:
        return md_content.replace(appendix_marker, f"\n\n{diagrams_block}{appendix_marker}", 1)
    return md_content + f"\n\n{diagrams_block}"


def _pick_run_inputs_artifact(
    all_arts: List[Dict[str, Any]],
    run_inputs_kind: str,
) -> Optional[Dict[str, Any]]:
    candidates = [a for a in all_arts if a.get("kind") == run_inputs_kind]
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


def _present_kinds_set(all_arts: List[Dict[str, Any]]) -> Set[str]:
    return {k for k in (a.get("kind") for a in all_arts) if isinstance(k, str) and k.strip()}


def _missing_required_by_equivalence(
    present_kinds: Set[str],
    required_equivalence: Dict[str, Set[str]],
) -> List[str]:
    missing: List[str] = []
    for canonical, eqset in (required_equivalence or {}).items():
        if not (present_kinds & set(eqset)):
            missing.append(canonical)
    return missing


def _render_prompt(system_prompt: str, *, run_inputs_obj: Any, dependencies_obj: Any) -> str:
    run_inputs_text = json.dumps(run_inputs_obj, ensure_ascii=False, indent=2)
    deps_text = json.dumps(dependencies_obj, ensure_ascii=False, indent=2)
    return (
        system_prompt
        .replace("{{RUN_INPUTS}}", run_inputs_text)
        .replace("{{DEPENDENCIES}}", deps_text)
    )


# ---------------------------------------------------------------------------
# Main generator class
# ---------------------------------------------------------------------------
class ArchGuidanceGenerator:
    """
    Reusable architecture guidance document generator.

    Loads style-specific configuration (artifact kind dependencies, output metadata)
    and prompts (LLM system prompt + retrieval protocol) from YAML files in `style_dir`.

    To support a new architecture style, create a new style directory with:
      - config.yaml   (output_kind, output_filename, depends_on, tags, run_inputs_kind, etc.)
      - prompts.yaml  (protocol_preamble, system)

    Then instantiate this class with the new style_dir.
    """

    def __init__(self, style_dir: Path, settings: Settings) -> None:
        self.settings = settings

        cfg_path = style_dir / "config.yaml"
        prompts_path = style_dir / "prompts.yaml"

        if not cfg_path.exists():
            raise FileNotFoundError(f"arch style config not found: {cfg_path}")
        if not prompts_path.exists():
            raise FileNotFoundError(f"arch style prompts not found: {prompts_path}")

        with cfg_path.open("r", encoding="utf-8") as f:
            self._cfg: Dict[str, Any] = yaml.safe_load(f) or {}

        with prompts_path.open("r", encoding="utf-8") as f:
            self._prompts: Dict[str, Any] = yaml.safe_load(f) or {}

        # Validate required config fields
        for field in ("output_kind", "output_filename", "output_mime_type"):
            if not self._cfg.get(field):
                raise ValueError(f"arch style config missing required field: {field}")

        self._protocol_preamble: str = (self._prompts.get("protocol_preamble") or "").strip()
        self._system_prompt_template: str = (self._prompts.get("system") or "").strip()

        if not self._system_prompt_template:
            raise ValueError("arch style prompts.yaml must have a non-empty 'system' field")

        # Apply per-arch-style auto_page_paths override from config.yaml (if present)
        cfg_paths = self._cfg.get("auto_page_paths")
        if cfg_paths and isinstance(cfg_paths, list):
            self.settings = Settings(
                **{
                    **self.settings.__dict__,
                    "doc_auto_page_paths": tuple(cfg_paths),
                }
            )
            log.info("arch_style.auto_page_paths overridden paths=%s", cfg_paths)

        log.info(
            "arch_style.loaded output_kind=%s output_filename=%s",
            self._cfg["output_kind"],
            self._cfg["output_filename"],
        )

    async def generate(self, workspace_id: str) -> Dict[str, Any]:
        """
        Orchestrate the full document generation flow:
        1. Fetch workspace artifacts
        2. Validate hard dependencies
        3. Run multi-turn agentic retrieval loop
        4. Inject Mermaid diagrams
        5. Upload to S3
        6. Return CAM artifact payload
        """
        settings = self.settings

        log.info(
            "gen.begin workspace_id=%s output_kind=%s llm_enabled=%s config_ref=%s",
            workspace_id,
            self._cfg["output_kind"],
            settings.enable_real_llm,
            settings.config_ref,
        )

        if not settings.enable_real_llm:
            raise RuntimeError(
                "LLM_CONFIG_REF is not set; this server requires a live LLM via ConfigForge."
            )

        # 1) Fetch workspace artifacts
        all_arts = await fetch_workspace_artifacts(workspace_id, settings=settings)
        if not all_arts:
            raise RuntimeError("No artifacts found for workspace; cannot generate a guidance document.")

        kind_counts = Counter([a.get("kind") for a in all_arts if a.get("kind")])
        log.info("gen.fetch.done artifact_count=%s kinds=%s", len(all_arts), dict(kind_counts))

        # 2) Dependency validation (alias-aware)
        depends_on = self._cfg.get("depends_on") or {}
        hard_kinds: List[str] = depends_on.get("hard") or []
        soft_kinds: List[str] = depends_on.get("soft") or []

        hard_eq = await resolve_kind_aliases(hard_kinds, settings=settings)
        soft_eq = await resolve_kind_aliases(soft_kinds, settings=settings)

        present = _present_kinds_set(all_arts)
        missing_hard = _missing_required_by_equivalence(present, hard_eq)
        if missing_hard:
            raise RuntimeError(f"Missing hard dependency artifacts: {missing_hard}")

        selected_deps = shortlist_by_kinds_alias_aware(
            all_arts, hard_equivalence=hard_eq, soft_equivalence=soft_eq
        )

        # 3) Run inputs artifact
        run_inputs_kind = self._cfg.get("run_inputs_kind") or hard_kinds[0] if hard_kinds else ""
        run_inputs_art = _pick_run_inputs_artifact(all_arts, run_inputs_kind)
        if not run_inputs_art:
            raise RuntimeError(
                f"RUN INPUTS missing: no '{run_inputs_kind}' artifact found in workspace."
            )
        run_inputs_obj = run_inputs_art.get("data") or {}

        # 4) Build artifact index
        artifact_index = [_artifact_index_record(a, settings) for a in all_arts]
        all_ids = [
            x.get("artifact_id")
            for x in artifact_index
            if isinstance(x, dict) and x.get("artifact_id")
        ]
        all_set = {x for x in all_ids if isinstance(x, str) and x.strip()}

        dependencies_obj = {
            "_retrieval_note": (
                "INDEX ONLY — this section lists artifact IDs and kinds but does NOT contain artifact "
                "data or diagrams. You MUST use the retrieval protocol (request slices via "
                '{"requests":[...]}) to obtain full artifact data including diagrams before producing '
                "the final document. Do NOT generate the final document until you have retrieved and "
                "reviewed slices for every artifact_id listed below."
            ),
            "workspace_id": workspace_id,
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

        # 5) Build system prompt
        full_template = (
            (self._protocol_preamble + "\n\n" + self._system_prompt_template)
            if self._protocol_preamble
            else self._system_prompt_template
        )
        system_prompt = _render_prompt(
            full_template,
            run_inputs_obj=run_inputs_obj,
            dependencies_obj=dependencies_obj,
        )

        # 6) Multi-turn retrieval loop
        final_obj, all_retrieved_artifacts = await self._retrieval_loop(
            workspace_id=workspace_id,
            all_arts=all_arts,
            kind_counts=kind_counts,
            artifact_index=artifact_index,
            all_ids=all_ids,
            all_set=all_set,
            system_prompt=system_prompt,
            run_inputs_art=run_inputs_art,
            selected_deps=selected_deps,
        )

        # 7) Post-process: content length, diagram injection
        md_content: str = final_obj.get("content") or ""

        if md_content:
            word_count = len(md_content.split())
            log.info("gen.content.stats chars=%s words=%s", len(md_content), word_count)
            if word_count < 3000:
                log.warning(
                    "gen.content.too_short words=%s — consider increasing max_tokens in ConfigForge",
                    word_count,
                )

        # Enforce max_prose_chars before diagram injection
        max_prose_chars = self._cfg.get("max_prose_chars")
        if isinstance(max_prose_chars, int) and max_prose_chars > 0 and len(md_content) > max_prose_chars:
            log.warning(
                "gen.prose.truncated limit=%s actual=%s",
                max_prose_chars, len(md_content),
            )
            md_content = md_content[:max_prose_chars]

        # Inject diagrams (not subject to prose char limit).
        # Pass both the raw artifacts AND the retrieved slices so diagrams are
        # captured regardless of where they live in the artifact structure.
        md_content = _inject_artifact_diagrams(
            md_content, all_arts, retrieved_slices=all_retrieved_artifacts
        )

        # 8) Write file
        doc_name = final_obj.get("name") or self._cfg.get("doc_name") or "Architecture Guidance"
        doc_desc = final_obj.get("description") or self._cfg.get("doc_description") or ""
        filename = final_obj.get("filename") or self._cfg["output_filename"]
        mime_type = final_obj.get("mime_type") or self._cfg["output_mime_type"]
        tags = final_obj.get("tags") or self._cfg.get("tags") or ["architecture", "guidance"]

        out_dir = ensure_output_dir()
        path = out_dir / filename
        path.write_text(md_content, encoding="utf-8")
        sha = sha256_of_file(path)
        size = path.stat().st_size
        # This file is written BEFORE any S3/Garage upload.
        # If S3 is unavailable or disabled, this local copy is the final artifact.
        log.info(
            "gen.write.ok path=%s size_bytes=%s sections_chars=%s "
            "— local file written; S3 upload follows if configured",
            path, size, len(md_content),
        )

        # 9) Upload to S3
        storage_uri = f"file://{path}"
        download_url: str | None = None
        download_expires_at: str | None = None

        if settings.s3_enabled and settings.s3_bucket:
            key = f"{(settings.s3_prefix or 'arch-guidance-docs').strip('/')}/{workspace_id}/{filename}"
            ok = upload_file_to_s3(
                settings=settings,
                local_path=path,
                bucket=settings.s3_bucket,
                key=key,
                content_type=mime_type,
            )
            if ok:
                storage_uri = f"s3://{settings.s3_bucket}/{key}"
                if settings.s3_force_signed or not settings.s3_public_base_url:
                    dl = generate_presigned_get_url(
                        settings, settings.s3_bucket, key, settings.s3_presign_ttl_seconds
                    )
                    if dl:
                        download_url = dl
                else:
                    dl = build_public_download_url(settings, settings.s3_bucket, key)
                    if dl:
                        download_url = dl

        # 10) Build related_assets from config
        related_assets = [
            dict(ra)
            for ra in (self._cfg.get("related_assets") or [])
            if isinstance(ra, dict)
        ]

        # 11) Assemble CAM artifact payload
        data_payload: Dict[str, Any] = dict(final_obj)
        data_payload.setdefault("name", doc_name)
        data_payload.setdefault("description", doc_desc)
        data_payload.setdefault("filename", filename)
        data_payload.setdefault("mime_type", mime_type)
        data_payload.setdefault("tags", tags)
        data_payload.setdefault("related_assets", related_assets)

        data_payload["content"] = md_content
        data_payload["storage_uri"] = storage_uri
        data_payload["download_url"] = download_url
        data_payload["download_expires_at"] = data_payload.get("download_expires_at") or download_expires_at
        data_payload["size_bytes"] = data_payload.get("size_bytes") or size
        data_payload["encoding"] = data_payload.get("encoding") or "utf-8"
        data_payload["checksum"] = data_payload.get("checksum") or {"sha256": sha}
        data_payload["workspace_id"] = workspace_id
        data_payload["source"] = {
            "path": str(path),
            "storage_uri": storage_uri,
            "download_url": download_url,
            "mime_type": mime_type,
            "encoding": "utf-8",
            "size_bytes": size,
            "sha256": sha,
            "run_inputs_artifact_id": run_inputs_art.get("artifact_id"),
            "dependency_selected_count": len(selected_deps),
            "dependency_total_artifacts": len(all_arts),
        }

        artifact: Dict[str, Any] = {
            "kind_id": self._cfg["output_kind"],
            "name": f"{doc_name} (Workspace {workspace_id})",
            "data": data_payload,
            "preview": {"text_excerpt": md_content[:260]},
            "mime_type": mime_type,
            "encoding": "utf-8",
            "filename": filename,
            "path": str(path),
            "storage_uri": storage_uri,
            "download_url": download_url,
            "checksum": {"sha256": sha},
            "tags": tags,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }

        log.info(
            "gen.success workspace_id=%s output_kind=%s uploaded=%s",
            workspace_id, self._cfg["output_kind"], bool(download_url),
        )
        return {"artifacts": [artifact]}

    async def _retrieval_loop(
        self,
        *,
        workspace_id: str,
        all_arts: List[Dict[str, Any]],
        kind_counts: Counter,
        artifact_index: List[Dict[str, Any]],
        all_ids: List[str],
        all_set: Set[str],
        system_prompt: str,
        run_inputs_art: Dict[str, Any],
        selected_deps: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        settings = self.settings
        seen_ids: Set[str] = set()
        retrieved_chars_total = 0
        all_retrieved_artifacts: List[Dict[str, Any]] = []

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context": {
                            "workspace": {"id": workspace_id},
                            "output_kind": self._cfg["output_kind"],
                            "run_inputs_artifact_id": run_inputs_art.get("artifact_id"),
                            "artifact_summary": {"total": len(all_arts), "kinds": dict(kind_counts)},
                        },
                        "artifact_index": artifact_index,
                        "instruction": (
                            "Start by requesting any deep slices you need. "
                            "You will also receive server-driven batches."
                        ),
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        final_obj: Dict[str, Any] | None = None

        for turn in range(1, settings.doc_max_turns + 1):
            log.info("retrieval.turn.begin turn=%s seen=%s/%s", turn, len(seen_ids), len(all_set))

            # Once all artifacts are seen, switch to compact 2-message context to avoid
            # Bedrock timeouts from accumulated large conversation history.
            if seen_ids == all_set and all_retrieved_artifacts:
                log.info("retrieval.all_seen turn=%s — using compact context for final", turn)
                final_messages = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "context": {
                                    "workspace": {"id": workspace_id},
                                    "output_kind": self._cfg["output_kind"],
                                    "run_inputs_artifact_id": run_inputs_art.get("artifact_id"),
                                    "artifact_summary": {"total": len(all_arts), "kinds": dict(kind_counts)},
                                },
                                "all_retrieved_artifacts": all_retrieved_artifacts,
                                "artifact_ids": sorted(list(seen_ids)),
                                "instruction": (
                                    "All artifacts have been retrieved. Produce the final document now. "
                                    'Return {"final": {...}} with complete coverage of every artifact '
                                    "listed in artifact_ids. "
                                    "Use Markdown tables for API endpoints, events, services, tech stack, SLOs, and risks. "
                                    "Use bullet lists for alternatives, migration steps, and open questions. "
                                    "Use prose paragraphs for architectural rationale only. "
                                    "ALL 17 required sections must be present — completeness over verbosity."
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
                    log.warning(
                        "llm.json.parse_failed turn=%s output_chars=%s — attempting truncation recovery",
                        turn, len(llm_raw),
                    )
                    recovered = _recover_final_from_truncated_json(llm_raw)
                    if recovered and recovered.get("content"):
                        llm_obj = {"final": recovered}
                    else:
                        log.error("llm.parse.failed turn=%s raw_prefix=%r", turn, llm_raw[:500])
                        raise

                if isinstance(llm_obj, dict) and isinstance(llm_obj.get("final"), dict):
                    candidate = llm_obj["final"]
                    # Patch coverage fields if LLM ID mismatch (we verified seen_ids == all_set)
                    if (
                        not isinstance(candidate.get("covered_artifact_ids"), list)
                        or set(candidate.get("covered_artifact_ids", [])) != set(all_ids)
                    ):
                        log.info("retrieval.compact.patching_coverage all_ids=%s", len(all_ids))
                        candidate["covered_artifact_ids"] = list(all_ids)
                    if not isinstance(candidate.get("coverage_map"), dict):
                        candidate["coverage_map"] = {
                            aid: {
                                "kind": next(
                                    (a.get("kind", "") for a in all_arts if a.get("artifact_id") == aid),
                                    "",
                                ),
                                "used_in_sections": ["document"],
                                "key_points": [],
                            }
                            for aid in all_ids
                        }
                    ok, reason = _validate_final(
                        final_obj=candidate, all_ids=all_ids, seen_ids=seen_ids
                    )
                    if ok:
                        final_obj = candidate
                        break
                    log.warning(
                        "retrieval.final.invalid reason=%s (content issue — not retrying)", reason
                    )
                    break  # content missing; don't fall through

            llm_raw = await _llm_chat_strict_json(messages=messages, settings=settings)
            try:
                llm_obj = _extract_last_json_object(llm_raw)
            except ValueError:
                log.error("llm.parse.failed turn=%s raw_prefix=%r", turn, llm_raw[:500])
                raise

            messages.append({"role": "assistant", "content": llm_raw})

            # Model attempted final — validate
            if isinstance(llm_obj, dict) and isinstance(llm_obj.get("final"), dict):
                candidate = llm_obj["final"]
                ok, reason = _validate_final(
                    final_obj=candidate, all_ids=all_ids, seen_ids=seen_ids
                )
                if ok:
                    final_obj = candidate
                    break

                # Force back into retrieval
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "error": reason,
                                "seen_artifact_ids": sorted(list(seen_ids)),
                                "missing_artifact_ids": sorted(list(all_set - seen_ids)),
                                "instruction": (
                                    "Do NOT return final yet. Request or accept more slices "
                                    "until all artifacts have been seen and coverage_map is complete."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

            # Parse explicit requests
            reqs = llm_obj.get("requests") if isinstance(llm_obj, dict) else None
            explicit_requests: List[Dict[str, Any]] = reqs if isinstance(reqs, list) else []

            # Auto-page unseen artifacts
            auto_requests = _auto_page_requests(
                all_ids=all_ids, already_seen=seen_ids, settings=settings
            )

            combined = (explicit_requests or []) + (auto_requests or [])
            if not combined:
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "error": "protocol_violation",
                                "instruction": 'Return JSON with either {"requests":[...]} or {"final":{...}}.',
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

            retrieved, newly_seen, chars_used = _fulfill_requests(
                requests=combined, all_arts=all_arts, settings=settings
            )
            retrieved_chars_total += chars_used
            seen_ids |= newly_seen
            all_retrieved_artifacts.extend(retrieved)

            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "retrieved": retrieved,
                            "seen_artifact_ids": sorted(list(seen_ids)),
                            "missing_artifact_ids": sorted(list(all_set - seen_ids)),
                            "retrieved_chars_total": retrieved_chars_total,
                            "instruction": (
                                "Incorporate these details. If anything is still unclear or truncated, "
                                "request deeper slices. Otherwise produce final once missing_artifact_ids "
                                "is empty."
                            ),
                        },
                        ensure_ascii=False,
                    ),
                }
            )

        if final_obj is None:
            raise RuntimeError(
                f"LLM did not produce an acceptable final document within "
                f"DOC_MAX_TURNS={settings.doc_max_turns}."
            )

        return final_obj, all_retrieved_artifacts
