FROM python:3.11-slim

# (Add any system deps you need for your engine)
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/

# If you sometimes build with extras, keep ARG like your other image
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
    MCP_PORT=8001 \
    MCP_TRANSPORT=streamable-http \
    LOG_LEVEL=INFO

EXPOSE 8001

# No healthcheck here (streamable-http doesn't expose GET /health)
# If you want one, you can POST a short initialize with curl and timeout.

# Start exactly like your working server:
CMD ["/bin/sh", "-lc", "exec python -m mcp_mermaid_diagrammer"]