# File: servers/git-repo-snapshot/src/mcp_git_repo_snapshot/tools/clone_repo.py
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from git import Repo, GitCommandError  # GitPython

from ..models.params import CloneRepoParams
from ..models.repo_snapshot import RepoSnapshot


_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _sanitize_repo_dir_name(repo_url: str) -> str:
    """
    Produce a safe folder name from the repo URL, e.g., 'github-com_owner_repo'.
    """
    no_scheme = re.sub(r"^[a-zA-Z]+://", "", repo_url)
    safe = _SANITIZE_RE.sub("-", no_scheme).strip("-")
    return safe or "repo"


def _ensure_writable_dir(path_str: str) -> Path:
    p = Path(path_str).expanduser().resolve()
    if not p.is_absolute():
        raise ValueError("volume_path must be an absolute path")
    p.mkdir(parents=True, exist_ok=True)
    if not os.access(p, os.W_OK):
        raise PermissionError(f"Path not writable: {p}")
    return p


def _clone_or_update_repo(
    repo_url: str,
    target_dir: Path,
    branch: Optional[str],
    depth: Optional[int],
) -> Tuple[Repo, str]:
    """
    Clone if missing, otherwise fetch/checkout the requested branch.
    Returns (Repo, active_branch_name)
    """
    if (target_dir / ".git").exists():
        repo = Repo(str(target_dir))
        # fetch updates
        try:
            repo.remotes.origin.fetch()
        except GitCommandError as e:
            raise RuntimeError(f"git fetch failed: {e}") from e
    else:
        clone_kwargs = {}
        if depth and depth > 0:
            clone_kwargs["depth"] = depth
            clone_kwargs["single_branch"] = True
        try:
            repo = Repo.clone_from(repo_url, str(target_dir), **clone_kwargs)
        except GitCommandError as e:
            # clean up partial directory
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            raise RuntimeError(f"git clone failed: {e}") from e

    # Determine branch
    if branch:
        checkout_ref = branch
    else:
        # Resolve default branch from origin/HEAD if possible
        try:
            checkout_ref = repo.git.symbolic_ref("refs/remotes/origin/HEAD")
            # e.g. "refs/remotes/origin/main" -> "main"
            checkout_ref = checkout_ref.rsplit("/", 1)[-1]
        except GitCommandError:
            # fallback to 'main' then 'master'
            names = {r.name for r in repo.remotes.origin.refs}
            checkout_ref = "main" if "origin/main" in names or "main" in names else "master"

    # Checkout
    try:
        repo.git.checkout(checkout_ref)
        active_branch = checkout_ref
    except GitCommandError as e:
        raise RuntimeError(f"git checkout {checkout_ref} failed: {e}") from e

    return repo, active_branch


def _current_commit_sha(repo: Repo) -> str:
    return repo.git.rev_parse("HEAD")


def _tags_pointing_at_head(repo: Repo) -> List[str]:
    try:
        tags_output = repo.git.tag("--points-at", "HEAD")
        if not tags_output:
            return []
        return [t.strip() for t in tags_output.splitlines() if t.strip()]
    except GitCommandError:
        return []


async def clone_repo_tool(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    MCP tool handler: clones a repo into a given volume and returns the 'data'
    object for cam.asset.repo_snapshot (strict shape). The MCP SDK will JSON-serialize
    the dict you return.
    """
    validated = CloneRepoParams.model_validate(params)

    # Security: only allow https or ssh URL schemes (optional auth_mode hint)
    if validated.auth_mode:
        if validated.auth_mode not in {"https", "ssh"}:
            raise ValueError("auth_mode must be 'https' or 'ssh'")
    if not (
        validated.repo_url.startswith("https://")
        or validated.repo_url.startswith("ssh://")
        or validated.repo_url.startswith("git@")
    ):
        raise ValueError("repo_url must be https://, ssh://, or git@ style")

    volume_root = _ensure_writable_dir(validated.volume_path)
    repo_dir_name = _sanitize_repo_dir_name(validated.repo_url)
    target_dir = volume_root / repo_dir_name

    repo, active_branch = _clone_or_update_repo(
        repo_url=validated.repo_url,
        target_dir=target_dir,
        branch=validated.branch,
        depth=validated.depth,
    )

    commit_sha = _current_commit_sha(repo)
    head_tags = _tags_pointing_at_head(repo)

    # Build the strict data payload (matches artifact kind's json_schema)
    data = RepoSnapshot(
        repo=validated.repo_url,
        commit=commit_sha,
        branch=active_branch,
        paths_root=str(target_dir),
        tags=head_tags or None,
    ).model_dump(exclude_none=True)

    return data
