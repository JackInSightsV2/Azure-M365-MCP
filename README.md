# Microsoft 365 & Azure MCP Server

A unified MCP (Model Context Protocol) server that provides access to Microsoft Graph API and Azure CLI through a single Docker container. This server enables AI assistants like Claude, Cursor, and Warp AI to interact with your Microsoft 365 and Azure resources seamlessly.

## ✨ Features

- **Azure CLI Integration**: Execute any Azure CLI command to manage Azure resources
- **Microsoft Graph API**: Full access to Microsoft 365 resources (users, groups, mail, calendars, etc.)
- **Dual Transport Modes**: Supports both stdio (default) and HTTP/SSE transport modes
- **Flexible Authentication**: Interactive device code flow or automated service principal authentication
- **Shared App Registration**: Use a single app registration for both Azure CLI and Graph API
- **Docker Ready**: Pre-built container images available on GitHub Container Registry
- **Production Ready**: Includes health checks, logging, and error handling

## 🚀 Quick Start

### Prerequisites

- Docker installed and running
- Access to Microsoft 365/Azure (for authentication)

### Claude Desktop

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "unified-microsoft-mcp": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--name",
        "unified-microsoft-mcp",
        "-e",
        "LOG_LEVEL=INFO",
        "ghcr.io/jackinsightsv2/m365-azure-mcp:latest"
      ]
    }
  }
}
```

### Cursor

Add this to your `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "unified-microsoft-mcp": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--name",
        "unified-microsoft-mcp",
        "-e",
        "LOG_LEVEL=INFO",
        "ghcr.io/jackinsightsv2/m365-azure-mcp:latest"
      ],
      "env": {}
    }
  }
}
```

### Warp AI

Add this to your Warp MCP configuration:

```json
{
  "unified-microsoft-mcp": {
    "command": "docker",
    "args": [
      "run",
      "--rm",
      "-i",
      "--name",
      "unified-microsoft-mcp",
      "-e",
      "LOG_LEVEL=INFO",
      "ghcr.io/jackinsightsv2/m365-azure-mcp:latest"
    ],
    "env": {},
    "working_directory": null,
    "start_on_launch": true
  }
}
```

The Docker container will be automatically downloaded from GitHub Container Registry.

## 🛠️ Available Tools

### `execute_azure_cli_command`
Execute Azure CLI commands for managing Azure resources. Communicate naturally - ask Claude/Cursor to "list my Azure subscriptions" or "create a resource group called MyRG in East US".

### `graph_command`
Execute Microsoft Graph API commands for managing Microsoft 365 resources. Ask naturally - "show me my profile" or "list all users in my organization".

## 🔐 Authentication & Security

Both tools support multiple authentication modes:

### 1. Interactive Authentication (Default - Most Secure)
When you don't provide credentials in the configuration, the server will prompt you to authenticate through your browser when first using each tool. This keeps your credentials out of configuration files.

**Note**: Interactive authentication works with stdio transport mode. For HTTP/SSE mode, you must provide credentials via environment variables.

### 2. Automated Authentication (Optional)
For automated scenarios or HTTP/SSE transport mode, you can provide credentials via environment variables.

### 3. Shared App Registration (Recommended)
You can use a single Azure AD app registration for both Azure CLI and Microsoft Graph API by setting `SHARE_APP_REGISTRATION=true`. This simplifies configuration and reduces the number of credentials you need to manage.

## 🔧 Configuration with Credentials

### Transport Modes

The server supports two transport modes:

- **stdio** (default): Standard input/output communication, supports interactive authentication
- **sse**: HTTP Server-Sent Events mode, requires credentials in environment variables

To use SSE mode, set `MCP_TRANSPORT=sse` and `MCP_PORT=8001` (or your preferred port).

### Basic Configuration (Interactive Auth)

No credentials needed - authentication happens interactively when tools are first used.

### Advanced Configuration (Automated Auth)

If you want to avoid interactive authentication prompts or use HTTP/SSE mode, add environment variables to your MCP configuration:

### Claude Desktop
```json
{
  "mcpServers": {
    "unified-microsoft-mcp": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--name",
        "unified-microsoft-mcp",
        "-e",
        "AZURE_APP_TENANT_ID=your-tenant-id",
        "-e",
        "AZURE_APP_CLIENT_ID=your-client-id",
        "-e",
        "AZURE_APP_CLIENT_SECRET=your-client-secret",
        "-e",
        "GRAPH_APP_CLIENT_ID=your-graph-client-id",
        "-e",
        "GRAPH_APP_TENANT_ID=your-graph-tenant-id",
        "-e",
        "GRAPH_APP_CLIENT_SECRET=your-graph-client-secret",
        "-e",
        "LOG_LEVEL=INFO",
        "ghcr.io/jackinsightsv2/m365-azure-mcp:latest"
      ]
    }
  }
}
```

### Cursor
```json
{
  "mcpServers": {
    "unified-microsoft-mcp": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--name",
        "unified-microsoft-mcp",
        "-e",
        "AZURE_APP_TENANT_ID=your-tenant-id",
        "-e",
        "AZURE_APP_CLIENT_ID=your-client-id",
        "-e",
        "AZURE_APP_CLIENT_SECRET=your-client-secret",
        "-e",
        "GRAPH_APP_CLIENT_ID=your-graph-client-id",
        "-e",
        "GRAPH_APP_TENANT_ID=your-graph-tenant-id",
        "-e",
        "GRAPH_APP_CLIENT_SECRET=your-graph-client-secret",
        "-e",
        "LOG_LEVEL=INFO",
        "ghcr.io/jackinsightsv2/m365-azure-mcp:latest"
      ],
      "env": {}
    }
  }
}
```

### Warp AI
```json
{
  "unified-microsoft-mcp": {
    "command": "docker",
    "args": [
      "run",
      "--rm",
      "-i",
      "--name",
      "unified-microsoft-mcp",
      "-e",
      "AZURE_APP_TENANT_ID=your-tenant-id",
      "-e",
      "AZURE_APP_CLIENT_ID=your-client-id",
      "-e",
      "AZURE_APP_CLIENT_SECRET=your-client-secret",
      "-e",
      "GRAPH_APP_CLIENT_ID=your-graph-client-id",
      "-e",
      "GRAPH_APP_TENANT_ID=your-graph-tenant-id",
      "-e",
      "GRAPH_APP_CLIENT_SECRET=your-graph-client-secret",
      "-e",
      "LOG_LEVEL=INFO",
      "ghcr.io/jackinsightsv2/m365-azure-mcp:latest"
    ],
    "env": {},
    "working_directory": null,
    "start_on_launch": true
  }
}
```

### Shared App Registration Configuration

To use a single app registration for both Azure CLI and Graph API:

```json
{
  "mcpServers": {
    "unified-microsoft-mcp": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--name",
        "unified-microsoft-mcp",
        "-e",
        "SHARE_APP_REGISTRATION=true",
        "-e",
        "AZURE_APP_TENANT_ID=your-tenant-id",
        "-e",
        "AZURE_APP_CLIENT_ID=your-client-id",
        "-e",
        "AZURE_APP_CLIENT_SECRET=your-client-secret",
        "-e",
        "LOG_LEVEL=INFO",
        "ghcr.io/jackinsightsv2/m365-azure-mcp:latest"
      ]
    }
  }
}
```

When `SHARE_APP_REGISTRATION=true`, the Graph API will automatically use the Azure CLI credentials. Ensure your app registration has both Azure RBAC roles and Microsoft Graph API permissions configured.

### Environment Variables

#### General Settings
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Default: INFO
- `MCP_TRANSPORT`: Transport mode ("stdio" or "sse"). Default: stdio
- `MCP_PORT`: Port for SSE mode. Default: 8001
- `SHARE_APP_REGISTRATION`: Use same app registration for Azure CLI and Graph API (true/false). Default: false

#### Azure CLI
- `AZURE_APP_TENANT_ID`: Your Azure AD tenant ID
- `AZURE_APP_CLIENT_ID`: Your service principal client ID  
- `AZURE_APP_CLIENT_SECRET`: Your service principal client secret
- `AZURE_SUBSCRIPTION_ID`: Your Azure subscription ID (optional)
- `COMMAND_TIMEOUT`: Timeout for Azure CLI commands in seconds. Default: 300
- `MAX_CONCURRENT_COMMANDS`: Maximum concurrent Azure CLI commands. Default: 5

#### Microsoft Graph
- `GRAPH_APP_CLIENT_ID`: Your app registration client ID (for read/write mode)
- `GRAPH_APP_TENANT_ID`: Your app registration tenant ID (for read/write mode)
- `GRAPH_APP_CLIENT_SECRET`: Your app registration client secret (for read/write mode)
- `OPERATION_TIMEOUT`: Timeout for Graph API operations in seconds. Default: 300
- `MAX_CONCURRENT_OPERATIONS`: Maximum concurrent Graph API operations. Default: 5

**Alternative variable names** (for backward compatibility):
- `USE_APP_REG_CLIENTID` (alternative to `GRAPH_APP_CLIENT_ID`)
- `TENANTID` (alternative to `GRAPH_APP_TENANT_ID`)
- `CLIENT_SECRET` (alternative to `GRAPH_APP_CLIENT_SECRET`)

## 🐳 Docker Compose

For local development or production deployment, you can use Docker Compose:

1. Copy `env.example` to `.env`:
   ```bash
   cp env.example .env
   ```

2. Edit `.env` and configure your credentials

3. Start the service:
   ```bash
   docker-compose up -d
   ```

4. View logs:
   ```bash
   docker-compose logs -f
   ```

The docker-compose.yml includes:
- Persistent Azure CLI configuration volume
- Log directory mounting
- Health checks
- Resource limits
- Automatic restart policy

## 💻 Local Development

### Prerequisites

- Python 3.11+
- Azure CLI installed
- Poetry (for dependency management)

### Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd Azure-M365-MCP
   ```

