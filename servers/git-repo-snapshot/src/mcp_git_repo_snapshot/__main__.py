from __future__ import annotations
import sys
from .server import mcp

def main() -> None:
    print(">>> starting git-repo-snapshot MCP server (stdio)…", file=sys.stderr, flush=True)
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()