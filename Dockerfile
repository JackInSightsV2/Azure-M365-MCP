FROM python:3.14-slim-bookworm

WORKDIR /app

# Install Azure CLI and the small set of system packages it requires.
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

# Install the server with standard Python packaging.
COPY pyproject.toml README.md LICENSE ./
COPY unified_mcp/ ./unified_mcp/
RUN python -m pip install --no-cache-dir .

# Run without root privileges and keep Azure CLI state in a mountable location.
RUN useradd --create-home --shell /bin/bash app \
    && mkdir -p /home/app/.azure /tmp/logs \
    && chown -R app:app /home/app/.azure /tmp/logs /app

USER app

ENV LOG_LEVEL=INFO \
    LOG_FILE=/tmp/logs/unified_mcp.log \
    AZURE_CONFIG_DIR=/home/app/.azure \
    MCP_TRANSPORT=stdio \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8001

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD if [ "$MCP_TRANSPORT" = "stdio" ]; then python -c "import unified_mcp"; else curl --fail --silent "http://127.0.0.1:${MCP_PORT}/health" >/dev/null; fi

CMD ["unified-microsoft-mcp"]
