#!/bin/bash
set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 <server-name> [port]"
    echo "Available servers:"
    echo "  git-repo-snapshot"
    exit 1
fi

SERVER_NAME="$1"
PORT="${2:-8000}"
SERVER_PATH="servers/${SERVER_NAME}"

if [ ! -d "$SERVER_PATH" ]; then
    echo "❌ Server '${SERVER_NAME}' not found in ${SERVER_PATH}"
    exit 1
fi

echo "🚀 Starting ${SERVER_NAME} server in SSE mode on port ${PORT}..."

# Change to server directory
cd "$SERVER_PATH"

# Check if SSE transport is available
SSE_MODULE="src/mcp_${SERVER_NAME//-/_}/transports/sse.py"
if [ ! -f "$SSE_MODULE" ]; then
    echo "❌ SSE transport not implemented for ${SERVER_NAME}"
    echo "   Missing: ${SSE_MODULE}"
    exit 1
fi

# Run the server in SSE mode using uvicorn
export MCP_TRANSPORT=sse
export MCP_PORT="$PORT"

exec uv run uvicorn "mcp_${SERVER_NAME//-/_}.transports.sse:app" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --log-level info \
    --reload