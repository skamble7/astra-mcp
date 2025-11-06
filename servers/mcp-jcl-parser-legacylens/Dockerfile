# servers/mcp-jcl-parser-legacylens/Dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps (tini optional but nice for signal handling)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tini && rm -rf /var/lib/apt/lists/*

# Copy project metadata first for efficient layer caching
COPY pyproject.toml README.md /app/

# Install deps and project (editable), using uv (no process substitution)
RUN pip install --no-cache-dir uv && uv pip install --system -e .

# Now copy the source
COPY src /app/src

# Make the src importable
ENV PYTHONPATH=/app/src

# Runtime env defaults (overridden by compose/.env)
ENV LOG_LEVEL=INFO \
    CACHE_DIR=/app/.cache \
    MCP_TRANSPORT=streamable-http \
    MCP_PORT=8876 \
    MCP_MOUNT_PATH=/mcp \
    PAGE_SIZE=100 \
    MAX_PAGE_SIZE=500 \
    WORKERS=8

# Create cache dir
RUN mkdir -p /app/.cache

EXPOSE 8876

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "mcp_jcl_parser_legacylens"]