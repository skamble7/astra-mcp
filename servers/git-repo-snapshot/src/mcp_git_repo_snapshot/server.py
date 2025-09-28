from __future__ import annotations

from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP

from .models.repo_snapshot import RepoSnapshot
from .tools.clone_repo import clone_repo_tool

# FastMCP server instance (name is what clients will see)
mcp = FastMCP("git-repo-snapshot")


@mcp.tool(name="git.repo.snapshot", title="Git Repo Snapshot")
async def git_repo_snapshot(
    repo_url: str,
    volume_path: str,
    branch: Optional[str] = None,
    depth: Optional[int] = None,
    auth_mode: Optional[Literal["https", "ssh"]] = None,
) -> RepoSnapshot:
    """
    Clone a Git repository into a specified volume path and return a cam.asset.repo_snapshot
    'data' object (repo, commit, branch, paths_root, tags).
    """
    # Reuse our validated tool implementation. It returns a dict; FastMCP accepts
    # both dicts and pydantic models. We'll coerce to RepoSnapshot for a typed schema.
    data = await clone_repo_tool(
        {
            "repo_url": repo_url,
            "volume_path": volume_path,
            "branch": branch,
            "depth": depth,
            "auth_mode": auth_mode,
        }
    )
    return RepoSnapshot.model_validate(data)
