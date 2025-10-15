FROM python:3.12-slim

WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tini && rm -rf /var/lib/apt/lists/*

# ⬇️ Copy both pyproject + README first so build backend can read the readme
COPY pyproject.toml README.md /app/

# Install deps + editable package (uses hatchling; needs README.md present)
RUN pip install --no-cache-dir uv && uv pip install --system -e .

# Now copy the source (editable install points to /app)
COPY src /app/src
ENV PYTHONPATH=/app/src

# Health/entry
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["mcp-workspace-doc-generator"]