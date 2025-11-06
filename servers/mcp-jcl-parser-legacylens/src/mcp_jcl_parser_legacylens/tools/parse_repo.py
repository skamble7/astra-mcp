# servers/mcp-jcl-parser-legacylens/src/mcp_jcl_parser_legacylens/tools/parse_repo.py
from __future__ import annotations

import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from ..settings import Settings
from ..pagination import CursorV1, encode_cursor, decode_cursor
from ..cache import (
    run_dir, source_index_path, manifest_path, artifact_path,
    write_json, read_json, exists,
)
from ..utils.fs import walk_index, safe_join
from ..hashing import sha256_file
from ..parsers.legacylens import parse_jcl_file

logger = logging.getLogger("mcp.jcl.parse_repo")

ORDER = ["job", "step"]  # fixed (we don't accept kinds from input)

class ParseRepoInput(BaseModel):
    paths_root: str
    page_size: Optional[int] = None
    cursor: Optional[str] = None
    force_reparse: bool = False
    run_id: Optional[str] = None   # allows reusing an existing run

def _sanitize_key(s: str | None) -> str:
    if not s:
        return "unnamed"
    return "".join(ch if ch.isalnum() or ch in ("-","_") else "_" for ch in s)

def register_tool(mcp: Any) -> None:
    @mcp.tool(name="parse_jcl")
    def jcl_parse_repo(
        paths_root: str,
        page_size: Optional[int] = None,
        cursor: Optional[str] = None,
        force_reparse: bool = False,
        run_id: Optional[str] = None,
    ):
        """
        Paginated JCL parser. Pages over *files*; each file yields 0..N jobs and 0..M steps.
        Response mirrors the COBOL server envelope:
          { run, meta, artifacts, next_cursor }
        Only input that matters: paths_root (plus optional cursor/page_size/run_id for paging control).
        """
        input = ParseRepoInput(
            paths_root=paths_root,
            page_size=page_size,
            cursor=cursor,
            force_reparse=force_reparse,
            run_id=run_id,
        )
        cfg = Settings()

        # Page size
        effective_page_size = input.page_size or cfg.PAGE_SIZE
        if effective_page_size > cfg.MAX_PAGE_SIZE:
            effective_page_size = cfg.MAX_PAGE_SIZE

        # Validate root
        root = os.path.abspath(input.paths_root)
        if not os.path.isdir(root):
            raise FileNotFoundError(f"paths_root not found: {root}")

        # Resolve cursor / run_id
        cur_from_input: Optional[CursorV1] = None
        if input.cursor:
            try:
                cur_from_input = decode_cursor(input.cursor)
            except Exception:
                cur_from_input = None

        run_id_val = (
            (cur_from_input.run_id if cur_from_input else None)
            or input.run_id
            or _make_run_id()
        )
        _ = run_dir(cfg, run_id_val)  # ensure run dir

        # Build (or load) simple source index of JCL files
        idx_path = source_index_path(cfg, run_id_val)
        if exists(idx_path) and (cur_from_input or input.run_id):
            src_index = read_json(idx_path)
            files = src_index.get("files", [])
        else:
            files = walk_index(root)  # filters to .jcl only
            write_json(idx_path, {"root": root, "files": files})

        total_files = len(files)

        # Pagination init/advance
        if cur_from_input and cur_from_input.run_id == run_id_val:
            cur = cur_from_input
            cur.ps = effective_page_size
        else:
            cur = CursorV1(run_id=run_id_val, ps=effective_page_size)

        start = cur.offset
        end = min(start + effective_page_size, total_files)
        page_files = files[start:end]

        # Parse-on-demand for THIS PAGE only
        def work_file(fmeta: Dict[str, Any]):
            rel = fmeta["relpath"]
            abs_path = safe_join(root, rel)
            sha = sha256_file(abs_path)  # compute real sha for caching and keys

            should_parse = input.force_reparse
            if not should_parse:
                marker_job = artifact_path(cfg, run_id_val, sha, "job", "_index")
                should_parse = not exists(marker_job)

            if should_parse:
                parsed = parse_jcl_file(abs_path, rel, cfg)
                jobs = parsed.get("jobs") or []
                steps = parsed.get("steps") or []

                # Persist job artifacts (+ index)
                job_keys: list[str] = []
                for j in jobs:
                    job_name = _sanitize_key(j.get("job_name"))
                    ap = artifact_path(cfg, run_id_val, sha, "job", job_name)
                    write_json(ap, j)
                    job_keys.append(job_name)
                write_json(artifact_path(cfg, run_id_val, sha, "job", "_index"), {"keys": job_keys})

                # Persist step artifacts (+ index)
                step_keys: list[str] = []
                for s in steps:
                    job = _sanitize_key(s.get("job_name"))
                    step = _sanitize_key(s.get("step_name"))
                    ap = artifact_path(cfg, run_id_val, sha, "step", f"{job}__{step}")
                    write_json(ap, s)
                    step_keys.append(f"{job}__{step}")
                write_json(artifact_path(cfg, run_id_val, sha, "step", "_index"), {"keys": step_keys})

            # Build page payload by reading cached artifacts for both kinds
            out_items: list[dict] = []

            idx = artifact_path(cfg, run_id_val, sha, "job", "_index")
            if exists(idx):
                keys = (read_json(idx).get("keys") or [])
                for key in keys:
                    ap = artifact_path(cfg, run_id_val, sha, "job", key)
                    if exists(ap):
                        out_items.append({"kind": "cam.jcl.job", "key": f"{rel}::{key}", "data": read_json(ap)})

            idx = artifact_path(cfg, run_id_val, sha, "step", "_index")
            if exists(idx):
                keys = (read_json(idx).get("keys") or [])
                for key in keys:
                    ap = artifact_path(cfg, run_id_val, sha, "step", key)
                    if exists(ap):
                        out_items.append({"kind": "cam.jcl.step", "key": f"{rel}::{key}", "data": read_json(ap)})

            jobs_count = sum(1 for it in out_items if it["kind"] == "cam.jcl.job")
            steps_count = sum(1 for it in out_items if it["kind"] == "cam.jcl.step")
            return (out_items, jobs_count, steps_count, rel, sha)

        page: List[Dict[str, Any]] = []
        page_jobs, page_steps = 0, 0

        with ThreadPoolExecutor(max_workers=cfg.WORKERS) as ex:
            futs = [ex.submit(work_file, f) for f in page_files]
            for fut in as_completed(futs):
                items, jc, sc, rel, sha = fut.result()
                page.extend(items)
                page_jobs += jc
                page_steps += sc
                logger.debug("Parsed %s (sha=%s...): jobs=%d steps=%d", rel, sha[:8], jc, sc)

        # Write/refresh manifest (resources rely on this)
        write_json(manifest_path(cfg, run_id_val), {
            "run_id": run_id_val,
            "paths_root": root,
            "page_size": effective_page_size,
            "counts": {"files": total_files},
        })

        next_cur = None
        if end < total_files:
            cur.offset = end
            next_cur = encode_cursor(cur)

        return {
            "run": {"run_id": run_id_val, "paths_root": root},
            "meta": {
                "counts": {
                    "files_in_page": len(page_files),
                    "jobs_in_page": page_jobs,
                    "steps_in_page": page_steps,
                },
                "page_size": effective_page_size,
            },
            "artifacts": page,
            "next_cursor": next_cur,
        }

def _make_run_id() -> str:
    import datetime
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    return f"jcl_{ts}"