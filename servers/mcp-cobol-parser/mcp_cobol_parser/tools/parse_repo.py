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
from ..parsers.proleap import parse_program_with_proleap  # now returns (internal, raw_bridge, telemetry)
from ..parsers.normalize.copybook_normalizer import normalize_cb2xml_tree
from ..parsers.normalize.program_normalizer import normalize_program_obj
from ..utils.artifacts import ensure_enveloped_item  # ← guardrail

logger = logging.getLogger("mcp.cobol.parse_repo")

# default order (backward-compatible + new kinds)
ORDER = ["source_index", "copybook", "program", "ast_proleap", "asg_proleap", "parse_report"]

# Canonical kind_ids and schema versions for envelopes
KIND_IDS = {
    "source_index":  "cam.asset.source_index",
    "copybook":      "cam.cobol.copybook",
    "program":       "cam.cobol.program",
    "ast_proleap":   "cam.cobol.ast_proleap",
    "asg_proleap":   "cam.cobol.asg_proleap",
    "parse_report":  "cam.cobol.parse_report",
    "error":         "cam.error",
}
SCHEMA_VERS = {
    "cam.asset.source_index": "1.0.0",
    "cam.cobol.copybook":     "1.0.0",
    "cam.cobol.program":      "1.0.0",
    "cam.cobol.ast_proleap":  "1.0.0",
    "cam.cobol.asg_proleap":  "1.0.0",
    "cam.cobol.parse_report": "1.0.0",
    "cam.error":              "1.0.0",
}

