# servers/workspace-doc-generator/src/mcp_workspace_doc_generator/server.py
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

from .tools.generate_document import generate_workspace_document
from .models.params import GenerateParams
from .settings import Settings

log = logging.getLogger(os.getenv("SERVICE_NAME", "mcp.workspace.doc.generator"))

mcp = FastMCP("workspace-doc-generator")

# In-memory job store (simple; swap to Redis if you need persistence)
_JOBS: dict[str, dict[str, Any]] = {}

async def _run_doc_job(job_id: str, args: dict[str, Any]) -> None:
    job = _JOBS[job_id]
    job["status"] = "running"
    job["progress"] = 10.0
    job["message"] = "Fetching artifacts…"
    try:
        params = GenerateParams(**args)
        # Run the whole doc generation off the event loop if you add blocking bits later
        result = await generate_workspace_document(params)
        job["status"] = "done"
        job["progress"] = 100.0
        job["message"] = "Document generated."
        job["result"] = result                # full cam.asset.file_detail
        job["artifacts"] = [result]           # generic harvesters expect an artifacts array
    except Exception as e:
        log.exception("job.failed", extra={"job_id": job_id})
        job["status"] = "error"
        job["message"] = "Generation failed."
        job["error"] = f"{e.__class__.__name__}: {e}"

@mcp.tool(name="workspace.document.start", title="Start Workspace Document Generation")
async def workspace_document_start(workspace_id: str, prompt: str) -> dict:
    """Start async doc generation; returns job_id immediately."""
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {
        "status": "queued",
        "progress": 0.0,
        "message": "Queued",
        "workspace_id": workspace_id,
    }
    args = {"workspace_id": workspace_id, "prompt": prompt}
    asyncio.get_running_loop().create_task(_run_doc_job(job_id, args))
    log.info("job.start", extra={"job_id": job_id, "workspace_id": workspace_id})
    return {"job_id": job_id, "status": "queued", "progress": 0.0, "message": "Queued"}

@mcp.tool(name="workspace.document.status", title="Check Workspace Document Job")
async def workspace_document_status(job_id: str) -> dict:
    job = _JOBS.get(job_id)
    if not job:
        return {"job_id": job_id, "status": "error", "error": "Unknown job_id", "message": "Job not found."}

    out: dict[str, Any] = {
        "job_id": job_id,
        "status": job.get("status"),
        "progress": job.get("progress"),
        "message": job.get("message"),
    }
    if job.get("status") == "done":
        # expose both (result and artifacts)
        out["result"] = job.get("result")
        out["artifacts"] = job.get("artifacts")
    if job.get("status") == "error":
        out["error"] = job.get("error")
    return out

# (Optional) keep the direct tool for simple callers; it can still time out if LLM is slow.
@mcp.tool(name="generate.workspace.document", title="Generate Workspace Document (blocking)")
async def tool_generate_workspace_document(workspace_id: str, prompt: str) -> Dict[str, Any]:
    log.info("tool.call", extra={"tool": "generate.workspace.document", "workspace_id": workspace_id})
    params = GenerateParams(workspace_id=workspace_id, prompt=prompt)
    return await generate_workspace_document(params)

try:
    @mcp.on_startup  # type: ignore[attr-defined]
    async def _on_start() -> None:
        s = Settings.from_env()
        log.info(
            "Workspace Doc Generator started",
            extra={
                "transport": os.getenv("MCP_TRANSPORT", "streamable-http"),
                "llm_enabled": s.enable_real_llm,
                "llm_provider": s.llm_provider,
                "llm_model": s.llm_model,
                "artifact_service_url": s.artifact_service_url,
            },
        )
except Exception:
    pass