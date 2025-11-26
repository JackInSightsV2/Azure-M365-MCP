# Release v1.0.1

## 🚀 Major Features

### HTTP & OpenAPI Access
This release introduces powerful new transport modes that expand how you can interact with the MCP server:

- **HTTP/SSE Mode**: Run the server over HTTP using Server-Sent Events, enabling remote access and integration with web applications
- **OpenAPI/REST API Mode**: Full REST API support with interactive Swagger UI documentation
  - Access Swagger UI at `http://localhost:<port>/docs`
  - Standard HTTP POST endpoints for Azure CLI and Graph commands
  - Perfect for integration with external tools, scripts, and web applications

### Streamlined Application
We've significantly simplified configuration and improved the overall user experience:

- **Shared App Registration**: Use a single Azure AD app registration for both Azure CLI and Microsoft Graph API
  - Set `SHARE_APP_REGISTRATION=true` to enable
  - Eliminates duplicate credential configuration
  - Reduces setup complexity and credential management overhead
- **Unified Configuration**: Improved configuration management with better defaults and validation
- **Enhanced Credential Handling**: Smarter fallback logic for authentication credentials

## 📋 What's New

### Transport Modes
- **stdio** (default): Standard input/output communication with interactive authentication
- **sse**: HTTP Server-Sent Events mode for remote access
- **openapi**: Full REST API with Swagger documentation

### Configuration Improvements
- Simplified credential management with shared app registration support
- Better environment variable handling and validation
- Improved error messages and logging

### API Endpoints (OpenAPI Mode)
- `POST /execute-azure-cli` - Execute Azure CLI commands via REST API
- `POST /execute-graph-command` - Execute Microsoft Graph API commands via REST API
- `GET /docs` - Interactive Swagger UI documentation

## 🔧 Usage

### Enable OpenAPI Mode
```bash
docker run --rm -i \
  -e MCP_TRANSPORT=openapi \
  -e MCP_PORT=8001 \
  -p 8001:8001 \
  ghcr.io/jackinsightsv2/m365-azure-mcp:latest
```

Then access the Swagger UI at `http://localhost:8001/docs`

### Enable Shared App Registration
```bash
docker run --rm -i \
  -e SHARE_APP_REGISTRATION=true \
  -e AZURE_APP_TENANT_ID=your-tenant-id \
  -e AZURE_APP_CLIENT_ID=your-client-id \
  -e AZURE_APP_CLIENT_SECRET=your-client-secret \
  ghcr.io/jackinsightsv2/m365-azure-mcp:latest
```

## 📦 Docker Image

The Docker image is automatically built and published to GitHub Container Registry:
- `ghcr.io/jackinsightsv2/m365-azure-mcp:v1.0.1`
- `ghcr.io/jackinsightsv2/m365-azure-mcp:latest`

## 🔄 Migration Notes

- Existing stdio mode configurations continue to work without changes
- New HTTP/SSE and OpenAPI modes require credentials via environment variables (interactive auth not supported)
- Shared app registration is optional but recommended for simplified configuration

## 🐛 Bug Fixes & Improvements

- Improved error handling and logging
- Better credential validation and fallback logic
- Enhanced documentation and examples

---

**Full Changelog**: See commit history for detailed changes.