# CHANGED: allow positional or keyword calls
def _envelope(kind_id: str, key: str, data: Dict[str, Any],
              relpath: Optional[str], sha: Optional[str], cfg: Settings) -> Dict[str, Any]:
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
        prog_files = [f for f in files if f.kind == "cobol" and any(k in resolved_kinds for k in ("program","ast_proleap","asg_proleap","parse_report"))]

        # Build catalog of envelope kinds to emit
        catalog: List[Dict[str, Any]] = []
        if "source_index" in resolved_kinds:
            catalog.append({"kind_id": KIND_IDS["source_index"], "key": "source-index", "sha": None})

        if "copybook" in resolved_kinds:
            for f in sorted(copy_files, key=lambda x: x.relpath):
                catalog.append({"kind_id": KIND_IDS["copybook"], "key": f.relpath, "sha": f.sha256})

        # For each COBOL program file, we may emit up to 4 artifacts
        for f in sorted(prog_files, key=lambda x: x.relpath):
            if "program" in resolved_kinds:
                catalog.append({"kind_id": KIND_IDS["program"], "key": f.relpath, "sha": f.sha256})
            if "ast_proleap" in resolved_kinds:
                catalog.append({"kind_id": KIND_IDS["ast_proleap"], "key": f.relpath, "sha": f.sha256})
            if "asg_proleap" in resolved_kinds:
                catalog.append({"kind_id": KIND_IDS["asg_proleap"], "key": f.relpath, "sha": f.sha256})
            if "parse_report" in resolved_kinds:
                catalog.append({"kind_id": KIND_IDS["parse_report"], "key": f.relpath, "sha": f.sha256})

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
                    KIND_IDS["copybook"],
                    rel,
                    normalized,
                    rel,
                    sha,
                    cfg,
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

        def work_prog_group(rel: str, sha: str):
            """
            Single parse for a COBOL file, then fan out:
              - cam.cobol.program
              - cam.cobol.ast_proleap
              - cam.cobol.asg_proleap (derived minimal if needed)
              - cam.cobol.parse_report
            """
            src_abs = os.path.join(root, rel)

            # Paths for each product
            p_prog  = artifact_path(cfg, run_id_val, sha, "program")
            p_ast   = artifact_path(cfg, run_id_val, sha, "ast_proleap")
            p_asg   = artifact_path(cfg, run_id_val, sha, "asg_proleap")
            p_prep  = artifact_path(cfg, run_id_val, sha, "parse_report")
            p_err   = artifact_path(cfg, run_id_val, sha, "error")

            # Skip if all already exist (unless force)
            if (all(exists(p) for p in (p_prog, p_ast, p_asg, p_prep)) and not input.force_reparse):
                return ("program-bundle", rel, sha, None)

            try:
                internal, raw_bridge, telemetry = parse_program_with_proleap(src_abs, cfg)  # STRICT

                # 1) cam.cobol.program (canonical)
                normalized = normalize_program_obj(internal, relpath=rel, sha256=sha).model_dump()
                env_prog = _envelope(
                    KIND_IDS["program"],
                    rel,
                    normalized,
                    rel,
                    sha,
                    cfg,
                )
                write_json(p_prog, env_prog)

                # 2) cam.cobol.ast_proleap (verbatim bridge JSON into ast)
                ast_payload = {
                    "parser": {"name": "proleap", "version": cfg.PARSER_VERSION_PROLEAP},
                    "source": {"relpath": rel, "sha256": sha},
                    "ast": raw_bridge,  # store bridge JSON verbatim
                    "stats": {
                        "node_count": None,  # unknown from bridge; keep None
                    },
                    "issues": [],  # we treat bridge 'status=ok' as no issues
                }
                env_ast = _envelope(
                    KIND_IDS["ast_proleap"],
                    rel,
                    ast_payload,
                    rel,
                    sha,
                    cfg,
                )
                write_json(p_ast, env_ast)

                # 3) cam.cobol.asg_proleap (derive minimal ASG from internal if needed)
                #    Build a lightweight call graph + performs using the normalized internal object.
                paras = internal.get("paragraphs") or []
                calls = []
                performs = []
                nodes = set()
                for p in paras:
                    pname = (p.get("name") or "").upper()
                    if pname:
                        nodes.add(pname)
                    for tgt in (p.get("performs") or []):
                        t = (tgt or "").upper()
                        if t:
                            performs.append({"from": pname, "to": t})
                            nodes.add(t)
                    for c in (p.get("calls") or []):
                        tgt = (c.get("target") or "").upper()
                        if tgt:
                            calls.append({"target": tgt, "dynamic": bool(c.get("dynamic"))})
                            nodes.add(tgt)

                asg_payload = {
                    "parser": {"name": "proleap", "version": cfg.PARSER_VERSION_PROLEAP},
                    "source": {"relpath": rel, "sha256": sha},
                    "asg": {
                        "program_id": internal.get("program_id"),
                        "performs": performs,
                        "calls": calls,
                        "symbols": {},  # not available; keep empty
                    },
                    "call_graph": {
                        "nodes": sorted(nodes),
                        "edges": [[e["from"], e["to"]] for e in performs],
                    },
                    "issues": [],
                }
                env_asg = _envelope(
                    KIND_IDS["asg_proleap"],
                    rel,
                    asg_payload,
                    rel,
                    sha,
                    cfg,
                )
                write_json(p_asg, env_asg)

                # 4) cam.cobol.parse_report (telemetry)
                parse_report = {
                    "parser": {"name": "proleap", "version": cfg.PARSER_VERSION_PROLEAP},
                    "source": {"relpath": rel, "sha256": sha},
                    "timings_ms": telemetry.get("timings_ms") or {},
                    "counters": telemetry.get("counters") or {},
                    "messages": telemetry.get("messages") or [],
                }
                env_prep = _envelope(
                    KIND_IDS["parse_report"],
                    rel,
                    parse_report,
                    rel,
                    sha,
                    cfg,
                )
                write_json(p_prep, env_prep)

                return ("program-bundle", rel, sha, None)

            except Exception as e:
                env = ErrorArtifact(
                    key=rel,
                    data={"phase": "program", "error": str(e)},
                    provenance={"producer": "mcp.cobol.parse_repo", "source": {"relpath": rel, "sha256": sha}},
                ).model_dump()
                write_json(p_err, env)
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
                elif kid in (KIND_IDS["program"], KIND_IDS["ast_proleap"], KIND_IDS["asg_proleap"], KIND_IDS["parse_report"]):
                    # group parse per COBOL file (dedupe by relpath)
                    # We key the group on relpath to run once.
                    rel = it["key"]; sha = it["sha"]
                    # Only submit once per relpath (simple dedupe: track a set locally)
                    if not any(getattr(t, "_rel", None) == rel for t in tasks):
                        fut = ex.submit(work_prog_group, rel, sha)
                        setattr(fut, "_rel", rel)
                        tasks.append(fut)

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
                "program": sum(1 for f in prog_files) if "program" in resolved_kinds else 0,
                "ast_proleap": sum(1 for f in prog_files) if "ast_proleap" in resolved_kinds else 0,
                "asg_proleap": sum(1 for f in prog_files) if "asg_proleap" in resolved_kinds else 0,
                "parse_report": sum(1 for f in prog_files) if "parse_report" in resolved_kinds else 0,
            },
        })

        # Build the page payload (always ENVELOPED)
        page: List[Dict[str, Any]] = []
        for it in page_catalog:
            kid = it["kind_id"]
            if kid == KIND_IDS["source_index"]:
                env = _envelope(
                    KIND_IDS["source_index"],
                    "source-index",
                    src_index.model_dump(),
                    None,
                    None,
                    cfg,
                )
                page.append(env)
                continue

            sha = it["sha"]; rel = it["key"]

            def _maybe_append(token: str):
                ap = artifact_path(cfg, run_id_val, sha, token)
                if exists(ap):
                    page.append(read_json(ap))
                else:
                    ep = artifact_path(cfg, run_id_val, sha, "error")
                    if exists(ep):
                        page.append(read_json(ep))

            if kid == KIND_IDS["copybook"]:
                _maybe_append("copybook")
            elif kid == KIND_IDS["program"]:
                _maybe_append("program")
            elif kid == KIND_IDS["ast_proleap"]:
                _maybe_append("ast_proleap")
            elif kid == KIND_IDS["asg_proleap"]:
                _maybe_append("asg_proleap")
            elif kid == KIND_IDS["parse_report"]:
                _maybe_append("parse_report")

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
                            "program": sum(1 for f in prog_files) if "program" in resolved_kinds else 0,
                            "ast_proleap": sum(1 for f in prog_files) if "ast_proleap" in resolved_kinds else 0,
                            "asg_proleap": sum(1 for f in prog_files) if "asg_proleap" in resolved_kinds else 0,
                            "parse_report": sum(1 for f in prog_files) if "parse_report" in resolved_kinds else 0,
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
                    "program": sum(1 for f in prog_files) if "program" in resolved_kinds else 0,
                    "ast_proleap": sum(1 for f in prog_files) if "ast_proleap" in resolved_kinds else 0,
                    "asg_proleap": sum(1 for f in prog_files) if "asg_proleap" in resolved_kinds else 0,
                    "parse_report": sum(1 for f in prog_files) if "parse_report" in resolved_kinds else 0,
                },
                "page_size": effective_page_size,
            },
            "artifacts": page,       # ← Canonical envelopes
            "next_cursor": next_cur,
        }