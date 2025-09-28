"""OS and path utilities for safe file system operations."""

import os
import stat
from pathlib import Path
from typing import Optional, List, Dict, Any

from .logging import get_logger

logger = get_logger(__name__)


class PathError(Exception):
    """Exception for path-related errors."""
    pass


def normalize_volume_path(volume_path: str) -> str:
    """Normalize a volume path for cross-platform compatibility.
    
    Args:
        volume_path: Raw volume path
        
    Returns:
        Normalized absolute path
        
    Raises:
        PathError: If path is invalid or inaccessible
    """
    if not volume_path:
        raise PathError("Volume path cannot be empty")
    
    # Convert to Path object and resolve
    path = Path(volume_path).expanduser().resolve()
    
    # Ensure it's absolute
    if not path.is_absolute():
        raise PathError(f"Volume path must be absolute: {volume_path}")
    
    return str(path)


def ensure_directory_writable(directory_path: str) -> str:
    """Ensure a directory exists and is writable.
    
    Args:
        directory_path: Path to check/create
        
    Returns:
        Normalized path to the directory
        
    Raises:
        PathError: If directory cannot be created or is not writable
    """
    normalized_path = normalize_volume_path(directory_path)
    path = Path(normalized_path)
    
    try:
        # Create directory if it doesn't exist
        path.mkdir(parents=True, exist_ok=True)
        
        # Check if writable
        if not os.access(path, os.W_OK):
            raise PathError(f"Directory is not writable: {normalized_path}")
        
        logger.debug("Directory is writable", path=normalized_path)
        return normalized_path
        
    except PermissionError as e:
        raise PathError(f"Permission denied creating directory {normalized_path}: {e}")
    except OSError as e:
        raise PathError(f"Failed to create directory {normalized_path}: {e}")


def safe_join_path(base_path: str, *path_components: str) -> str:
    """Safely join path components, preventing directory traversal.
    
    Args:
        base_path: Base directory path
        *path_components: Path components to join
        
    Returns:
        Safe joined path
        
    Raises:
        PathError: If the resulting path would escape the base path
    """
    base = Path(base_path).resolve()
    
    # Join all components
    joined = base
    for component in path_components:
        # Remove any leading slashes or dots that could cause traversal
        clean_component = str(component).lstrip('/').lstrip('\\')
        if clean_component in ('', '.', '..'):
            continue
        joined = joined / clean_component
    
    resolved = joined.resolve()
    
    # Ensure the resolved path is within the base path
    try:
        resolved.relative_to(base)
    except ValueError:
        raise PathError(f"Path traversal detected: {path_components}")
    
    return str(resolved)


def get_directory_info(directory_path: str) -> Dict[str, Any]:
    """Get information about a directory.
    
    Args:
        directory_path: Path to analyze
        
    Returns:
        Dictionary with directory information
    """
    path = Path(directory_path)
    
    if not path.exists():
        raise PathError(f"Path does not exist: {directory_path}")
    
    if not path.is_dir():
        raise PathError(f"Path is not a directory: {directory_path}")
    
    try:
        stat_info = path.stat()
        
        info = {
            'path': str(path.resolve()),
            'exists': True,
            'is_directory': True,
            'readable': os.access(path, os.R_OK),
            'writable': os.access(path, os.W_OK),
            'executable': os.access(path, os.X_OK),
            'size_bytes': stat_info.st_size,
            'created_time': stat_info.st_ctime,
            'modified_time': stat_info.st_mtime,
            'accessed_time': stat_info.st_atime,
            'permissions': oct(stat_info.st_mode)[-3:],
        }
        
        # Count contents
        try:
            contents = list(path.iterdir())
            info['file_count'] = len([f for f in contents if f.is_file()])
            info['directory_count'] = len([f for f in contents if f.is_dir()])
            info['total_items'] = len(contents)
        except PermissionError:
            info['file_count'] = None
            info['directory_count'] = None
            info['total_items'] = None
        
        return info
        
    except (OSError, PermissionError) as e:
        raise PathError(f"Cannot access directory info: {e}")


def compute_paths_root(volume_path: str, namespace: str = "repos") -> str:
    """Compute the root path for storing repositories within a volume.
    
    Args:
        volume_path: Base volume path
        namespace: Namespace for organizing content (default: "repos")
        
    Returns:
        Path to the repository root directory
    """
    normalized_volume = normalize_volume_path(volume_path)
    return safe_join_path(normalized_volume, namespace)


def get_available_space(directory_path: str) -> Dict[str, int]:
    """Get available disk space for a directory.
    
    Args:
        directory_path: Path to check
        
    Returns:
        Dictionary with space information in bytes
    """
    path = Path(directory_path)
    
    try:
        # Get the mount point for this path
        mount_point = path
        while not mount_point.exists():
            mount_point = mount_point.parent
            if mount_point == mount_point.parent:  # Root reached
                break
        
        statvfs = os.statvfs(mount_point)
        
        return {
            'total_bytes': statvfs.f_frsize * statvfs.f_blocks,
            'available_bytes': statvfs.f_frsize * statvfs.f_bavail,
            'free_bytes': statvfs.f_frsize * statvfs.f_bfree,
            'used_bytes': statvfs.f_frsize * (statvfs.f_blocks - statvfs.f_bfree),
        }
        
    except (OSError, AttributeError) as e:
        logger.warning("Cannot get disk space info", error=str(e), path=directory_path)
        return {
            'total_bytes': 0,
            'available_bytes': 0,
            'free_bytes': 0,
            'used_bytes': 0,
        }


def clean_directory(directory_path: str, keep_hidden: bool = True) -> Dict[str, Any]:
    """Clean a directory by removing its contents.
    
    Args:
        directory_path: Directory to clean
        keep_hidden: Whether to keep hidden files/directories
        
    Returns:
        Dictionary with cleanup results
    """
    path = Path(directory_path)
    
    if not path.exists() or not path.is_dir():
        raise PathError(f"Invalid directory: {directory_path}")
    
    removed_files = 0
    removed_dirs = 0
    errors = []
    
    try:
        for item in path.iterdir():
            # Skip hidden files if requested
            if keep_hidden and item.name.startswith('.'):
                continue
            
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                    removed_files += 1
                elif item.is_dir():
                    import shutil
                    shutil.rmtree(item)
                    removed_dirs += 1
            except (PermissionError, OSError) as e:
                errors.append(f"Failed to remove {item}: {e}")
        
        return {
            'removed_files': removed_files,
            'removed_directories': removed_dirs,
            'errors': errors,
            'success': len(errors) == 0,
        }
        
    except PermissionError as e:
        raise PathError(f"Permission denied cleaning directory: {e}")


def get_current_working_directory() -> str:
    """Get the current working directory safely.
    
    Returns:
        Current working directory path
    """
    try:
        return str(Path.cwd().resolve())
    except OSError as e:
        raise PathError(f"Cannot determine current working directory: {e}")


def change_working_directory(directory_path: str) -> str:
    """Change the current working directory safely.
    
    Args:
        directory_path: New working directory
        
    Returns:
        Previous working directory
        
    Raises:
        PathError: If directory change fails
    """
    current_dir = get_current_working_directory()
    normalized_path = normalize_volume_path(directory_path)
    
    if not Path(normalized_path).is_dir():
        raise PathError(f"Not a directory: {normalized_path}")
    
    try:
        os.chdir(normalized_path)
        logger.debug("Changed working directory", from_dir=current_dir, to_dir=normalized_path)
        return current_dir
    except OSError as e:
        raise PathError(f"Cannot change directory to {normalized_path}: {e}")