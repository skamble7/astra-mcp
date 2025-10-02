# File: servers/git-repo-snapshot/src/mcp_git_repo_snapshot/__main__.py
from __future__ import annotations
import os
import sys
from .server import mcp

def main() -> None:
    # Helpful banner to stderr; do NOT write to stdout in stdio mode
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        sys.stderr.write("mcp-git-repo-snapshot: starts an MCP stdio server.\n")
        sys.stderr.flush()
        return

    os.environ.setdefault("MCP_TRANSPORT", "stdio")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()