2. Install dependencies:
   ```bash
   poetry install
   ```

3. Copy environment file:
   ```bash
   cp env.example .env
   ```

4. Configure `.env` with your settings

5. Run the server:
   ```bash
   poetry run python -m unified_mcp.main
   ```

   Or use the entry point:
   ```bash
   poetry run unified-microsoft-mcp
   ```

### Building the Docker Image

```bash
docker build -t unified-microsoft-mcp:latest .
```

### Running Tests

```bash
poetry run pytest
```

## 📖 Usage Examples

### Azure CLI Examples

```bash
# List subscriptions
execute_azure_cli_command(command="az account list")

# List resource groups
execute_azure_cli_command(command="az group list")

# Create a resource group
execute_azure_cli_command(command="az group create --name MyRG --location eastus")

# List virtual machines
execute_azure_cli_command(command="az vm list")

# Get storage accounts
execute_azure_cli_command(command="az storage account list")
```

### Microsoft Graph Examples

```bash
# Get current user info
graph_command(command="me")

# List all users
graph_command(command="users")

# Get specific user
graph_command(command="users/user@domain.com")

# List groups
graph_command(command="groups")

# Get user's mail
graph_command(command="me/mailFolders/inbox/messages")

# Create a user (requires client secret)
graph_command(
    command="users",
    method="POST",
    data={
        "accountEnabled": true,
        "displayName": "John Doe",
        "mailNickname": "johndoe",
        "userPrincipalName": "johndoe@yourdomain.com",
        "passwordProfile": {
            "forceChangePasswordNextSignIn": true,
            "password": "TempPassword123!"
        }
    }
)
```

