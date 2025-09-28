# Git Repository Snapshot MCP Server

This MCP server provides tools for cloning and managing git repositories, returning structured repository snapshot data.

## Features

- **Safe Git Cloning**: Secure repository cloning with path traversal protection
- **Flexible Cloning Options**: Support for specific branches, shallow clones, and depth control
- **Structured Metadata**: Returns comprehensive repository information including commit details, tags, and file structure
- **Volume Path Management**: Organized storage under configurable volume paths
- **Multiple Transport Support**: Both STDIO and SSE (HTTP) transports

## Installation

```bash
cd servers/git-repo-snapshot
uv sync
```

## Usage

### STDIO Mode (Default)

```bash
python -m mcp_git_repo_snapshot
```

### SSE Mode (HTTP Server)

```bash
uvicorn mcp_git_repo_snapshot.transports.sse:app --host 0.0.0.0 --port 8000
```

## Tools

### clone_repo

Clone a git repository and return snapshot metadata.

**Parameters:**
- `repo_url` (string, required): Git repository URL
- `volume_path` (string, required): Volume path for storing the repository
- `branch` (string, optional): Specific branch to clone (default: repository default)
- `depth` (integer, optional): Clone depth for shallow clones (default: full clone)

**Returns:**
Repository snapshot artifact with metadata and file structure.

## Configuration

Configuration files are located in `src/mcp_git_repo_snapshot/config/`:

- `default.yaml`: Server settings, clone parameters, and allowed protocols
- `logging.yaml`: Logging configuration

## Environment Variables

- `GIT_SSH_COMMAND`: Custom SSH command for Git operations
- `HTTP_PROXY`/`HTTPS_PROXY`: Proxy settings for HTTP(S) repositories
- `MCP_TRANSPORT`: Transport mode (`stdio` or `sse`)
- `MCP_PORT`: Port for SSE mode (default: 8000)

## Security

- Path traversal protection for volume paths
- URL validation for repository URLs
- Configurable protocol allowlist
- Safe temporary directory handling