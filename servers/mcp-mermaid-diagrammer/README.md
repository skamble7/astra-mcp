FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Project metadata & source
COPY pyproject.toml ./
# (Don't copy README.md; it's optional and often missing)
COPY src/ ./src/

# Install
RUN python -m pip install --upgrade pip && \
    pip install -e .

# Non-root user
RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app
USER mcp

# Do not bake a fixed port into the image; let docker-compose provide it.
ENV PYTHONPATH=/app/src \
    MCP_HOST=0.0.0.0 \
    MCP_TRANSPORT=streamable-http \
    MCP_MOUNT_PATH=/mcp \
    LOG_LEVEL=INFO

# This is just metadata; compose will bind to whatever MCP_PORT you set.
EXPOSE 8766

CMD ["/bin/sh", "-lc", "exec python -m mcp_mermaid_diagrammer"]