## 🔒 Security Best Practices

1. **Interactive Authentication (Recommended)**: Use the default configuration without credentials. The server will securely prompt for authentication when needed, keeping your secrets out of configuration files.

2. **Environment Variables**: Only add credentials to the configuration if you need fully automated operation or are using HTTP/SSE mode.

3. **Shared App Registration**: When using `SHARE_APP_REGISTRATION=true`, ensure your app registration has the minimum required permissions for both Azure CLI and Graph API operations.

4. **Client Secrets**: You don't need to add secrets to environment variables if using interactive authentication. The server will prompt for them when needed.

5. **HTTP/SSE Mode**: When using SSE transport mode, credentials are required as interactive authentication is not supported.

## 🐛 Troubleshooting

### Authentication Issues

**Problem**: "Authentication failed" or "Client secret required"
- **Solution**: Check that your client ID, tenant ID, and client secret are correct
- Ensure you copied the secret **value**, not the secret ID
- Verify your app registration has the required permissions

**Problem**: "Device code timeout"
- **Solution**: Complete authentication within the time limit (usually 15 minutes)
- For automated scenarios, use service principal authentication instead

**Problem**: "Permission denied" for Graph API operations
- **Solution**: Configure appropriate API permissions in Azure Portal
- For read/write operations, ensure your app registration has the necessary delegated or application permissions
- If using shared app registration, ensure the app has both Azure RBAC roles and Graph API permissions

### Transport Mode Issues

**Problem**: Server not responding in SSE mode
- **Solution**: Ensure `MCP_TRANSPORT=sse` and `MCP_PORT` are set correctly
- Check that the port is not already in use
- Verify firewall rules allow connections to the port

**Problem**: Interactive auth not working in SSE mode
- **Solution**: SSE mode requires credentials in environment variables. Interactive authentication only works with stdio transport mode.

### Configuration Issues

**Problem**: Graph API using wrong credentials
- **Solution**: Check `SHARE_APP_REGISTRATION` setting
  - If `true`, Graph uses `AZURE_APP_*` credentials
  - If `false`, Graph uses `GRAPH_APP_*` credentials or falls back to read-only mode

**Problem**: "Missing required credentials for HTTP mode"
- **Solution**: HTTP/SSE mode requires credentials. Provide:
  - Azure CLI: `AZURE_APP_TENANT_ID`, `AZURE_APP_CLIENT_ID`, `AZURE_APP_CLIENT_SECRET`
  - Graph API: `GRAPH_APP_*` credentials or enable `SHARE_APP_REGISTRATION=true`

### Docker Issues

**Problem**: Container exits immediately
- **Solution**: Check logs with `docker logs unified-microsoft-mcp`
- Ensure environment variables are set correctly
- Verify the image was pulled successfully

**Problem**: Azure CLI commands fail
- **Solution**: Ensure Azure CLI is authenticated in the container
- For persistent auth, use the mounted volume for Azure CLI config
- Check that the service principal has appropriate Azure RBAC roles

## 📚 Additional Resources

- [Microsoft Graph API Documentation](https://docs.microsoft.com/en-us/graph/api/overview)
- [Azure CLI Documentation](https://docs.microsoft.com/en-us/cli/azure/)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [Azure AD App Registration Guide](https://docs.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

MIT License 