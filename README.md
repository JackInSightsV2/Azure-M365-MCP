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
- “Connect to the aks-prod cluster and list the pods that are not running.”

The available results depend on the permissions of the account that signs in.

## Before you start

You need:

1. [uv](https://docs.astral.sh/uv/) installed. The client starts the server with `uvx`, which fetches it and its Python dependencies on first use.
2. A supported AI client: Claude Code, Claude Desktop, VS Code, Cursor, Antigravity, OpenCode, or Codex.
3. An Azure or Microsoft 365 account with permission to view or manage the information you need.
4. Optional: the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli). Without it, the Azure tools use the Azure Resource Manager REST API instead.

For the optional [Kubernetes (AKS) tools](#kubernetes-aks), run the server on your desktop with `uvx` (the plugin and the installer do). Nothing else needs installing: the server includes the Azure CLI, and the first AKS use downloads `kubectl` and `kubelogin` with Microsoft's `az aks install-cli`.

## Claude Code plugin

In Claude Code, add this repository as a plugin marketplace and install the plugin:

```text
/plugin marketplace add JackInSightsV2/Azure-M365-MCP
/plugin install azure-m365@azure-m365-mcp
```

The plugin provides the `azure-m365` server (started with `uvx`, so the machine needs [uv](https://docs.astral.sh/uv/)) two skills, and an agent:

- `/azure-m365:setup` completes an Interactive sign-in and checks the connection with a `me` read and `az account show`.
- `microsoft-cloud` gives the assistant common Microsoft Graph and Azure paths so calls are right first time. It loads automatically when relevant.
- `tenant-verifier` (the Verifier) has Read tools only. Before a write to Azure or to users, groups, or licences it runs a What-if (native ARM What-if for Azure deployments, otherwise a diff of the current state against the planned change) and gives a GO / CHECK verdict; afterwards it re-reads the target and confirms the change landed. The `microsoft-cloud` skill calls it around those writes, not around mail or other low-risk writes. Ask for it any time with `@agent-azure-m365:tenant-verifier`.

Other clients do not support plugins; use the installer below.

## Install with one command

If you have [uv](https://docs.astral.sh/uv/) installed, one command adds the server to your client's configuration. Nothing else needs installing first:

```bash
uvx --from git+https://github.com/JackInSightsV2/Azure-M365-MCP unified-microsoft-mcp install --client cursor
```

Replace `cursor` with your client. The entry is named `azure-m365`.

| `--client` | Default file written | `--scope user` writes |
| --- | --- | --- |
| `claude-code` | `.mcp.json` in the current directory | `~/.claude.json` |
| `vscode` | `.vscode/mcp.json` in the current directory | your VS Code user profile's `mcp.json` |
| `cursor` | `.cursor/mcp.json` in the current directory | `~/.cursor/mcp.json` |
| `codex` | `~/.codex/config.toml` | (default) |
| `claude-desktop` | `claude_desktop_config.json` in `~/Library/Application Support/Claude` (macOS), `%APPDATA%\Claude` (Windows), or `~/.config/Claude` (Linux) | (default) |

- The installer adds the entry to the existing file and leaves your other settings and MCP servers as they are. It is safe to run again: an up-to-date entry is left alone, and an older one is replaced.
- `--scope project|user` picks between the current project and your whole user account. `--dir <path>` uses a different project or home folder.
- By default the client starts the server with `uvx`, so the machine needs only `uv`. The server includes the Azure CLI (an `az` already on your `PATH` is used first); the first start downloads it with the server, about 350 MB, so it can take a minute.
- If the file is not plain JSON (for example, it contains comments), the installer stops without changing it. Add the entry by hand in that case.

Restart your client afterwards, then continue from [Sign in](#3-sign-in).

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
      "command": "uvx",
      "args": ["--from", "git+https://github.com/JackInSightsV2/Azure-M365-MCP", "unified-microsoft-mcp"]
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
      "command": "uvx",
      "args": ["--from", "git+https://github.com/JackInSightsV2/Azure-M365-MCP", "unified-microsoft-mcp"]
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
      "command": ["uvx", "--from", "git+https://github.com/JackInSightsV2/Azure-M365-MCP", "unified-microsoft-mcp"],
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
command = "uvx"
args = ["--from", "git+https://github.com/JackInSightsV2/Azure-M365-MCP", "unified-microsoft-mcp"]
```

</details>

The configuration tells the client to run:

```text
uvx --from git+https://github.com/JackInSightsV2/Azure-M365-MCP unified-microsoft-mcp
```

You do not run that command separately. The AI client runs it when required.

### 2. Restart your AI client

Restart the client after saving its configuration. It should discover these tools:

- `azure_read` to look up Azure resources and `azure_write` to change them;
- `azure_find_resource` to find which subscription and resource group an Azure resource is in (needs the opt-in [Resource inventory](#resource-inventory-opt-in));
- `microsoft365_read` to read Microsoft 365 and Entra ID through Microsoft Graph (read-only);
- `microsoft365_write` to change Microsoft 365 and Entra ID through Microsoft Graph (your client should ask before each call).

Your client may ask you to approve a tool before it runs. That approval prompt is controlled by the client, not this server.

### 3. Sign in

Ask the assistant:

> Sign me in to Azure.

A browser window opens for Microsoft sign-in, the same as `az login` or `Connect-AzAccount`. Complete sign-in, then retry your original request.

Microsoft Graph and Azure sign in separately, so a second browser window may open the first time you use the other. This is normal. On a machine without a browser (for example over SSH), the assistant returns a web address and device code instead; see [Sign-in and permissions](#sign-in-and-permissions).

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

Set it in the `env` block of the server entry in your MCP client configuration:

```json
"env": {
  "EXECUTION_POLICY": "read-only"
}
```

OpenCode calls this block `environment`; Codex uses a `[mcp_servers.<name>.env]` table. See [client setup](docs/client-setup.md#optional-limit-what-the-assistant-can-do) for complete examples.

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

In an MCP client configuration, put them in the server entry's `env` block:

```json
"env": {
  "EXECUTION_POLICY": "allowlist",
  "AZURE_COMMAND_ALLOWLIST": "az login,az account show,az group list,az vm list",
  "GRAPH_REQUEST_ALLOWLIST": "GET /me,GET /users,GET /groups"
}
```

`GET /users` also permits a specific user path such as `GET /users/{id}`. It does not permit a different path such as `/users-internal`.

Include `az login` when allowlisted desktop users need to sign in interactively.
Azure entries match the beginning of the parsed command, so `az vm list` also permits options such as `az vm list --resource-group Finance`.

Execution policy can only reduce access. Azure RBAC and Microsoft Graph permissions still decide what the signed-in account can actually do.

## Sign-in and permissions

### Normal desktop use

Sign-in opens a browser window, like `az login` or `Connect-AzAccount`. No client secret is required. Microsoft Graph signs in as Microsoft Graph Command Line Tools (the app `Connect-MgGraph` uses) and Azure as Azure PowerShell (the app `Connect-AzAccount` uses).

Set `SIGN_IN_FLOW=device_code` on a host without a browser (for example SSH sessions); the server then returns a code and sign-in address instead.

### Microsoft Graph permissions

By default the server asks Microsoft Graph only for the permissions your Tenant has already granted to Microsoft Graph Command Line Tools (`https://graph.microsoft.com/.default`), so no consent prompt appears. A request that needs a permission not yet granted returns `403` with a suggestion naming what to do.

To sign in with more permissions, set `GRAPH_SCOPES` to a comma-separated list, for example:

```text
GRAPH_SCOPES=https://graph.microsoft.com/Mail.Read,https://graph.microsoft.com/Group.ReadWrite.All
```

A consent prompt then appears for any permission not yet granted. If your Tenant does not let users consent, an admin must approve it; the server never works around that.

Never paste passwords, client secrets, API keys, or access tokens into an AI chat or tool command.

### Signing in only once

The sign-in is cached, so after the first sign-in the server refreshes access silently instead of prompting again. Tokens are stored in the operating system's credential store (Keychain on macOS, DPAPI on Windows, Secret Service on Linux) and fall back to a plaintext file only where none is available. The sign-in record lives in `TOKEN_CACHE_DIR` (default `~/.IdentityService`). Set `GRAPH_TOKEN_CACHE=false` to disable caching and prompt every time.

### When the Azure CLI is missing or cannot sign in

If the Azure CLI is not installed, or its sign-in fails, the Azure tools use the Azure Resource Manager REST API instead, signing in as Azure PowerShell (`AZURE_ARM_CLIENT_ID`), the same app `Connect-AzAccount` uses. Whether that sign-in is allowed is decided by your Tenant's policy. See [Tools](#tools).

### Resource inventory (opt-in)

`azure_find_resource` finds an Azure resource by name (its subscription, resource group, type, location, and ID) in one call. It uses a Resource inventory: a local file listing every Azure resource you can see, built from one Azure Resource Graph query and rebuilt when older than 24 hours or when a lookup finds nothing. It stores only name, type, subscription, resource group, location, and ID (no tags or properties), sits beside the token cache (`TOKEN_CACHE_DIR`, default `~/.IdentityService`), and is readable only by your user account. Microsoft 365 objects are never included.

That file is a map of your whole Azure estate, so it is off by default. The `setup` skill explains the risk and turns it on only if you say yes. To do it yourself:

```bash
uvx --from git+https://github.com/JackInSightsV2/Azure-M365-MCP unified-microsoft-mcp resource-inventory on   # or: off, status
```

`off` withdraws consent and deletes the file. Setting `RESOURCE_INVENTORY=true` in the server environment also gives consent.

### Kubernetes (AKS)

The Kubernetes tools run `az`, `kubelogin`, and `kubectl` with your own kubeconfig (`KUBECONFIG` is respected) and the same access you have in a terminal. They are for desktop use and need nothing installed beyond `uv`:

- Tools already on your `PATH` are used first.
- Otherwise `az` is the Azure CLI installed with the server.
- Otherwise, on first use (`kubernetes_connect`, or `kubernetes_read` / `kubernetes_write` when `kubectl` is missing), the server downloads `kubectl` and `kubelogin` once with Microsoft's `az aks install-cli --install-location <dir>/kubectl --kubelogin-install-location <dir>/kubelogin`, where `<dir>` is `~/.IdentityService/bin` (set `TOOLS_DIR` to change it). Later calls reuse them.

If the download is blocked (offline, proxy), the tool says so and gives the manual install commands, for example:

```bash
brew install kubectl Azure/kubelogin/kubelogin                                    # macOS
winget install -e --id Kubernetes.kubectl; winget install -e --id Microsoft.Azure.Kubelogin   # Windows
az aks install-cli                                                                # any OS with the Azure CLI
```

`kubernetes_connect` (subscription, resource group, cluster, optional namespace) does what you would do by hand, stopping at the first step that fails:

```bash
az account set --subscription <sub>
az aks get-credentials --resource-group <rg> --name <cluster> --overwrite-existing
kubelogin convert-kubeconfig -l azurecli
kubectl config set-context --current --namespace=<ns>
```

If the Azure CLI is not signed in, it starts `az login` first, following `SIGN_IN_FLOW` (a browser window by default; device code only with `SIGN_IN_FLOW=device_code`). Then use `kubernetes_read` for `get`, `describe`, `logs`, `top`, `events`, and other reads, and `kubernetes_write` for every other kubectl command. Interactive and long-running commands (`-it`, `edit`, `attach`, `port-forward`, `proxy`, `--watch`, `logs -f`) are rejected. Set `ENABLE_KUBERNETES=false` to hide the tools.

### Unattended or shared server

Administrators can configure managed identity or a service principal through environment variables. See [env.example](env.example). These options are intended for managed deployments, not normal desktop setup.

The server stops an Azure command if the configured managed identity or service-principal sign-in fails. It will not silently use a different cached identity.

To turn an interactive sign-in into a service principal, an administrator with rights to create app registrations and assign roles can run the bundled helper in a terminal:

```bash
unified-microsoft-mcp-bootstrap-spn --role Reader
```

It signs in (device code if needed), creates the app registration and role assignment, and prints the `AZURE_APP_*` environment variables to set. The generated secret is long-lived and bypasses MFA, so store it in a secret manager and scope the role tightly. This grants Azure Resource Manager access only; Microsoft Graph application permissions require separate admin consent.

## Troubleshooting

### The client says `uvx` was not found

Install [uv](https://docs.astral.sh/uv/), then confirm this works in a terminal:

```bash
uvx --version
```

Some clients do not inherit your shell's `PATH`. If `uvx` works in a terminal but not in the client, use the full path from `which uvx` as the `command`.

### The tools do not appear

Check that the configuration file is in the correct location and contains valid JSON or TOML. Restart the AI client after changing it.

### A browser window opened, or I received a device code

Complete sign-in in the browser window, or open the supplied address and enter the code, then retry the request. Azure and Microsoft Graph may each request sign-in.

### I see a "Permissions requested" consent screen

The server asked Microsoft Graph for a permission your Tenant has not granted, usually because `GRAPH_SCOPES` is set. Accept it only if you are allowed to; otherwise cancel and ask an admin. Remove `GRAPH_SCOPES` to use only the permissions already granted.

### I received `AuthorizationFailed`, `Forbidden`, or `Insufficient privileges`

The signed-in account, or the Microsoft Graph permissions granted in your Tenant, do not allow that operation. For Graph, the result suggests which permission to request with `GRAPH_SCOPES`. Otherwise ask an Azure or Microsoft 365 administrator to confirm the account’s role or Graph permissions. Changing execution policy cannot add permission.

### I received `Execution policy denied...`

The server’s safety policy blocked the operation. Use a read-only command, add the required command to the allowlist, or—only when the role is expected to make changes—use `unrestricted`.

### I am seeing an older version

`uvx` reuses its cached build. Clear it, then restart the AI client so it fetches the latest version:

```bash
uv cache clean unified-microsoft-mcp
```

## Technical reference

### Tools

`azure_read` (the Azure Read tool) and `azure_write` (the Azure Write tool) each accept either an Azure CLI command beginning with `az` or an Azure Resource Manager REST path with the `api-version` query parameter. `azure_read` runs only read-only CLI actions (`list`, `show`, `get`, `query`, `what-if`, ...), REST `GET`, and the read-only POST queries (Resource Graph, Cost Management query, deployment What-if); anything else is rejected with a pointer to `azure_write`. The client can therefore auto-allow `azure_read` and ask before each `azure_write` call.

```text
az account show
az group list
az vm list --resource-group example-rg

command: subscriptions?api-version=2022-12-01
method: GET

command: subscriptions/{id}/resourceGroups/example-rg?api-version=2021-04-01
method: PUT
data: {"location": "eastus"}
```

The server picks the transport. It uses the Azure CLI when it is available and falls back to the Azure Resource Manager REST API (`https://management.azure.com`) when the CLI is missing or fails, including when its sign-in is blocked by Conditional Access. A CLI command with no direct REST equivalent cannot fall back; the error then suggests an ARM path to retry with.

Interactive sign-in for the REST fallback uses `AZURE_ARM_CLIENT_ID` (the Azure PowerShell public client by default), which a locked-down tenant may permit even when the Azure CLI is blocked. Disable the fallback with `ENABLE_AZURE_REST=false`.

`microsoft365_read` accepts a Microsoft Graph v1.0 path and only issues GET requests. `microsoft365_write` accepts a path, a POST, PUT, PATCH, or DELETE method, and an optional JSON body:

```text
# microsoft365_read
command: users

# microsoft365_write

command: groups/{id}
method: PATCH
data: {"displayName": "New name"}
```

Graph writes require an application or managed identity with the necessary Microsoft Graph application permissions.

`kubernetes_connect` connects kubectl to an AKS cluster once; `kubernetes_read` (read-only kubectl commands) and `kubernetes_write` (every other kubectl command) take a `command` beginning with `kubectl` plus optional `context` and `namespace`. See [Kubernetes (AKS)](#kubernetes-aks).

```text
# kubernetes_connect
subscription: Contoso Prod
resource_group: rg-aks
cluster: aks-prod
namespace: payments

# kubernetes_read
command: kubectl get pods -o wide

# kubernetes_write
command: kubectl rollout restart deployment/web
```

### Transport options

| Transport | Setting | Endpoint | Use |
| --- | --- | --- | --- |
| stdio | `MCP_TRANSPORT=stdio` | process input/output | Normal local IDE use; default |
| Streamable HTTP | `MCP_TRANSPORT=streamable-http` | `/mcp` | Shared or remote MCP server |
| SSE | `MCP_TRANSPORT=sse` | `/sse` | Compatibility with older clients |
| OpenAPI | `MCP_TRANSPORT=openapi` | `/docs` | Direct REST integrations |

To run an HTTP transport, start the server yourself with the setting in its environment (or in a `.env` file in the working directory; see [env.example](env.example)):

```bash
MCP_TRANSPORT=openapi uvx --from git+https://github.com/JackInSightsV2/Azure-M365-MCP unified-microsoft-mcp
curl http://127.0.0.1:8001/health
```

For HTTP deployments, set `MCP_API_KEY`, use TLS, and place the server behind network access controls. The built-in server binds to `127.0.0.1` by default.

### Run an installed copy

Install Python 3.11–3.14, then install the package (it includes the Azure CLI):

```bash
python -m pip install .
```

Configure the MCP client to launch `unified-microsoft-mcp` directly instead of `uvx`.

### Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
black --check unified_mcp tests
ruff check unified_mcp tests
mypy unified_mcp
pytest --cov=unified_mcp
```

## Security and licensing

See [SECURITY.md](SECURITY.md) for vulnerability reporting and deployment guidance. This project is licensed under the [MIT License](LICENSE).
