# servers/mcp-cobol-parser/mcp_cobol_parser/tools/parse_repo.py
from __future__ import annotations

import os
import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from ..settings import Settings, make_run_id
from ..pagination import CursorV1, encode_cursor, decode_cursor
from ..cache import (
    run_dir, source_index_path, manifest_path, artifact_path,
    write_json, read_json, exists,
)
from ..utils.fs import walk_index
from ..models.cam_source_index import CamSourceIndex, SourceIndexFile
from ..models.error_record import ErrorArtifact
from ..parsers.cb2xml import parse_copybook_with_cb2xml
from ..parsers.proleap import parse_program_with_proleap  # STRICT: real ProLeap only
from ..parsers.normalize.copybook_normalizer import normalize_cb2xml_tree
from ..parsers.normalize.program_normalizer import normalize_program_obj
from ..utils.artifacts import ensure_enveloped_item  # ← guardrail

logger = logging.getLogger("mcp.cobol.parse_repo")

ORDER = ["source_index", "copybook", "program"]

# Canonical kind_ids and schema versions for envelopes
KIND_IDS = {
    "source_index": "cam.asset.source_index",
    "copybook": "cam.cobol.copybook",
    "program": "cam.cobol.program",
    "error": "cam.error",
}
SCHEMA_VERS = {
    "cam.asset.source_index": "1.0.0",
    "cam.cobol.copybook": "1.0.0",
    "cam.cobol.program": "1.0.0",
    "cam.error": "1.0.0",
}

def _envelope(*, kind_id: str, key: str, data: Dict[str, Any], relpath: Optional[str], sha: Optional[str], cfg: Settings) -> Dict[str, Any]:
    return {
        "kind_id": kind_id,
        "schema_version": SCHEMA_VERS.get(kind_id, "1.0.0"),
        "key": key,
        "provenance": {
            "producer": "mcp.cobol.parse_repo",
            "parsers": {
                "proleap": cfg.PARSER_VERSION_PROLEAP,
                "cb2xml": cfg.PARSER_VERSION_CB2XML,
            },
            "source": {"relpath": relpath, "sha256": sha},
        },
        "data": data,
    }

class ParseRepoInput(BaseModel):
    paths_root: str
    page_size: Optional[int] = None
    cursor: Optional[str] = None
    kinds: Optional[List[str]] = None
    force_reparse: bool = False
    run_id: Optional[str] = None   # allows reusing an existing run

