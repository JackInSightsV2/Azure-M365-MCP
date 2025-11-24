# Unified Microsoft MCP Server - Combines Azure CLI and Microsoft Graph API
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    apt-transport-https \
    lsb-release \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Azure CLI
RUN curl -sLS https://packages.microsoft.com/keys/microsoft.asc | \
    gpg --dearmor | \
    tee /etc/apt/trusted.gpg.d/microsoft.gpg > /dev/null && \
    AZ_REPO=$(lsb_release -cs) && \
    echo "deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ $AZ_REPO main" | \
    tee /etc/apt/sources.list.d/azure-cli.list && \
    apt-get update && \
    apt-get install -y azure-cli && \
    rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user
RUN useradd --create-home --shell /bin/bash app

# Copy the application
COPY unified_mcp/ ./unified_mcp/
COPY pyproject.toml .

# Change ownership of /app to the app user AFTER copying files
RUN chown -R app:app /app

USER app

# Set environment variables
ENV PYTHONPATH=/app
ENV LOG_LEVEL=INFO
ENV LOG_FILE=/tmp/unified_mcp.log
ENV MCP_TRANSPORT=stdio
ENV MCP_PORT=8000

# Expose the MCP port (if running in SSE mode)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import unified_mcp; print('OK')" || exit 1

# MCP server uses stdio transport, no port needed

# Run the unified MCP server
CMD ["python", "-m", "unified_mcp.main"] 