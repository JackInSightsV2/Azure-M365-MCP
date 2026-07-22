# Unified Microsoft MCP Server

An MCP server that exposes Azure CLI commands and Microsoft Graph requests through one process. It supports local stdio clients, MCP Streamable HTTP, the legacy MCP SSE transport, and a small OpenAPI interface.

The server executes Azure CLI arguments without invoking a shell, limits concurrent work, applies operation timeouts, pools Graph HTTP connections, retries Graph throttling responses, and can protect every non-health HTTP endpoint with a bearer token.

## Use with an IDE

The IDE starts and stops the server automatically over stdio. You do not run a separate server.

The simplest setup uses the published Docker image, which already contains Python, the server, and Azure CLI:

```json
{
  "mcpServers": {
    "unified-microsoft": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "unified-microsoft-mcp-azure:/home/app/.azure",
        "ghcr.io/jackinsightsv2/azure-m365-mcp:latest"
      ]
    }
  }
}
```

Docker creates the named volume automatically so Azure CLI sign-in survives server restarts. For the exact Cursor, Antigravity, OpenCode, and Codex configuration locations, see [MCP client setup](docs/client-setup.md).

To run without Docker, install Python 3.11–3.14 and Azure CLI, then install the package:

```bash
python -m pip install .
```

Use `"command": "unified-microsoft-mcp"` in the client configuration. The client still manages the process.

## Tools

`execute_azure_cli_command` accepts a command whose first parsed argument must be exactly `az`:

```text
az account show
az group list
az vm list --resource-group example-rg
```

`graph_command` accepts a Microsoft Graph v1.0-relative path, an HTTP method, and an optional JSON object:

```text
command: me
method: GET

command: users
method: GET

command: groups/{id}
method: PATCH
data: {"displayName": "New name"}
```

Graph access is governed by the identity's configured permissions. The default delegated scopes are read-only; write operations require a custom application or managed identity with explicit application permissions.

## Execution policy

`EXECUTION_POLICY` adds an application-level guard before authentication or external execution:

| Mode | Behavior |
| --- | --- |
| `unrestricted` | Compatibility default; permits every validated Azure CLI and Graph operation |
| `read-only` | Permits recognized Azure read commands and Graph `GET`; blocks `az rest` |
| `allowlist` | Permits only token-safe Azure prefixes and Graph method/path prefixes |

For an allowlist deployment, configure comma-separated entries:

```dotenv
EXECUTION_POLICY=allowlist
AZURE_COMMAND_ALLOWLIST=az account show,az group list,az vm list
GRAPH_REQUEST_ALLOWLIST=GET /me,GET /users,GET /groups
```

Azure allowlist entries match parsed argument prefixes, not raw strings. Graph entries include the method and path; `GET /users` also permits descendants such as `GET /users/{id}`, but not `/users-internal`. Use `read-only` or a narrow allowlist for remote HTTP deployments. Azure RBAC and Graph permissions remain the final authorization boundaries.

## Authentication

Choose one approach:

1. Local interactive authentication: use `stdio`, run `az login` through the Azure tool, and let Graph prompt with device-code authentication. This requires no stored client secret.
2. Managed identity: for an Azure-hosted workload, set `USE_MANAGED_IDENTITY=true`. Set `MANAGED_IDENTITY_CLIENT_ID` only for a user-assigned identity. Assign the identity appropriate Azure RBAC roles and Microsoft Graph application permissions.
3. Service principals: configure the `AZURE_APP_*` variables for Azure CLI and the `GRAPH_APP_*` variables for Graph. Set `SHARE_APP_REGISTRATION=true` to reuse one application registration.

Never put client secrets in tool arguments. Supply them through environment variables or your platform's secret store. See [env.example](env.example) for all supported settings.

## Transports

| Transport | Setting | Endpoint | Intended use |
| --- | --- | --- | --- |
| stdio | `MCP_TRANSPORT=stdio` | process streams | Local MCP clients; safest default |
| Streamable HTTP | `MCP_TRANSPORT=streamable-http` | `/mcp` | Current remote MCP transport |
| SSE | `MCP_TRANSPORT=sse` | `/sse` | Legacy client compatibility |
| OpenAPI | `MCP_TRANSPORT=openapi` | `/docs` | Direct REST integration |

HTTP transports bind to `127.0.0.1` by default. To listen on another interface, explicitly set `MCP_HOST`; containers set this to `0.0.0.0` internally while Compose publishes only to host loopback.

For any HTTP deployment, set a long random `MCP_API_KEY` and send it as a bearer token:

```bash
export MCP_TRANSPORT=streamable-http
export MCP_API_KEY="$(openssl rand -hex 32)"
unified-microsoft-mcp
```

```text
Authorization: Bearer <MCP_API_KEY>
```

`CORS_ALLOWED_ORIGINS` is a comma-separated browser origin allowlist. It protects browser-originated requests but is not authentication. `/health` remains public for readiness checks. In OpenAPI mode, `/docs`, `/redoc`, and `/openapi.json` are public, while execution endpoints require the bearer token when configured.

## Docker

Build and run directly:

```bash
docker build -t unified-microsoft-mcp .
docker run --rm -i \
  -e MCP_TRANSPORT=stdio \
  unified-microsoft-mcp
```

Run Streamable HTTP with Compose:

```bash
cp env.example .env
# Edit .env: set MCP_TRANSPORT=streamable-http, MCP_API_KEY, and authentication.
docker compose up --build -d
curl http://127.0.0.1:8001/health
```

The image runs as a non-root user. Azure CLI state is stored in `/home/app/.azure`, logs in `/tmp/logs`, and the Compose file persists both appropriately. Avoid exposing port 8001 publicly without TLS and an upstream access-control layer.

Published images use:

```bash
docker pull ghcr.io/jackinsightsv2/azure-m365-mcp:latest
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
black --check unified_mcp tests
ruff check unified_mcp tests
mypy unified_mcp
pytest -m "not docker" --cov=unified_mcp
```

Docker integration tests use mock mode and do not require Azure credentials:

```bash
pytest -m docker
```

Mock mode is test-only and must not be used in a real deployment.

## Operational notes

- `COMMAND_TIMEOUT` and `MAX_CONCURRENT_COMMANDS` bound Azure CLI execution.
- `OPERATION_TIMEOUT` and `MAX_CONCURRENT_OPERATIONS` bound Graph calls.
- Graph `429` responses are retried up to three attempts, honoring `Retry-After` up to 30 seconds.
- Sensitive Azure CLI flag values such as passwords, secrets, and API keys are redacted from diagnostic logs.
- The server validates that Azure commands begin with `az`; Azure RBAC remains the real authorization boundary.
- Configured managed-identity or service-principal login must succeed before an Azure command runs; failed configured authentication never falls through to a cached CLI identity.

See [SECURITY.md](SECURITY.md) for vulnerability reporting and deployment guidance. This project is licensed under the [MIT License](LICENSE).
