# File: servers/git-repo-snapshot/src/mcp_git_repo_snapshot/server.py
from __future__ import annotations

import asyncio
import uuid
import logging
import os
from typing import Literal, Optional, Dict, Any

from mcp.server.fastmcp import FastMCP
from .models.repo_snapshot import RepoSnapshot
from .tools.clone_repo import clone_repo_tool

logger = logging.getLogger("mcp.git-repo-snapshot.server")
mcp = FastMCP("git-repo-snapshot")

_JOBS: dict[str, dict[str, Any]] = {}

async def _run_clone_job(job_id: str, args: dict[str, Any]) -> None:
    job = _JOBS[job_id]
    job["status"] = "running"
    job["progress"] = 50.0  # coarse midpoint; refine if clone_repo_tool can stream progress
    job["message"] = "Cloning repository…"
    try:
        data = await asyncio.to_thread(clone_repo_tool, args)
        # Normalize RepoSnapshot → dict
        snapshot = RepoSnapshot.model_validate(data).model_dump()
        job["result"] = snapshot
        job["artifacts"] = [snapshot]         # <— standard artifacts array (matches output_contract.artifacts_property)
        job["status"] = "done"
        job["progress"] = 100.0
        job["message"] = "Snapshot complete."
    except Exception as e:
        job["error"] = str(e)
        job["status"] = "error"
        job["message"] = "Snapshot failed."

@mcp.tool(name="git.repo.snapshot.start", title="Start Git Repo Snapshot")
async def git_repo_snapshot_start(
    repo_url: str,
    volume_path: str,
    branch: Optional[str] = None,
    depth: Optional[int] = 1,
    auth_mode: Optional[Literal["https", "ssh"]] = None,
) -> dict:
    # Basic arg hygiene (generic callers won’t know your filesystem)
    try:
        os.makedirs(volume_path, exist_ok=True)
    except Exception as e:
        return {
            "job_id": None,
            "status": "error",
            "error": f"Invalid volume_path: {e}",
            "message": "Could not prepare destination directory."
        }

    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {
        "status": "queued",
        "progress": 0.0,
        "message": "Snapshot queued.",
    }
    args = {
        "repo_url": repo_url,
        "volume_path": volume_path,
        "branch": branch,
        "depth": depth,
        "auth_mode": auth_mode,
    }
    asyncio.get_running_loop().create_task(_run_clone_job(job_id, args))
    # Start responses should be minimal but predictable
    return {
        "job_id": job_id,
        "status": "queued",
        "progress": 0.0,
        "message": "Snapshot queued."
    }

@mcp.tool(name="git.repo.snapshot.status", title="Check Snapshot Status")
async def git_repo_snapshot_status(job_id: str) -> dict:
    job = _JOBS.get(job_id)
    if not job:
        return {
            "job_id": job_id,
            "status": "error",         # <— normalize; avoid custom "not_found"
            "error": "Unknown job_id",
            "message": "Job not found."
        }

    # Always return a consistent envelope
    out: dict[str, Any] = {
        "job_id": job_id,
        "status": job.get("status", "error"),
        "progress": job.get("progress", None),
        "message": job.get("message", None),
    }

    if job.get("status") == "done":
        # Prefer artifacts (generic harvesters), keep result for backward compat
        if "artifacts" in job:
            out["artifacts"] = job["artifacts"]
        if "result" in job:
            out["result"] = job["result"]

    if job.get("status") == "error":
        out["error"] = job.get("error", "unknown error")

    # Future-friendly: cursors if you ever page results
    out["next_cursor"] = None

    return out

try:
    @mcp.on_startup  # type: ignore[attr-defined]
    async def _on_start() -> None:
        logger.info("FastMCP server started with tools: %s", [t.name for t in mcp.tools])
except Exception:
    pass