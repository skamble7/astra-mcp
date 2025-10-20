FROM python:3.12-slim

WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tini && rm -rf /var/lib/apt/lists/*

# Copy project metadata first for efficient layer caching
COPY pyproject.toml README.md /app/

# Install deps and project (editable)
RUN pip install --no-cache-dir uv && uv pip install --system -e .

# Copy source
COPY src /app/src
ENV PYTHONPATH=/app/src

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["mcp-raina-input-fetcher"]