def register_tool(mcp: Any) -> None:
    @mcp.tool(name="cobol.parse_repo")
    def cobol_parse_repo(
        paths_root: str,
        page_size: Optional[int] = None,
        cursor: Optional[str] = None,
        kinds: Optional[List[str]] = None,
        force_reparse: bool = False,
        run_id: Optional[str] = None,
    ):
        input = ParseRepoInput(
            paths_root=paths_root,
            page_size=page_size,
            cursor=cursor,
            kinds=kinds,
            force_reparse=force_reparse,
            run_id=run_id,
        )

        cfg = Settings()

        resolved_kinds = input.kinds or ORDER
        for k in resolved_kinds:
            if k not in ORDER:
                raise ValueError(f"Unknown kind: {k}")

        effective_page_size = input.page_size or cfg.PAGE_SIZE
        if effective_page_size > cfg.MAX_PAGE_SIZE:
            effective_page_size = cfg.MAX_PAGE_SIZE

        root = os.path.abspath(input.paths_root)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"paths_root not found: {root}")

        # Cursor/run_id resolution
        cur_from_input: Optional[CursorV1] = None
        if input.cursor:
            try:
                cur_from_input = decode_cursor(input.cursor)
            except Exception:
                cur_from_input = None

        run_id_val = (
            (cur_from_input.run_id if cur_from_input else None)
            or input.run_id
            or make_run_id()
        )
        _ = run_dir(cfg, run_id_val)

        # Source index build/load
        src_index_fp = source_index_path(cfg, run_id_val)
        if exists(src_index_fp) and (cur_from_input or input.run_id):
            src_index = CamSourceIndex(**read_json(src_index_fp))
        else:
            files_raw = walk_index(root)
            files = [SourceIndexFile(**f) for f in files_raw]
            src_index = CamSourceIndex(root=root, files=files)
            write_json(src_index_fp, src_index.model_dump())

        files = src_index.files
        copy_files = [f for f in files if f.kind == "copybook" and ("copybook" in resolved_kinds)]
        prog_files = [f for f in files if f.kind == "cobol" and ("program" in resolved_kinds)]

        # Build catalog of envelope kinds to emit
        catalog: List[Dict[str, Any]] = []
        if "source_index" in resolved_kinds:
            catalog.append({"kind_id": KIND_IDS["source_index"], "key": "source-index", "sha": None})

        if "copybook" in resolved_kinds:
            for f in sorted(copy_files, key=lambda x: x.relpath):
                catalog.append({"kind_id": KIND_IDS["copybook"], "key": f.relpath, "sha": f.sha256})

        if "program" in resolved_kinds:
            for f in sorted(prog_files, key=lambda x: x.relpath):
                catalog.append({"kind_id": KIND_IDS["program"], "key": f.relpath, "sha": f.sha256})

        total = len(catalog)

        # Pagination
        if cur_from_input and cur_from_input.run_id == run_id_val:
            cur = cur_from_input
            cur.ps = effective_page_size
        else:
            cur = CursorV1(run_id=run_id_val, ps=effective_page_size)

        start = cur.offset
        end = min(start + effective_page_size, total)
        page_catalog = catalog[start:end]

        # Parse-on-demand for page items only; cache ENVELOPED artifacts
        def work_copy(item: Dict[str, Any]):
            rel = item["key"]
            sha = item["sha"]
            src_abs = os.path.join(root, rel)
            outp = artifact_path(cfg, run_id_val, sha, "copybook")
            if exists(outp) and not input.force_reparse:
                return ("copybook", rel, sha, None)
            try:
                tree = parse_copybook_with_cb2xml(src_abs, cfg)
                name = os.path.splitext(os.path.basename(rel))[0].upper()
                normalized = normalize_cb2xml_tree(tree, name=name, relpath=rel, sha256=sha).model_dump()
                env = _envelope(
                    kind_id=KIND_IDS["copybook"],
                    key=rel,
                    data=normalized,
                    relpath=rel,
                    sha=sha,
                    cfg=cfg,
                )
                write_json(outp, env)
                return ("copybook", rel, sha, None)
            except Exception as e:
                errp = artifact_path(cfg, run_id_val, sha, "error")
                env = ErrorArtifact(
                    key=rel,
                    data={"phase": "copybook", "error": str(e)},
                    provenance={"producer": "mcp.cobol.parse_repo", "source": {"relpath": rel, "sha256": sha}},
                ).model_dump()
                write_json(errp, env)
                return ("error", rel, sha, str(e))

        def work_prog(item: Dict[str, Any]):
            rel = item["key"]
            sha = item["sha"]
            src_abs = os.path.join(root, rel)
            outp = artifact_path(cfg, run_id_val, sha, "program")
            if exists(outp) and not input.force_reparse:
                return ("program", rel, sha, None)
            try:
                obj = parse_program_with_proleap(src_abs, cfg)  # STRICT: raises on issues
                normalized = normalize_program_obj(obj, relpath=rel, sha256=sha).model_dump()
                env = _envelope(
                    kind_id=KIND_IDS["program"],
                    key=rel,
                    data=normalized,
                    relpath=rel,
                    sha=sha,
                    cfg=cfg,
                )
                write_json(outp, env)
                return ("program", rel, sha, None)
            except Exception as e:
                errp = artifact_path(cfg, run_id_val, sha, "error")
                env = ErrorArtifact(
                    key=rel,
                    data={"phase": "program", "error": str(e)},
                    provenance={"producer": "mcp.cobol.parse_repo", "source": {"relpath": rel, "sha256": sha}},
                ).model_dump()
                write_json(errp, env)
                return ("error", rel, sha, str(e))

        # Ensure artifacts for THIS PAGE only
        tasks = []
        with ThreadPoolExecutor(max_workers=cfg.WORKERS) as ex:
            for it in page_catalog:
                kid = it["kind_id"]
                if kid == KIND_IDS["source_index"]:
                    continue
                if kid == KIND_IDS["copybook"]:
                    tasks.append(ex.submit(work_copy, it))
                elif kid == KIND_IDS["program"]:
                    tasks.append(ex.submit(work_prog, it))
            for _ in as_completed(tasks):
                pass

        # Write/refresh manifest
        from ..cache import write_json as _wjson
        _wjson(manifest_path(cfg, run_id_val), {
            "run_id": run_id_val,
            "paths_root": root,
            "kinds": resolved_kinds,
            "page_size": effective_page_size,
            "counts": {
                "source_index": 1 if "source_index" in resolved_kinds else 0,
                "copybook": len(copy_files) if "copybook" in resolved_kinds else 0,
                "program": len(prog_files) if "program" in resolved_kinds else 0,
            },
        })

        # Build the page payload (always ENVELOPED)
        page: List[Dict[str, Any]] = []
        for it in page_catalog:
            kid = it["kind_id"]
            if kid == KIND_IDS["source_index"]:
                env = _envelope(
                    kind_id=kid,
                    key="source-index",
                    data=src_index.model_dump(),
                    relpath=None,
                    sha=None,
                    cfg=cfg,
                )
                page.append(env)
                continue

            sha = it["sha"]
            if kid == KIND_IDS["copybook"]:
                ap = artifact_path(cfg, run_id_val, sha, "copybook")
                if exists(ap):
                    page.append(read_json(ap))
                else:
                    ep = artifact_path(cfg, run_id_val, sha, "error")
                    if exists(ep):
                        page.append(read_json(ep))
            elif kid == KIND_IDS["program"]:
                ap = artifact_path(cfg, run_id_val, sha, "program")
                if exists(ap):
                    page.append(read_json(ap))
                else:
                    ep = artifact_path(cfg, run_id_val, sha, "error")
                    if exists(ep):
                        page.append(read_json(ep))

        # FINAL GUARDRAIL: coerce any legacy/malformed entries into canonical envelope
        malformed = sum(1 for p in page if not (isinstance(p, dict) and "kind_id" in p and "data" in p))
        page = [ensure_enveloped_item(p) for p in page]

        next_cur = None
        if end < total:
            cur.offset = end
            next_cur = encode_cursor(cur)

        # ─── Logging summary ─────────────────────────────────────────────────
        counts = dict(Counter([p.get("kind_id") for p in page]))
        has_next = bool(next_cur)
        sample_n = max(0, int(os.getenv("ARTIFACT_LOG_SAMPLE", "5")))
        samples = []
        for p in page[:sample_n]:
            data_keys = sorted(list((p.get("data") or {}).keys()))[:12]
            samples.append({
                "kind_id": p.get("kind_id"),
                "schema_version": p.get("schema_version"),
                "key": p.get("key"),
                "data_keys": data_keys,
                "diagrams": bool(p.get("diagrams")),
                "narratives": bool(p.get("narratives")),
            })

        logger.info(
            "parse_repo page: run_id=%s items=%d kinds=%s next_cursor=%s coerced_legacy=%d",
            run_id_val, len(page), counts, "yes" if has_next else "no", malformed
        )
        if samples:
            logger.info("parse_repo samples: %s", samples)

        # ─── FULL BODY LOG (opt-in) ─────────────────────────────────────────
        if os.getenv("ARTIFACT_LOG_FULL", "").lower() in {"1", "true", "yes"}:
            resp_preview_limit = int(os.getenv("ARTIFACT_LOG_FULL_LIMIT", "0"))  # 0 = no cap
            try:
                full_obj = {
                    "run": {"run_id": run_id_val, "paths_root": root},
                    "meta": {
                        "counts": {
                            "source_index": 1 if "source_index" in resolved_kinds else 0,
                            "copybook": len(copy_files) if "copybook" in resolved_kinds else 0,
                            "program": len(prog_files) if "program" in resolved_kinds else 0,
                        },
                        "page_size": effective_page_size,
                    },
                    "artifacts": page,
                    "next_cursor": next_cur,
                }
                payload = json.dumps(full_obj, ensure_ascii=False)
                if resp_preview_limit and len(payload) > resp_preview_limit:
                    logger.info("parse_repo full response (truncated to %d chars): %s",
                                resp_preview_limit, payload[:resp_preview_limit])
                else:
                    logger.info("parse_repo full response: %s", payload)
            except Exception as e:
                logger.warning("parse_repo full response logging failed: %s", e)

        return {
            "run": {"run_id": run_id_val, "paths_root": root},
            "meta": {
                "counts": {
                    "source_index": 1 if "source_index" in resolved_kinds else 0,
                    "copybook": len(copy_files) if "copybook" in resolved_kinds else 0,
                    "program": len(prog_files) if "program" in resolved_kinds else 0,
                },
                "page_size": effective_page_size,
            },
            "artifacts": page,       # ← Canonical envelopes
            "next_cursor": next_cur,
        }