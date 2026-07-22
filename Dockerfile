# Stage 1: Builder
FROM python:3.14-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from the committed lock file
RUN pip install --no-cache-dir poetry==2.4.1
ENV POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1
COPY pyproject.toml poetry.lock README.md ./
COPY unified_mcp/ ./unified_mcp/
RUN poetry install --only main

# Stage 2: Final
FROM python:3.14-slim-bookworm

WORKDIR /app

# Install runtime dependencies and Azure CLI
# Combine into single RUN to minimize layers and clean up effectively
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    apt-transport-https \
    lsb-release \
    gnupg \
    ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -sLS https://packages.microsoft.com/keys/microsoft.asc | \
       gpg --dearmor | \
       tee /etc/apt/keyrings/microsoft.gpg > /dev/null \
    && chmod go+r /etc/apt/keyrings/microsoft.gpg \
    && echo "deb [arch=`dpkg --print-architecture` signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ `lsb_release -cs` main" | \
       tee /etc/apt/sources.list.d/azure-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends azure-cli \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the locked application environment from builder
COPY --from=builder /app/.venv /opt/venv

# Create non-root user
RUN useradd --create-home --shell /bin/bash app \
    && mkdir -p /home/app/.azure /tmp/logs \
    && chown -R app:app /home/app/.azure /tmp/logs

# Copy application code
COPY unified_mcp/ ./unified_mcp/
COPY pyproject.toml .

# Change ownership
RUN chown -R app:app /app

USER app

# Set environment variables
ENV PYTHONPATH=/app
ENV PATH=/opt/venv/bin:$PATH
ENV LOG_LEVEL=INFO
ENV LOG_FILE=/tmp/logs/unified_mcp.log
ENV AZURE_CONFIG_DIR=/home/app/.azure
ENV MCP_TRANSPORT=stdio
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8001

# Expose the MCP port when running an HTTP transport
EXPOSE 8001

# HTTP modes expose a real readiness endpoint; stdio can only be checked locally.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD if [ "$MCP_TRANSPORT" = "stdio" ]; then python -c "import unified_mcp"; else curl --fail --silent "http://127.0.0.1:${MCP_PORT}/health" >/dev/null; fi

# Run the unified MCP server
CMD ["python", "-m", "unified_mcp.main"]
