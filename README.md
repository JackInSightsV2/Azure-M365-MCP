# Unified Microsoft MCP Server

Connect an AI assistant such as Cursor, Google Antigravity, OpenCode, or OpenAI Codex to Microsoft Azure and Microsoft 365.

The assistant can use your existing access to investigate issues, collect information, and—if you allow it—make changes. It cannot grant itself extra permissions.

## What problem does this solve?

Support engineers often need to move between the Azure portal, Microsoft 365 admin centres, Microsoft Graph, and command-line tools to answer one ticket. That takes time and requires knowing where Microsoft has placed each setting.

This server gives a supported AI client two controlled tools—one for Azure and one for Microsoft 365. You can describe the task in plain English, and the assistant uses those tools to gather the information available to your signed-in account.

For example, instead of finding and combining several portal pages, you can ask:

> Show me the user account, group memberships, assigned licences, and managed devices for user@example.com.

The AI client decides which tool calls are needed, the MCP server validates and runs them, and Microsoft still enforces your normal permissions. You remain responsible for checking the result before acting on it.

## Who is this for?

This project is designed for people such as:

- first- and second-line helpdesk engineers;
- Microsoft 365 and Azure support teams;
- system administrators;
- developers and automation engineers.

You do not need to know Python or run the server manually. Your AI client starts and stops it automatically.

You should be comfortable copying a configuration block into the file used by your AI client. The steps below show the exact file and content.

## What can I ask it?

Examples include:

- “Which Azure subscription am I connected to?”
- “List the resource groups and show me which region each uses.”
- “Show the virtual machines in the Finance resource group.”
- “List Microsoft 365 users with their job titles.”
- “Find the details for user@example.com.”
- “List Entra ID groups.”
- “Show the managed devices in Intune.”

The available results depend on the permissions of the account that signs in.

## Before you start

You need:

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
2. A supported AI client: Cursor, Antigravity, OpenCode, or Codex.
3. An Azure or Microsoft 365 account with permission to view or manage the information you need.

The Docker image already contains the server, Python, and Azure CLI.

## Quick start

### 1. Add the server to your AI client

Choose your client below. The examples are complete configurations for a new file:

