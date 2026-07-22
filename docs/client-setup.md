# MCP client setup

The server works with any MCP client that supports stdio or Streamable HTTP. Stdio is the safest local default because the server process is private to the client. Streamable HTTP is useful when one long-running instance must serve multiple clients.

Install the project first:

```bash
poetry install
poetry env info --path
```

Replace `/absolute/path/to/Azure-M365-MCP` in the examples below. Keep secrets out of committed configuration: use the client's environment support, an uncommitted environment file, or your operating system's secret store.

## Cursor

Cursor reads project configuration from `.cursor/mcp.json` and user configuration from `~/.cursor/mcp.json`.

```json
{
  "mcpServers": {
    "unified-microsoft": {
      "command": "poetry",
      "args": ["run", "unified-microsoft-mcp"],
      "cwd": "/absolute/path/to/Azure-M365-MCP",
      "env": {
        "MCP_TRANSPORT": "stdio",
        "EXECUTION_POLICY": "read-only"
      }
    }
  }
}
```

Cursor also discovers a repository-root `AGENTS.md` for durable project instructions. This repository ignores local agent context so each contributor can keep their own without changing the package.

Official reference: [Cursor MCP documentation](https://cursor.com/docs/context/model-context-protocol).

## Google Antigravity

Antigravity uses `~/.gemini/config/mcp_config.json` globally or `.agents/mcp_config.json` in a workspace.

```json
{
  "mcpServers": {
    "unified-microsoft": {
      "command": "poetry",
      "args": ["run", "unified-microsoft-mcp"],
      "cwd": "/absolute/path/to/Azure-M365-MCP",
      "env": {
        "MCP_TRANSPORT": "stdio",
        "EXECUTION_POLICY": "read-only"
      }
    }
  }
}
```

For a remote server Antigravity calls the endpoint field `serverUrl` (not `url`):

```json
{
  "mcpServers": {
    "unified-microsoft": {
      "serverUrl": "http://127.0.0.1:8001/mcp"
    }
  }
}
```

Official reference: [Antigravity MCP documentation](https://antigravity.google/docs/mcp).

## OpenCode

OpenCode uses `opencode.json`. Its local command is an array and its root key is `mcp`, not `mcpServers`.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "unified-microsoft": {
      "type": "local",
      "command": [
        "poetry",
        "--directory",
        "/absolute/path/to/Azure-M365-MCP",
        "run",
        "unified-microsoft-mcp"
      ],
      "environment": {
        "MCP_TRANSPORT": "stdio",
        "EXECUTION_POLICY": "read-only"
      },
      "enabled": true
    }
  }
}
```

Official reference: [OpenCode MCP servers](https://opencode.ai/docs/mcp-servers/).

## OpenAI Codex

Codex shares MCP configuration across its app, CLI, and IDE extension. Put user configuration in `~/.codex/config.toml`, or trusted project configuration in `.codex/config.toml`.

```toml
[mcp_servers.unified_microsoft]
command = "poetry"
args = ["run", "unified-microsoft-mcp"]
cwd = "/absolute/path/to/Azure-M365-MCP"

[mcp_servers.unified_microsoft.env]
MCP_TRANSPORT = "stdio"
EXECUTION_POLICY = "read-only"
```

Codex also reads `AGENTS.md`. The MCP server publishes concise initialization instructions, so Codex receives tool-selection and credential-safety guidance during protocol initialization as well.

Official reference: [Codex MCP documentation](https://developers.openai.com/codex/mcp/).

## Streamable HTTP

Start a protected loopback server:

```bash
export MCP_TRANSPORT=streamable-http
export MCP_API_KEY="$(openssl rand -hex 32)"
export EXECUTION_POLICY=read-only
poetry run unified-microsoft-mcp
```

The MCP endpoint is `http://127.0.0.1:8001/mcp`. Cursor uses `url`; Antigravity uses `serverUrl`; OpenCode uses a remote entry; Codex uses TOML:

Cursor:

```json
{
  "mcpServers": {
    "unified-microsoft": {
      "url": "http://127.0.0.1:8001/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_API_KEY>"
      }
    }
  }
}
```

Antigravity:

```json
{
  "mcpServers": {
    "unified-microsoft": {
      "serverUrl": "http://127.0.0.1:8001/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_API_KEY>"
      }
    }
  }
}
```

Codex:

```toml
[mcp_servers.unified_microsoft]
url = "http://127.0.0.1:8001/mcp"
bearer_token_env_var = "MCP_API_KEY"
```

OpenCode:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "unified-microsoft": {
      "type": "remote",
      "url": "http://127.0.0.1:8001/mcp",
      "headers": {
        "Authorization": "Bearer {env:MCP_API_KEY}"
      },
      "enabled": true
    }
  }
}
```

When a client cannot resolve bearer tokens from the environment, keep its configuration uncommitted and set an `Authorization: Bearer <MCP_API_KEY>` header. Do not expose the built-in HTTP listener directly to the internet; add TLS and an upstream identity-aware access layer.

## Verify the connection

After restarting the client, it should discover exactly these tools:

- `execute_azure_cli_command`
- `graph_command`

Start with `az account show` and `GET me`. If either returns a device-code prompt, complete sign-in and retry the same request.
