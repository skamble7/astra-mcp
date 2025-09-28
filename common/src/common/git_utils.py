"""Git utilities for safe repository operations."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse

try:
    import git
    from git import Repo, InvalidGitRepositoryError, GitCommandError
except ImportError:
    git = None
    Repo = None
    InvalidGitRepositoryError = Exception
    GitCommandError = Exception

from .logging import get_logger

logger = get_logger(__name__)


class GitError(Exception):
    """Base exception for git operations."""
    pass


def is_valid_git_url(url: str) -> bool:
    """Check if a URL is a valid git repository URL.
    
    Args:
        url: Repository URL to validate
        
    Returns:
        True if the URL appears to be a valid git repository URL
    """
    if not url:
        return False
    
    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    
    # Check for common git URL patterns
    if parsed.scheme in ('http', 'https', 'git', 'ssh'):
        return True
    
    # Check for SSH git URLs (git@github.com:user/repo.git)
    if '@' in url and ':' in url and not parsed.scheme:
        return True
    
    # Check for local paths
    if os.path.exists(url) and os.path.isdir(url):
        return True
    
    return False


def safe_path_join(base_path: str, *paths: str) -> str:
    """Safely join paths, preventing directory traversal attacks.
    
    Args:
        base_path: Base directory path
        *paths: Path components to join
        
    Returns:
        Safe joined path
        
    Raises:
        GitError: If the resulting path would escape the base path
    """
    base = Path(base_path).resolve()
    joined = base.joinpath(*paths).resolve()
    
    # Ensure the joined path is within the base path
    try:
        joined.relative_to(base)
    except ValueError:
        raise GitError(f"Path traversal detected: {paths}")
    
    return str(joined)


def clone_repository(
    repo_url: str,
    target_path: str,
    branch: Optional[str] = None,
    depth: Optional[int] = None,
    single_branch: bool = True,
) -> Dict[str, Any]:
    """Clone a git repository safely.
    
    Args:
        repo_url: Repository URL to clone
        target_path: Local path to clone to
        branch: Specific branch to clone (default: repository default)
        depth: Clone depth (None for full clone)
        single_branch: Whether to clone only the specified branch
        
    Returns:
        Dictionary with clone metadata
        
    Raises:
        GitError: If clone operation fails
    """
    if not git:
        raise GitError("GitPython is not installed")
    
    if not is_valid_git_url(repo_url):
        raise GitError(f"Invalid git URL: {repo_url}")
    
    # Ensure target directory exists and is writable
    target = Path(target_path)
    target.mkdir(parents=True, exist_ok=True)
    
    if not os.access(target, os.W_OK):
        raise GitError(f"Target path is not writable: {target_path}")
    
    # Clean up existing directory if it exists
    if target.exists() and any(target.iterdir()):
        logger.warning("Target directory is not empty, cleaning up", path=target_path)
        shutil.rmtree(target)
        target.mkdir(parents=True)
    
    try:
        logger.info("Starting git clone", url=repo_url, target=target_path, branch=branch)
        
        # Prepare clone arguments
        clone_kwargs = {
            'url': repo_url,
            'to_path': target_path,
        }
        
        if branch:
            clone_kwargs['branch'] = branch
        
        if depth:
            clone_kwargs['depth'] = depth
        
        if single_branch:
            clone_kwargs['single_branch'] = True
        
        # Perform the clone
        repo = Repo.clone_from(**clone_kwargs)
        
        # Get metadata
        metadata = {
            'url': repo_url,
            'path': target_path,
            'branch': repo.active_branch.name if repo.active_branch else 'HEAD',
            'commit': repo.head.commit.hexsha,
            'commit_message': repo.head.commit.message.strip(),
            'commit_author': str(repo.head.commit.author),
            'commit_date': repo.head.commit.committed_datetime.isoformat(),
        }
        
        # Add tag information if available
        try:
            tags = [tag.name for tag in repo.tags if tag.commit == repo.head.commit]
            if tags:
                metadata['tags'] = tags
        except Exception:
            pass  # Tags are optional
        
        logger.info("Git clone completed successfully", **metadata)
        return metadata
        
    except GitCommandError as e:
        logger.error("Git clone failed", error=str(e), url=repo_url)
        raise GitError(f"Clone failed: {e}")
    except Exception as e:
        logger.error("Unexpected error during clone", error=str(e), url=repo_url)
        raise GitError(f"Unexpected clone error: {e}")


def get_repository_info(repo_path: str) -> Dict[str, Any]:
    """Get information about an existing git repository.
    
    Args:
        repo_path: Path to the git repository
        
    Returns:
        Dictionary with repository metadata
        
    Raises:
        GitError: If not a valid git repository
    """
    if not git:
        raise GitError("GitPython is not installed")
    
    try:
        repo = Repo(repo_path)
        
        metadata = {
            'path': repo_path,
            'branch': repo.active_branch.name if repo.active_branch else 'HEAD',
            'commit': repo.head.commit.hexsha,
            'commit_message': repo.head.commit.message.strip(),
            'commit_author': str(repo.head.commit.author),
            'commit_date': repo.head.commit.committed_datetime.isoformat(),
            'is_dirty': repo.is_dirty(),
            'untracked_files': repo.untracked_files,
        }
        
        # Add remote information
        if repo.remotes:
            metadata['remotes'] = {
                remote.name: list(remote.urls)
                for remote in repo.remotes
            }
        
        # Add tag information
        try:
            tags = [tag.name for tag in repo.tags if tag.commit == repo.head.commit]
            if tags:
                metadata['tags'] = tags
        except Exception:
            pass
        
        return metadata
        
    except InvalidGitRepositoryError:
        raise GitError(f"Not a git repository: {repo_path}")
    except Exception as e:
        raise GitError(f"Error reading repository info: {e}")


def create_temp_clone(
    repo_url: str,
    branch: Optional[str] = None,
    depth: Optional[int] = 1,
) -> str:
    """Create a temporary clone of a repository.
    
    Args:
        repo_url: Repository URL to clone
        branch: Specific branch to clone
        depth: Clone depth (default: 1 for shallow clone)
        
    Returns:
        Path to the temporary clone directory
        
    Raises:
        GitError: If clone operation fails
    """
    temp_dir = tempfile.mkdtemp(prefix="astra_mcp_git_")
    
    try:
        clone_repository(
            repo_url=repo_url,
            target_path=temp_dir,
            branch=branch,
            depth=depth,
            single_branch=True,
        )
        return temp_dir
    except Exception:
        # Clean up on failure
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise