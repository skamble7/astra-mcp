# server.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .models.params import GenerateGuidanceParams
from .settings import Settings
from .tools.microservices_guidance import generate_microservices_arch_guidance
from .tools.data_pipeline_guidance import generate_data_pipeline_arch_guidance

log = logging.getLogger(os.getenv("SERVICE_NAME", "mcp.raina.arch.guidance.generator"))

allowed_hosts = os.getenv(
    "ALLOWED_HOSTS",
    "localhost:*,127.0.0.1:*,host.docker.internal:*,*",
).split(",")
allowed_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:*,http://127.0.0.1:*,http://host.docker.internal:*,*",
).split(",")

mcp = FastMCP(
    "mcp.raina.arch.guidance.generator",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    ),
)

_JOBS: dict[str, dict[str, Any]] = {}


def _safe_cfg_snapshot(s: Settings) -> dict[str, Any]:
    return {
        "transport": os.getenv("MCP_TRANSPORT", "streamable-http"),
        "llm_enabled": s.enable_real_llm,
        "config_ref": s.config_ref,
        "artifact_service_url": s.artifact_service_url,
        "s3_enabled": s.s3_enabled,
        "s3_endpoint_url": s.s3_endpoint_url,
        "s3_bucket": s.s3_bucket,
        "s3_prefix": s.s3_prefix,
    }


async def _run_guidance_job(job_id: str, workspace_id: str) -> None:
    job = _JOBS[job_id]
    job["status"] = "running"
    job["progress"] = 10.0
    job["message"] = "Generating architecture guidance document…"
    try:
        params = GenerateGuidanceParams(workspace_id=workspace_id)
        result = await generate_microservices_arch_guidance(params)
        job["status"] = "done"
        job["progress"] = 100.0
        job["message"] = "Architecture guidance document generated."
        job["result"] = result
        job["artifacts"] = result.get("artifacts", [])
    except Exception as e:
        log.exception("job.failed job_id=%s", job_id)
        job["status"] = "error"
        job["message"] = "Generation failed."
        job["error"] = f"{e.__class__.__name__}: {e}"


# ---------------------------------------------------------------------------
# Async (job-based) tools — for long-running generation
# ---------------------------------------------------------------------------

@mcp.tool(
    name="microservices.arch.guidance.start",
    title="Start Microservices Architecture Guidance Generation",
)
async def microservices_arch_guidance_start(workspace_id: str) -> dict:
    """
    Queue a background job to generate the microservices architecture guidance document
    for the given workspace. Returns a job_id for status polling.
    """
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {
        "status": "queued",
        "progress": 0.0,
        "message": "Queued",
        "workspace_id": workspace_id,
    }
    asyncio.get_running_loop().create_task(_run_guidance_job(job_id, workspace_id))
    log.info("job.start job_id=%s workspace_id=%s", job_id, workspace_id)
    return {"job_id": job_id, "status": "queued", "progress": 0.0, "message": "Queued"}


@mcp.tool(
    name="microservices.arch.guidance.status",
    title="Check Architecture Guidance Generation Job",
)
async def microservices_arch_guidance_status(job_id: str) -> dict:
    """Poll a background guidance generation job by job_id."""
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
        out["result"] = job.get("result")
        out["artifacts"] = job.get("artifacts")
    if job.get("status") == "error":
        out["error"] = job.get("error")
    return out


# ---------------------------------------------------------------------------
# Blocking tool — direct call, no job management
# ---------------------------------------------------------------------------

@mcp.tool(
    name="generate_microservices_arch_guidance",
    title="Generate Microservices Architecture Guidance (blocking)",
)
async def tool_generate_microservices_arch_guidance(workspace_id: str) -> Dict[str, Any]:
    """
    Generate a cam.governance.microservices_arch_guidance artifact from the workspace
    artifacts produced by the Microservices Architecture Discovery Pack.

    Accepts a workspace_id, fetches all workspace artifacts, runs a multi-turn LLM
    retrieval loop to produce the guidance Markdown document, uploads it to Garage/S3,
    and returns the artifact payload.
    """
    log.info("tool.call name=generate_microservices_arch_guidance workspace_id=%s", workspace_id)
    params = GenerateGuidanceParams(workspace_id=workspace_id)
    return await generate_microservices_arch_guidance(params)


async def _run_data_pipeline_guidance_job(job_id: str, workspace_id: str) -> None:
    job = _JOBS[job_id]
    job["status"] = "running"
    job["progress"] = 10.0
    job["message"] = "Generating data pipeline architecture guidance document…"
    try:
        params = GenerateGuidanceParams(workspace_id=workspace_id)
        result = await generate_data_pipeline_arch_guidance(params)
        job["status"] = "done"
        job["progress"] = 100.0
        job["message"] = "Data pipeline architecture guidance document generated."
        job["result"] = result
        job["artifacts"] = result.get("artifacts", [])
    except Exception as e:
        log.exception("job.failed job_id=%s", job_id)
        job["status"] = "error"
        job["message"] = "Generation failed."
        job["error"] = f"{e.__class__.__name__}: {e}"


# ---------------------------------------------------------------------------
# Data Pipeline — async (job-based) tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="data_pipeline.arch.guidance.start",
    title="Start Data Pipeline Architecture Guidance Generation",
)
async def data_pipeline_arch_guidance_start(workspace_id: str) -> dict:
    """
    Queue a background job to generate the data pipeline architecture guidance document
    for the given workspace. Returns a job_id for status polling.
    """
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {
        "status": "queued",
        "progress": 0.0,
        "message": "Queued",
        "workspace_id": workspace_id,
    }
    asyncio.get_running_loop().create_task(_run_data_pipeline_guidance_job(job_id, workspace_id))
    log.info("job.start job_id=%s workspace_id=%s", job_id, workspace_id)
    return {"job_id": job_id, "status": "queued", "progress": 0.0, "message": "Queued"}


@mcp.tool(
    name="data_pipeline.arch.guidance.status",
    title="Check Data Pipeline Architecture Guidance Generation Job",
)
async def data_pipeline_arch_guidance_status(job_id: str) -> dict:
    """Poll a background data pipeline guidance generation job by job_id."""
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
        out["result"] = job.get("result")
        out["artifacts"] = job.get("artifacts")
    if job.get("status") == "error":
        out["error"] = job.get("error")
    return out


# ---------------------------------------------------------------------------
# Data Pipeline — blocking tool
# ---------------------------------------------------------------------------

@mcp.tool(
    name="generate_data_pipeline_arch_guidance",
    title="Generate Data Pipeline Architecture Guidance (blocking)",
)
async def tool_generate_data_pipeline_arch_guidance(workspace_id: str) -> Dict[str, Any]:
    """
    Generate a cam.governance.data_pipeline_arch_guidance artifact from the workspace
    artifacts produced by the Data Engineering Architecture Discovery Pack.

    Accepts a workspace_id, fetches all workspace artifacts, runs a multi-turn LLM
    retrieval loop to produce the guidance Markdown document, uploads it to Garage/S3,
    and returns the artifact payload.
    """
    log.info("tool.call name=generate_data_pipeline_arch_guidance workspace_id=%s", workspace_id)
    params = GenerateGuidanceParams(workspace_id=workspace_id)
    return await generate_data_pipeline_arch_guidance(params)


try:
    @mcp.on_startup  # type: ignore[attr-defined]
    async def _on_start() -> None:
        s = Settings.from_env()
        snap = json.dumps(_safe_cfg_snapshot(s), ensure_ascii=False)
        log.info("Raina Arch Guidance Generator started cfg=%s", snap)
except Exception:
    pass
