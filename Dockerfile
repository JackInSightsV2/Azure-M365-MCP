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

# Install the Secret Service stack so the device-code token cache is encrypted at
# rest instead of stored in plaintext. PyGObject is what lets azure-identity's
# msal-extensions talk to libsecret; gnome-keyring provides the Secret Service and
# dbus its session bus. Build tools for PyGObject are removed after the wheel builds.
# PyGObject is pinned to the last release that targets gobject-introspection 1.x,
# which is what Debian bookworm ships.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsecret-1-0 \
    gir1.2-secret-1 \
    gir1.2-glib-2.0 \
    libgirepository-1.0-1 \
    libcairo2 \
    gnome-keyring \
    dbus \
    dbus-x11 \
    && apt-get install -y --no-install-recommends \
    gcc \
    pkg-config \
    libgirepository1.0-dev \
    libcairo2-dev \
    && python -m pip install --no-cache-dir "PyGObject==3.48.2" \
    && apt-get purge -y gcc pkg-config libgirepository1.0-dev libcairo2-dev \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install the server with standard Python packaging.
COPY pyproject.toml README.md LICENSE ./
COPY unified_mcp/ ./unified_mcp/
RUN python -m pip install --no-cache-dir .

# Entrypoint brings up the keyring (best effort) before running the server.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Run without root privileges and keep Azure CLI state and the device-code sign-in
# cache in mountable locations.
RUN useradd --create-home --shell /bin/bash app \
    && mkdir -p /home/app/.azure /home/app/.IdentityService/xdg-data/keyrings /tmp/logs \
    && chown -R app:app /home/app/.azure /home/app/.IdentityService /tmp/logs /app

USER app

ENV LOG_LEVEL=INFO \
    LOG_FILE=/tmp/logs/unified_mcp.log \
    AZURE_CONFIG_DIR=/home/app/.azure \
    XDG_RUNTIME_DIR=/tmp/runtime-app \
    XDG_DATA_HOME=/home/app/.IdentityService/xdg-data \
    ENABLE_KEYRING=true \
    SIGN_IN_FLOW=device_code \
    MCP_TRANSPORT=stdio \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8001

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD if [ "$MCP_TRANSPORT" = "stdio" ]; then python -c "import unified_mcp"; else curl --fail --silent "http://127.0.0.1:${MCP_PORT}/health" >/dev/null; fi

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["unified-microsoft-mcp"]
