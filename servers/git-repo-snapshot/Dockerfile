FROM python:3.11-slim

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/

ARG EXTRAS=""
RUN python -m pip install --upgrade pip && \
    if [ -n "$EXTRAS" ]; then \
      echo "Installing with extras: ${EXTRAS}" && pip install -e ".[${EXTRAS}]"; \
    else \
      echo "Installing base package" && pip install -e .; \
    fi

RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app
USER mcp

ENV PYTHONPATH=/app/src \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_TRANSPORT=streamable-http

EXPOSE 8000

# NOTE: streamable-http doesn't expose a GET /health by default; remove the healthcheck.
# If you need a healthcheck, use curl to POST initialize with a short timeout.

CMD ["/bin/sh", "-lc", "exec python -m mcp_git_repo_snapshot"]