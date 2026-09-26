# MCP client setup

Cursor, Antigravity, OpenCode, and Codex start the server automatically when they need it and stop it when the session ends. The configuration only tells the client what command to launch.

The examples start the server with [`uvx`](https://docs.astral.sh/uv/), which fetches and runs it without a separate install. Azure CLI commands also need the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli); without it, `azure_read` / `azure_write` use Azure Resource Manager REST. The `unified-microsoft-mcp install --client <name>` command writes these entries for Claude Code, VS Code, Cursor, Codex, and Claude Desktop.

## Cursor

Add this to `.cursor/mcp.json` in a project or `~/.cursor/mcp.json` globally:

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

Reference: [Cursor MCP documentation](https://cursor.com/docs/context/model-context-protocol).

## Google Antigravity

Add this to `.agents/mcp_config.json` in a workspace or `~/.gemini/config/mcp_config.json` globally:

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

Reference: [Antigravity MCP documentation](https://antigravity.google/docs/mcp).

## OpenCode

Add this to `opencode.json`:

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

Reference: [OpenCode MCP servers](https://opencode.ai/docs/mcp-servers/).

## OpenAI Codex

Add this to `~/.codex/config.toml` or `.codex/config.toml` in a trusted project:

```toml
[mcp_servers.unified_microsoft]
command = "uvx"
args = ["--from", "git+https://github.com/JackInSightsV2/Azure-M365-MCP", "unified-microsoft-mcp"]
```

Reference: [Codex MCP documentation](https://developers.openai.com/codex/mcp/).

## Installed executable

To run a locally installed copy instead of `uvx`, install Python 3.11–3.14 and the package (it includes the Azure CLI):

```bash
python -m pip install .
```

Then replace the `uvx` command in the relevant example with the installed executable:

```json
{
  "command": "unified-microsoft-mcp",
  "args": []
}
```

For OpenCode use `"command": ["unified-microsoft-mcp"]`; for Codex use `command = "unified-microsoft-mcp"` and omit `args`.

## Optional: limit what the assistant can do

The default policy is `unrestricted`, which allows the assistant to use any operation permitted by the signed-in account.

If the user should only investigate and collect information, set the environment variable in the client configuration.

Cursor and Antigravity:

```json
"env": {
  "EXECUTION_POLICY": "read-only"
}
```

OpenCode:

```json
"environment": {
  "EXECUTION_POLICY": "read-only"
}
```

Codex:

```toml
[mcp_servers.unified_microsoft.env]
EXECUTION_POLICY = "read-only"
```

Use `allowlist` only for a tightly controlled role or workflow. See [Execution policy in the README](../README.md#execution-policy-an-optional-safety-switch) for examples and guidance.

## Authentication

Start with either tool:

- `azure_read` with `az login`
- `microsoft365_read` with `me`

When sign-in is required a browser window opens (or, with `SIGN_IN_FLOW=device_code`, the tool returns a device code). Complete sign-in and retry the request. For unattended deployments, pass managed-identity or service-principal settings from [env.example](../env.example) instead.

## Remote server

Stdio is the normal IDE setup. If you deliberately run one shared Streamable HTTP server (`MCP_TRANSPORT=streamable-http`), configure the client with `http://127.0.0.1:8001/mcp` instead of a command. Cursor, OpenCode, and Codex call this field `url`; Antigravity calls it `serverUrl`. Set `MCP_API_KEY` on the server and configure the client to send it as a bearer token.
