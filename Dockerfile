# Stage 1: Builder
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Final
FROM python:3.11-slim-bookworm

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

# Copy installed python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN useradd --create-home --shell /bin/bash app \
    && mkdir -p /tmp/.azure \
    && chown -R app:app /tmp/.azure

# Copy application code
COPY unified_mcp/ ./unified_mcp/
COPY pyproject.toml .

# Change ownership
RUN chown -R app:app /app

USER app

# Set environment variables
ENV PYTHONPATH=/app
ENV LOG_LEVEL=INFO
ENV LOG_FILE=/tmp/unified_mcp.log
ENV AZURE_CONFIG_DIR=/tmp/.azure
ENV MCP_TRANSPORT=stdio
ENV MCP_PORT=8001

# Expose the MCP port (if running in SSE mode)
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import unified_mcp; print('OK')" || exit 1

# Run the unified MCP server
CMD ["python", "-m", "unified_mcp.main"]
