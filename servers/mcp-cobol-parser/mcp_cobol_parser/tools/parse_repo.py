# servers/mcp-cobol-parser/mcp_cobol_parser/tools/parse_repo.py
from __future__ import annotations

import os
import logging
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

ORDER = ["source_index", "copybook", "program"]


class ParseRepoInput(BaseModel):
    paths_root: str
    page_size: Optional[int] = None
    cursor: Optional[str] = None
    kinds: Optional[List[str]] = None
    force_reparse: bool = False
    run_id: Optional[str] = None   # allows reusing an existing run


def register_tool(mcp: Any) -> None:
    # Accept FLAT parameters so MCP clients don't need an 'input' wrapper
    @mcp.tool(name="cobol.parse_repo")
    def cobol_parse_repo(
        paths_root: str,
        page_size: Optional[int] = None,
        cursor: Optional[str] = None,
        kinds: Optional[List[str]] = None,
        force_reparse: bool = False,
        run_id: Optional[str] = None,
    ):
        # Normalize into our internal model
        input = ParseRepoInput(
            paths_root=paths_root,
            page_size=page_size,
            cursor=cursor,
            kinds=kinds,
            force_reparse=force_reparse,
            run_id=run_id,
        )

        cfg = Settings()

        # Resolve kinds & page size
        resolved_kinds = input.kinds or ORDER
        for k in resolved_kinds:
            if k not in ORDER:
                raise ValueError(f"Unknown kind: {k}")

        effective_page_size = input.page_size or cfg.PAGE_SIZE
        if effective_page_size > cfg.MAX_PAGE_SIZE:
            effective_page_size = cfg.MAX_PAGE_SIZE

        # Validate root
        root = os.path.abspath(input.paths_root)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"paths_root not found: {root}")

        # Resolve run_id: prefer cursor.run_id, else provided run_id, else new
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
        _ = run_dir(cfg, run_id_val)  # ensures run dir exists

        # Load or build Source Index (per run)
        src_index_path = source_index_path(cfg, run_id_val)
        if exists(src_index_path) and (cur_from_input or input.run_id):
            src_index = CamSourceIndex(**read_json(src_index_path))
        else:
            files_raw = walk_index(root)
            files = [SourceIndexFile(**f) for f in files_raw]
            src_index = CamSourceIndex(root=root, files=files)
            write_json(src_index_path, src_index.model_dump())

        # Plan lists from index (do NOT parse yet)
        files = src_index.files
        copy_files = [f for f in files if f.kind == "copybook" and ("copybook" in resolved_kinds)]
        prog_files = [f for f in files if f.kind == "cobol" and ("program" in resolved_kinds)]

        # Build a "catalog" of what this run exposes, in ORDER
        catalog: List[Dict[str, Any]] = []
        if "source_index" in resolved_kinds:
            catalog.append({"kind": "cam.asset.source_index", "key": "source-index", "meta": {}})

        if "copybook" in resolved_kinds:
            for f in sorted(copy_files, key=lambda x: x.relpath):
                catalog.append({"kind": "cam.cobol.copybook", "key": f.relpath, "sha": f.sha256})

        if "program" in resolved_kinds:
            for f in sorted(prog_files, key=lambda x: x.relpath):
                catalog.append({"kind": "cam.cobol.program", "key": f.relpath, "sha": f.sha256})

        total = len(catalog)

        # Pagination — initialize or advance cursor (bind to this run)
        if cur_from_input and cur_from_input.run_id == run_id_val:
            cur = cur_from_input
            cur.ps = effective_page_size
        else:
            cur = CursorV1(run_id=run_id_val, ps=effective_page_size)

        start = cur.offset
        end = min(start + effective_page_size, total)
        page_catalog = catalog[start:end]

        # Parse-on-demand helpers (only for items on this page)
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
                normalized = normalize_cb2xml_tree(tree, name=name, relpath=rel, sha256=sha)
                write_json(outp, normalized.model_dump())
                return ("copybook", rel, sha, None)
            except Exception as e:
                errp = artifact_path(cfg, run_id_val, sha, "error")
                write_json(
                    errp,
                    ErrorArtifact(key=rel, data={"phase": "copybook", "error": str(e)}).model_dump(),
                )
                return ("error", rel, sha, str(e))

        def work_prog(item: Dict[str, Any]):
            rel = item["key"]
            sha = item["sha"]
            src_abs = os.path.join(root, rel)
            outp = artifact_path(cfg, run_id_val, sha, "program")
            if exists(outp) and not input.force_reparse:
                return ("program", rel, sha, None)
            try:
                obj = parse_program_with_proleap(src_abs, cfg)  # STRICT: will raise on any issue

                # Diagnostic: confirm richer fields are flowing from JsonCli
                try:
                    eng = obj.get("engine")
                    sf = obj.get("sourceFormat")
                    pid = obj.get("programId") or obj.get("program_id")
                    logger = logging.getLogger("mcp.cobol.parse_repo")
                    logger.info(
                        "normalized %s (engine=%s, sourceFormat=%s, programId=%s)",
                        rel, eng, sf, pid
                    )
                except Exception:
                    # Don't let logging issues affect parsing
                    pass

                normalized = normalize_program_obj(obj, relpath=rel, sha256=sha)
                write_json(outp, normalized.model_dump())
                return ("program", rel, sha, None)
            except Exception as e:
                errp = artifact_path(cfg, run_id_val, sha, "error")
                write_json(
                    errp,
                    ErrorArtifact(key=rel, data={"phase": "program", "error": str(e)}).model_dump(),
                )
                return ("error", rel, sha, str(e))

        # Ensure artifacts for THIS PAGE only
        # (source_index is synthetic and needs no parsing)
        tasks = []
        with ThreadPoolExecutor(max_workers=cfg.WORKERS) as ex:
            for it in page_catalog:
                kind = it["kind"]
                if kind == "cam.asset.source_index":
                    continue
                if kind == "cam.cobol.copybook":
                    tasks.append(ex.submit(work_copy, it))
                elif kind == "cam.cobol.program":
                    tasks.append(ex.submit(work_prog, it))

            # drain
            for _ in as_completed(tasks):
                pass

        # Write/refresh manifest (resources rely on this); counts are advisory
        write_json(manifest_path(cfg, run_id_val), {
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

        # Build the page payload by reading cached artifacts now present
        page: List[Dict[str, Any]] = []
        for it in page_catalog:
            kind = it["kind"]
            if kind == "cam.asset.source_index":
                page.append({"kind": kind, "key": "source-index", "data": src_index.model_dump()})
                continue

            sha = it["sha"]
            if kind == "cam.cobol.copybook":
                ap = artifact_path(cfg, run_id_val, sha, "copybook")
                if exists(ap):
                    page.append({"kind": kind, "key": it["key"], "data": read_json(ap)})
                else:
                    ep = artifact_path(cfg, run_id_val, sha, "error")
                    if exists(ep):
                        page.append({"kind": "error", "key": it["key"], "data": read_json(ep)["data"]})
            elif kind == "cam.cobol.program":
                ap = artifact_path(cfg, run_id_val, sha, "program")
                if exists(ap):
                    page.append({"kind": kind, "key": it["key"], "data": read_json(ap)})
                else:
                    ep = artifact_path(cfg, run_id_val, sha, "error")
                    if exists(ep):
                        page.append({"kind": "error", "key": it["key"], "data": read_json(ep)["data"]})

        next_cur = None
        if end < total:
            cur.offset = end
            next_cur = encode_cursor(cur)

        return {
            "run": {
                "run_id": run_id_val,
                "paths_root": root,
            },
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