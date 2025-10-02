FROM python:3.11-slim

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# Ensure hatchling can see README during build
COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/

# Optional extras: pass EXTRAS="sse" to install server with ASGI deps
ARG EXTRAS=""
RUN python -m pip install --upgrade pip && \
    if [ -n "$EXTRAS" ]; then \
      echo "Installing with extras: ${EXTRAS}" && pip install -e ".[${EXTRAS}]"; \
    else \
      echo "Installing base package" && pip install -e .; \
    fi

# Non-root
RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app
USER mcp

ENV PYTHONPATH=/app/src \
    MCP_TRANSPORT=sse \
    MCP_PORT=8000

EXPOSE 8000

# Health for SSE
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD [ "/bin/sh", "-c", "curl -fsS http://localhost:${MCP_PORT}/health || exit 1" ]

# Run SSE by default (stdio still available via console script)
CMD ["/bin/sh", "-lc", "exec uvicorn mcp_git_repo_snapshot.transports.sse:app --host 0.0.0.0 --port ${MCP_PORT}"]