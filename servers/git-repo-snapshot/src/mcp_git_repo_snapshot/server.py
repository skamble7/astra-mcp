# File: servers/git-repo-snapshot/src/mcp_git_repo_snapshot/server.py
from __future__ import annotations

import asyncio
import uuid
from typing import Literal, Optional, Dict, Any

from mcp.server.fastmcp import FastMCP
from .models.repo_snapshot import RepoSnapshot
from .tools.clone_repo import clone_repo_tool

mcp = FastMCP("git-repo-snapshot")

# In-memory job table (you can swap to a file/db if you want persistence)
_JOBS: dict[str, dict[str, Any]] = {}   # { job_id: {status, result, error, started_at, ...} }


async def _run_clone_job(job_id: str, args: dict[str, Any]) -> None:
    _JOBS[job_id]["status"] = "running"
    try:
        # Run the blocking Git work off the event loop
        data = await asyncio.to_thread(clone_repo_tool, args)
        _JOBS[job_id]["result"] = data             # strict RepoSnapshot shape
        _JOBS[job_id]["status"] = "done"
    except Exception as e:
        _JOBS[job_id]["error"] = str(e)
        _JOBS[job_id]["status"] = "error"


@mcp.tool(name="git.repo.snapshot.start", title="Start Git Repo Snapshot")
async def git_repo_snapshot_start(
    repo_url: str,
    volume_path: str,
    branch: Optional[str] = None,
    depth: Optional[int] = 1,   # default to shallow for speed
    auth_mode: Optional[Literal["https", "ssh"]] = None,
) -> dict:
    """Start the clone/snapshot job and return a job_id to poll."""
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = {"status": "queued"}
    args = {
        "repo_url": repo_url,
        "volume_path": volume_path,
        "branch": branch,
        "depth": depth,
        "auth_mode": auth_mode,
    }
    # fire-and-forget background task (do not block this request)
    asyncio.get_running_loop().create_task(_run_clone_job(job_id, args))
    return {"job_id": job_id, "status": "queued"}


@mcp.tool(name="git.repo.snapshot.status", title="Check Snapshot Status")
async def git_repo_snapshot_status(job_id: str) -> dict:
    """Poll job status. When status=='done', returns the snapshot result."""
    job = _JOBS.get(job_id)
    if not job:
        return {"job_id": job_id, "status": "not_found"}
    out: dict[str, Any] = {"job_id": job_id, "status": job["status"]}
    if job["status"] == "done":
        out["result"] = RepoSnapshot.model_validate(job["result"]).model_dump()
    if job["status"] == "error":
        out["error"] = job.get("error", "unknown error")
    return out