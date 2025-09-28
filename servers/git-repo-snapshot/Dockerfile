FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY pyproject.toml ./
RUN pip install -e .[sse]

# Copy source code
COPY src/ ./src/
COPY .env.example ./.env

# Create non-root user
RUN useradd -m -u 1000 mcp && chown -R mcp:mcp /app
USER mcp

# Expose port for SSE mode
EXPOSE 8000

# Set environment variables
ENV MCP_TRANSPORT=sse
ENV MCP_PORT=8000
ENV PYTHONPATH=/app/src

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the server
CMD ["uvicorn", "mcp_git_repo_snapshot.transports.sse:app", "--host", "0.0.0.0", "--port", "8000"]