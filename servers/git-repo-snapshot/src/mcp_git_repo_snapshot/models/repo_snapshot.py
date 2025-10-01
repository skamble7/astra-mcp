# File: servers/git-repo-snapshot/src/mcp_git_repo_snapshot/models/repo_snapshot.py
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RepoSnapshot(BaseModel):
    """
    Matches the 'data' shape from the cam.asset.repo_snapshot json_schema.
    """
    repo: str = Field(min_length=1, description="Remote URL or origin name")
    commit: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    paths_root: str = Field(min_length=1, description="Filesystem mount/volume path used by tools")
    tags: Optional[List[str]] = None
