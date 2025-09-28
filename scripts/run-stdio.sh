#!/bin/bash
set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 <server-name>"
    echo "Available servers:"
    echo "  git-repo-snapshot"
    exit 1
fi

SERVER_NAME="$1"
SERVER_PATH="servers/${SERVER_NAME}"

if [ ! -d "$SERVER_PATH" ]; then
    echo "❌ Server '${SERVER_NAME}' not found in ${SERVER_PATH}"
    exit 1
fi

echo "🚀 Starting ${SERVER_NAME} server in STDIO mode..."

# Change to server directory
cd "$SERVER_PATH"

# Run the server in STDIO mode
exec uv run python -m "mcp_${SERVER_NAME//-/_}"