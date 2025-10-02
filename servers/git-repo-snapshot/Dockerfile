# servers/git-repo-snapshot/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY pyproject.toml ./
# install base (stdio) and optionally sse extras
ARG EXTRAS=""
RUN pip install -e .${EXTRAS:+[${EXTRAS}]}

COPY src/ ./src/
COPY .env.example ./.env

# non-root
RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app
USER mcp

ENV PYTHONPATH=/app/src
ENV MCP_TRANSPORT=stdio
ENV MCP_PORT=8000

EXPOSE 8000

# Healthcheck only makes sense in SSE mode; keep it but don’t break stdio
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD [ "/bin/sh", "-c", "[ \"$MCP_TRANSPORT\" = \"sse\" ] && curl -fsS http://localhost:${MCP_PORT}/health || exit 0" ]

# Switch on transport at runtime
CMD ["/bin/sh", "-lc", "\
  if [ \"$MCP_TRANSPORT\" = \"sse\" ]; then \
    exec uvicorn mcp_git_repo_snapshot.transports.sse:app --host 0.0.0.0 --port ${MCP_PORT}; \
  else \
    exec mcp-git-repo-snapshot; \
  fi"]