| Client | Where to put the configuration |
| --- | --- |
| Cursor | [`.cursor/mcp.json` or `~/.cursor/mcp.json`](docs/client-setup.md#cursor) |
| Google Antigravity | [`.agents/mcp_config.json` or `~/.gemini/config/mcp_config.json`](docs/client-setup.md#google-antigravity) |
| OpenCode | [`opencode.json`](docs/client-setup.md#opencode) |
| OpenAI Codex | [`~/.codex/config.toml` or `.codex/config.toml`](docs/client-setup.md#openai-codex) |

`~` means your user home folder—for example, `C:\Users\your-name` on Windows. A project file enables the server only in that project; a file in your home folder makes it available globally.

If the file already contains other settings or MCP servers, do not overwrite it. Add the `unified-microsoft` entry alongside the existing content, or make a backup before editing.

<details>
<summary><strong>Cursor configuration</strong></summary>

Save as `.cursor/mcp.json` in a project or `~/.cursor/mcp.json` globally:

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

</details>

<details>
<summary><strong>Google Antigravity configuration</strong></summary>

Save as `.agents/mcp_config.json` in a workspace or `~/.gemini/config/mcp_config.json` globally:

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

</details>

<details>
<summary><strong>OpenCode configuration</strong></summary>

Add to `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "unified-microsoft": {
      "type": "local",
      "command": [
        "docker", "run", "--rm", "-i",
        "-v", "unified-microsoft-mcp-azure:/home/app/.azure",
        "ghcr.io/jackinsightsv2/azure-m365-mcp:latest"
      ],
      "enabled": true
    }
  }
}
```

</details>

<details>
<summary><strong>OpenAI Codex configuration</strong></summary>

Add to `~/.codex/config.toml` or `.codex/config.toml` in a trusted project:

```toml
[mcp_servers.unified_microsoft]
command = "docker"
args = [
  "run", "--rm", "-i",
  "-v", "unified-microsoft-mcp-azure:/home/app/.azure",
  "ghcr.io/jackinsightsv2/azure-m365-mcp:latest"
]
```

</details>

The configuration tells the client to run:

```text
docker run --rm -i -v unified-microsoft-mcp-azure:/home/app/.azure ghcr.io/jackinsightsv2/azure-m365-mcp:latest
```

You do not run that command separately. The AI client runs it when required.

### 2. Restart your AI client

Restart the client after saving its configuration. It should discover these two tools:

- `execute_azure_cli_command` for Azure;
- `graph_command` for Microsoft 365 and Microsoft Graph.

Your client may ask you to approve a tool before it runs. That approval prompt is controlled by the client, not this server.

### 3. Sign in

Ask the assistant:

> Sign me in to Azure using the Azure CLI tool.

The assistant will return a web address and device code. Open the address, enter the code, and complete sign-in. Then retry your original request.

Microsoft Graph may request a separate device-code sign-in the first time it is used. This is normal.

The Docker configuration uses a named volume so Azure CLI sign-in survives restarts.

### 4. Try a read-only request

Ask:

> Show my current Azure account and subscription.

or:

> Use Microsoft Graph to show my profile.

## Execution policy: an optional safety switch

Execution policy controls what the MCP server will let the assistant attempt. It is an extra safety layer on top of Azure roles and Microsoft Graph permissions.

You do not need to configure it just to use the server. Most desktop AI clients can already ask you to approve individual tool calls. Use an execution policy when you also want a fixed server-side rule—for example, when a support role must never make changes even if someone approves the wrong tool call.

### Which policy should I use?

| Your situation | Recommended policy | What it means |
| --- | --- | --- |
| You need the assistant to investigate and make changes | `unrestricted` | Allows all supported commands. This is the default. |
| You only investigate incidents or collect information | `read-only` | Allows recognised Azure read commands and Graph `GET` requests. Blocks changes. |
| A shared workflow should run only a few approved commands | `allowlist` | Blocks everything except the command prefixes you specify. |

If you do not set anything, the server uses `unrestricted` so existing functionality continues to work.

For a first-line support role that only gathers information, `read-only` is the safer choice. A second-line engineer who is expected to restart, create, update, or delete resources will need `unrestricted` or a suitable allowlist.

### Where do I set it?

For the recommended Docker-based IDE setup, put it inside the Docker `args` or `command` list in your MCP client configuration.

Add these two entries after `"-i"`:

```json
"-e", "EXECUTION_POLICY=read-only",
```

For example:

```json
"args": [
  "run", "--rm", "-i",
  "-e", "EXECUTION_POLICY=read-only",
  "-v", "unified-microsoft-mcp-azure:/home/app/.azure",
  "ghcr.io/jackinsightsv2/azure-m365-mcp:latest"
]
```

This placement works in the Cursor and Antigravity `args` arrays, the OpenCode `command` array, and the Codex `args` array. See [client setup](docs/client-setup.md#optional-limit-what-the-assistant-can-do) for complete examples.

If you start the server with Docker Compose, copy `env.example` to `.env` and set:

```dotenv
EXECUTION_POLICY=read-only
```

If you run the installed executable directly, set the variable in the MCP client’s environment section or before starting the server:

```bash
export EXECUTION_POLICY=read-only
unified-microsoft-mcp
```

### How do I use an allowlist?

Use an allowlist only when you know the exact operations a role or workflow requires. Set all three variables:

```dotenv
EXECUTION_POLICY=allowlist
AZURE_COMMAND_ALLOWLIST=az login,az account show,az group list,az vm list
GRAPH_REQUEST_ALLOWLIST=GET /me,GET /users,GET /groups
```

In a Docker-based client configuration, pass them as Docker environment arguments:

```json
"-e", "EXECUTION_POLICY=allowlist",
"-e", "AZURE_COMMAND_ALLOWLIST=az login,az account show,az group list,az vm list",
"-e", "GRAPH_REQUEST_ALLOWLIST=GET /me,GET /users,GET /groups",
```

`GET /users` also permits a specific user path such as `GET /users/{id}`. It does not permit a different path such as `/users-internal`.

Include `az login` when allowlisted desktop users need to sign in interactively.
Azure entries match the beginning of the parsed command, so `az vm list` also permits options such as `az vm list --resource-group Finance`.

Execution policy can only reduce access. Azure RBAC and Microsoft Graph permissions still decide what the signed-in account can actually do.

## Sign-in and permissions

### Normal desktop use

Use device-code sign-in. No client secret is required. The server provides a code and Microsoft sign-in address when authentication is needed.

Never paste passwords, client secrets, API keys, or access tokens into an AI chat or tool command.

### Unattended or shared server

Administrators can configure managed identity or a service principal through environment variables. See [env.example](env.example). These options are intended for managed deployments, not normal desktop setup.

The server stops an Azure command if the configured managed identity or service-principal sign-in fails. It will not silently use a different cached identity.

## Troubleshooting

### The client says `docker` was not found

Install Docker Desktop, start it, and confirm this works in a terminal:

```bash
docker version
```

### The tools do not appear

Check that the configuration file is in the correct location and contains valid JSON or TOML. Restart the AI client after changing it.

### I received a device code

Open the supplied Microsoft sign-in address, enter the code, finish sign-in, and retry the request. Azure and Microsoft Graph may each request sign-in.

### I received `AuthorizationFailed`, `Forbidden`, or `Insufficient privileges`

The signed-in account does not have permission for that operation. Ask an Azure or Microsoft 365 administrator to confirm the account’s role or Graph permissions. Changing execution policy cannot add permission.

### I received `Execution policy denied...`

The server’s safety policy blocked the operation. Use a read-only command, add the required command to the allowlist, or—only when the role is expected to make changes—use `unrestricted`.

### I am seeing an older version

Pull the latest image and restart the AI client:

```bash
docker pull ghcr.io/jackinsightsv2/azure-m365-mcp:latest
```

## Technical reference

### Tools

`execute_azure_cli_command` accepts an Azure CLI command beginning with `az`, for example:

```text
az account show
az group list
az vm list --resource-group example-rg
```

`graph_command` accepts a Microsoft Graph v1.0 path, an HTTP method, and an optional JSON body:

```text
command: users
method: GET

command: groups/{id}
method: PATCH
data: {"displayName": "New name"}
```

Graph writes require an application or managed identity with the necessary Microsoft Graph application permissions.

### Transport options

| Transport | Setting | Endpoint | Use |
| --- | --- | --- | --- |
| stdio | `MCP_TRANSPORT=stdio` | process input/output | Normal local IDE use; default |
| Streamable HTTP | `MCP_TRANSPORT=streamable-http` | `/mcp` | Shared or remote MCP server |
| SSE | `MCP_TRANSPORT=sse` | `/sse` | Compatibility with older clients |
| OpenAPI | `MCP_TRANSPORT=openapi` | `/docs` | Direct REST integrations |

For HTTP deployments, set `MCP_API_KEY`, use TLS, and place the server behind network access controls. The built-in server binds to `127.0.0.1` by default.

### Run without Docker

Install Python 3.11–3.14 and Azure CLI, then install the package:

```bash
python -m pip install .
```

Configure the MCP client to launch `unified-microsoft-mcp` directly.

### Docker Compose

```bash
cp env.example .env
docker compose up --build -d
curl http://127.0.0.1:8001/health
```

### Development

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

## Security and licensing

See [SECURITY.md](SECURITY.md) for vulnerability reporting and deployment guidance. This project is licensed under the [MIT License](LICENSE).
