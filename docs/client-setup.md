# MCP client setup

Cursor, Antigravity, OpenCode, and Codex start the server automatically when they need it and stop it when the session ends. The configuration only tells the client what command to launch.

The examples use Docker because the image includes the server and Azure CLI. Docker creates the `unified-microsoft-mcp-azure` volume automatically, preserving Azure CLI sign-in between sessions.

## Cursor

Add this to `.cursor/mcp.json` in a project or `~/.cursor/mcp.json` globally:

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

Reference: [Cursor MCP documentation](https://cursor.com/docs/context/model-context-protocol).

## Google Antigravity

Add this to `.agents/mcp_config.json` in a workspace or `~/.gemini/config/mcp_config.json` globally:

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

Reference: [Antigravity MCP documentation](https://antigravity.google/docs/mcp).

## OpenCode

Add this to `opencode.json`:

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

Reference: [OpenCode MCP servers](https://opencode.ai/docs/mcp-servers/).

## OpenAI Codex

Add this to `~/.codex/config.toml` or `.codex/config.toml` in a trusted project:

```toml
[mcp_servers.unified_microsoft]
command = "docker"
args = [
  "run", "--rm", "-i",
  "-v", "unified-microsoft-mcp-azure:/home/app/.azure",
  "ghcr.io/jackinsightsv2/azure-m365-mcp:latest"
]
```

Reference: [Codex MCP documentation](https://developers.openai.com/codex/mcp/).

## Without Docker

Install Python 3.11–3.14, Azure CLI, and the package:

```bash
python -m pip install .
```

Then replace the Docker command in the relevant example with the installed executable:

```json
{
  "command": "unified-microsoft-mcp",
  "args": []
}
```

For OpenCode use `"command": ["unified-microsoft-mcp"]`; for Codex use `command = "unified-microsoft-mcp"` and omit `args`.

## Authentication

Start with either tool:

- `execute_azure_cli_command` with `az login`
- `graph_command` with `GET me`

The tool returns a device code when sign-in is required. Complete sign-in and retry the request. For unattended deployments, pass managed-identity or service-principal settings from [env.example](../env.example) instead.

## Remote server

Stdio is the normal IDE setup. If you deliberately run one shared Streamable HTTP server, configure the client with `http://127.0.0.1:8001/mcp` instead of a command. Cursor, OpenCode, and Codex call this field `url`; Antigravity calls it `serverUrl`. Set `MCP_API_KEY` on the server and configure the client to send it as a bearer token.
