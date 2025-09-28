#servers/git-repo-snapshot/src/mcp_git_repo_snapshot/models/params.py

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CloneRepoParams(BaseModel):
    """
    Input parameters for the tool:
      - repo_url: Remote Git URL (https or ssh)
      - volume_path: Absolute path to a writable directory where the repo will be cloned
      - branch: Optional branch name (defaults to remote HEAD)
      - depth: Optional shallow clone depth (e.g., 1)
      - auth_mode: Optional hint ("https" or "ssh")
    """

    repo_url: str = Field(min_length=1)
    volume_path: str = Field(min_length=1)
    branch: Optional[str] = None
    depth: Optional[int] = Field(default=None, ge=0)
    auth_mode: Optional[str] = Field(default=None, pattern="^(https|ssh)$")
