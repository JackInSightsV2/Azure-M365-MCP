#!/usr/bin/env python3
"""Unified Microsoft MCP Server - Main entry point."""

import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Resource, TextContent, Tool
from pydantic import AnyUrl, BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from unified_mcp.config import Settings
from unified_mcp.security import HttpSecurityMiddleware
from unified_mcp.services.azure_cli_service import AzureCliService
from unified_mcp.services.graph_service import GraphService

# Basic logging setup (will be reconfigured in main() with settings)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Global service instances
azure_cli_service: Optional[AzureCliService] = None
graph_service: Optional[GraphService] = None


# Pydantic models for OpenAPI
class AzureCliRequest(BaseModel):
    command: str


class AzureCliResponse(BaseModel):
    result: Any  # Can be a list, dict, or string depending on the command


class GraphRequest(BaseModel):
    command: str
    method: str = "GET"
    data: Optional[Dict[str, Any]] = None


class GraphResponse(BaseModel):
    success: bool = False
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    error_details: Optional[Dict[str, Any]] = None
    suggestion: Optional[str] = None
    auth_required: Optional[bool] = None
    verification_uri: Optional[str] = None
    user_code: Optional[str] = None
    expires_in: Optional[int] = None
    instructions: Optional[str] = None

    model_config = {"extra": "allow"}  # Allow extra fields that might be returned


def create_azure_cli_tool() -> Tool:
    """Create the Azure CLI command execution tool definition."""
    return Tool(
        name="execute_azure_cli_command",
        description=(
            "Execute Azure CLI commands. This tool allows you to run any Azure CLI command "
            "and get the output. Commands must start with 'az'. For authentication, you can "
            "use 'az login' for device code flow, configure managed identity, or provide "
            "service-principal credentials in environment variables."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The Azure CLI command to execute. Must start with 'az'. "
                        "Examples: 'az account list', 'az login', 'az group list'"
                    ),
                }
            },
            "required": ["command"],
        },
    )


def create_graph_tool() -> Tool:
    """Create the Microsoft Graph API tool definition."""
    return Tool(
        name="graph_command",
        description="Execute Microsoft Graph API commands. Supports GET, POST, PUT, PATCH, DELETE operations.",
        inputSchema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Graph API endpoint (e.g., 'users', 'me', 'groups', 'devices')",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "default": "GET",
                    "description": "HTTP method to use",
                },
                "data": {
                    "type": "object",
                    "description": "Request body data (for POST, PUT, PATCH operations)",
                },
            },
            "required": ["command"],
        },
    )


async def process_tool_call(
    name: str,
    arguments: Dict[str, Any],
    azure_service: Optional[AzureCliService],
    graph_service: Optional[GraphService],
) -> List[TextContent]:
    """Process tool execution requests."""
    if name == "execute_azure_cli_command":
        try:
            # Check if service is initialized
            if not azure_service:
                return [TextContent(type="text", text="Error: Azure CLI service not initialized")]

            # Validate arguments
            if not arguments or "command" not in arguments:
                return [TextContent(type="text", text="Error: Missing command argument")]

            command = arguments["command"]
            if not isinstance(command, str):
                return [TextContent(type="text", text="Error: Command must be a string")]

            logger.info("Executing Azure CLI command via MCP")

            # Execute the Azure CLI command
            azure_result = await azure_service.execute_azure_cli(command)
            return [TextContent(type="text", text=azure_result)]

        except Exception as e:
            logger.error(f"Error executing Azure CLI command: {e}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    elif name == "graph_command":
        try:
            # Check if service is initialized
            if not graph_service:
                return [TextContent(type="text", text="Error: Graph service not initialized")]

            command = arguments.get("command", "")
            method = arguments.get("method", "GET")
            data = arguments.get("data")

            logger.info(f"Executing Graph command: {method} {command}")

            graph_result = await graph_service.execute_command(command, method, data)

            # Format the response
            if graph_result.get("success"):
                response_text = f"✅ **Success** ({method} {command})\n\n"
                if graph_result.get("data"):
                    response_text += f"```json\n{json.dumps(graph_result['data'], indent=2)}\n```"
                else:
                    response_text += "Operation completed successfully."
            else:
                response_text = f"❌ **Error** ({method} {command})\n\n"
                response_text += f"**Error:** {graph_result.get('error', 'Unknown error')}\n\n"

                if graph_result.get("auth_required") and graph_result.get("instructions"):
                    response_text += f"**Instructions:**\n{graph_result['instructions']}\n\n"

                if graph_result.get("error_details"):
                    response_text += f"**Details:**\n```json\n{json.dumps(graph_result['error_details'], indent=2)}\n```"

            return [TextContent(type="text", text=response_text)]

        except Exception as e:
            logger.error(f"Error executing Graph command: {e}")
            error_text = f"❌ **Graph Tool Execution Failed**\n\n**Error:** {str(e)}"
            return [TextContent(type="text", text=error_text)]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    """Main MCP server entry point."""
    global azure_cli_service, graph_service

    try:
        # Initialize settings first
        settings = Settings()

        # Configure logging with settings (log file and log level)
        log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)

        # Remove existing file handlers to avoid duplicates
        root_logger.handlers = [
            h for h in root_logger.handlers if not isinstance(h, logging.FileHandler)
        ]

        # Add file handler with configured log file path
        log_directory = os.path.dirname(settings.log_file)
        if log_directory:
            os.makedirs(log_directory, exist_ok=True)
        file_handler = logging.FileHandler(settings.log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        root_logger.addHandler(file_handler)

        # Ensure stderr handler exists and is configured
        stderr_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, logging.StreamHandler) and h.stream == sys.stderr
        ]
        if not stderr_handlers:
            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setLevel(log_level)
            stderr_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
            root_logger.addHandler(stderr_handler)
        else:
            # Update existing stderr handler level
            for h in stderr_handlers:
                h.setLevel(log_level)

        # Initialize services
        azure_cli_service = AzureCliService(settings)
        graph_service = GraphService(settings)

        # Create MCP server
        server: Server = Server(settings.mcp_server_name)

        # Register tools
        azure_cli_tool = create_azure_cli_tool()
        graph_tool = create_graph_tool()

        @server.list_tools()  # type: ignore
        async def handle_list_tools() -> List[Tool]:
            """List available tools."""
            return [azure_cli_tool, graph_tool]

        @server.call_tool()  # type: ignore
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> list[TextContent]:
            """Handle tool execution requests."""
            return await process_tool_call(name, arguments, azure_cli_service, graph_service)

        @server.list_resources()  # type: ignore
        async def handle_list_resources() -> List[Resource]:
            """List available resources."""
            return [
                Resource(
                    uri=AnyUrl("azure://help"),
                    name="Azure CLI Help",
                    description="Help and examples for using Azure CLI commands",
                    mimeType="text/plain",
                ),
                Resource(
                    uri=AnyUrl("graph://help"),
                    name="Microsoft Graph Help",
                    description="Help and examples for using Microsoft Graph API",
                    mimeType="text/plain",
                ),
            ]

        @server.read_resource()  # type: ignore
        async def handle_read_resource(uri: AnyUrl) -> str:
            """Read a resource."""
            uri_string = str(uri)
            if uri_string == "azure://help":
                return """
# Azure CLI MCP Help

This tool provides access to Azure CLI commands through MCP.

## Authentication

The Azure CLI tool supports multiple authentication methods:

1. **Device Code Flow (Recommended for interactive use)**
   - Run: `az login`
   - Follow the device code authentication flow
   - Opens browser for authentication

2. **Service Principal (For automated operations)**
   - Set environment variables:
     - `AZURE_APP_TENANT_ID`: Your Azure AD tenant ID
     - `AZURE_APP_CLIENT_ID`: Your service principal client ID
     - `AZURE_APP_CLIENT_SECRET`: Your service principal client secret
     - `AZURE_SUBSCRIPTION_ID`: Your Azure subscription ID (optional)
   - **Shared App Registration**: Set `SHARE_APP_REGISTRATION=true` to use these same credentials for Microsoft Graph API

## Examples

### Login and basic operations
```
execute_azure_cli_command(command="az login")
execute_azure_cli_command(command="az account list")
execute_azure_cli_command(command="az account show")
```

### Resource management
```
execute_azure_cli_command(command="az group list")
execute_azure_cli_command(command="az vm list")
execute_azure_cli_command(command="az storage account list")
```

### Get help
```
execute_azure_cli_command(command="az --help")
execute_azure_cli_command(command="az vm --help")
```

## Security Notes

- Commands are validated to start with 'az'
- Commands are parsed into arguments and executed without a shell
- Sensitive flag values are redacted from diagnostic logs
"""

            elif uri_string == "graph://help":
                return """
# Microsoft Graph MCP Help

This tool provides access to Microsoft Graph API endpoints through MCP.

## Authentication

The Graph tool supports two authentication modes:

1. **Device Code Flow (Recommended for read-only operations)**
   - No client secret required
   - Opens browser for authentication
   - Suitable for user-delegated permissions

2. **Managed Identity (Recommended for Azure-hosted automation)**
   - Set `USE_MANAGED_IDENTITY=true`
   - Optionally set `MANAGED_IDENTITY_CLIENT_ID` for a user-assigned identity
   - Grant the identity the required Azure roles and Microsoft Graph application permissions

3. **Client Secret Flow (For application permissions)**
   - Requires client secret
   - Suitable for automated operations
   - Supply credentials through environment variables

## Configuration

### Option 1: Separate Credentials (Default)
Set these environment variables for Graph API:
- `GRAPH_APP_CLIENT_ID`: Your Azure AD application client ID (for read/write mode)
- `GRAPH_APP_TENANT_ID`: Your Azure AD tenant ID (for read/write mode)
- `GRAPH_APP_CLIENT_SECRET` or `CLIENT_SECRET`: Your client secret (optional, for app permissions)

### Option 2: Shared App Registration (Recommended)
To use the same app registration for both Azure CLI and Graph API, set:
- `SHARE_APP_REGISTRATION=true`: Enables credential sharing between Azure CLI and Graph API
- `AZURE_APP_TENANT_ID`: Your Azure AD tenant ID (shared)
- `AZURE_APP_CLIENT_ID`: Your Azure AD application client ID (shared)
- `AZURE_APP_CLIENT_SECRET`: Your client secret (shared)

When `SHARE_APP_REGISTRATION=true`, Graph API will automatically use the Azure CLI credentials if Graph-specific credentials are not provided. This eliminates the need to set duplicate environment variables.

## Examples

### Get current user info
```
graph_command(command="me")
```

### List all users
```
graph_command(command="users")
```

### Get specific user
```
graph_command(command="users/user@domain.com")
```

### Create a user (requires client secret)
```
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
    },
)
```

### Update user
```
graph_command(
    command="users/user@domain.com",
    method="PATCH", 
    data={"jobTitle": "Senior Developer"}
)
```

### Delete user
```
graph_command(
    command="users/user@domain.com",
    method="DELETE"
)
```

## Common Endpoints

- `me` - Current user info
- `users` - All users
- `groups` - All groups  
- `devices` - All devices
- `applications` - Applications
- `servicePrincipals` - Service principals
- `directoryRoles` - Directory roles
- `organization` - Organization info

For more endpoints, see: https://learn.microsoft.com/graph/api/overview
"""

            raise ValueError(f"Unknown resource: {uri}")

        logger.info("Starting Unified Microsoft MCP Server...")
        logger.info(f"Available tools: {azure_cli_tool.name}, {graph_tool.name}")
        logger.info(f"Log level: {settings.log_level}")
        logger.info(f"Log file: {settings.log_file}")
        logger.info(f"MCP Transport mode: {settings.mcp_transport}")
        if settings.share_app_registration:
            logger.info(
                "✅ Shared app registration enabled: Graph API will use Azure CLI credentials"
            )

        api_key = (
            settings.mcp_api_key.get_secret_value() if settings.mcp_api_key is not None else None
        )
        if settings.mcp_transport != "stdio" and not api_key:
            logger.warning(
                "HTTP transport has no MCP_API_KEY; rely only on a loopback bind or trusted network"
            )

        if settings.mcp_transport == "streamable-http":
            logger.info(
                "Starting Streamable HTTP server on http://%s:%s/mcp",
                settings.mcp_host,
                settings.mcp_port,
            )
            session_manager = StreamableHTTPSessionManager(
                app=server,
                json_response=False,
                stateless=False,
            )

            @contextlib.asynccontextmanager
            async def streamable_lifespan(_app: Starlette) -> AsyncIterator[None]:
                async with session_manager.run():
                    yield

            streamable_starlette_app = Starlette(
                routes=[Mount("/mcp", app=session_manager.handle_request)],
                lifespan=streamable_lifespan,
            )
            streamable_cors_app = CORSMiddleware(
                streamable_starlette_app,
                allow_origins=settings.cors_allowed_origins,
                allow_methods=["GET", "POST", "DELETE"],
                allow_headers=[
                    "Authorization",
                    "Content-Type",
                    "MCP-Protocol-Version",
                    "Mcp-Session-Id",
                ],
                expose_headers=["Mcp-Session-Id"],
            )
            streamable_secured_app = HttpSecurityMiddleware(
                streamable_cors_app,
                api_key=api_key,
                allowed_origins=settings.cors_allowed_origins,
            )
            config = uvicorn.Config(
                streamable_secured_app,
                host=settings.mcp_host,
                port=settings.mcp_port,
                log_level=settings.log_level.lower(),
            )
            await uvicorn.Server(config).serve()
        elif settings.mcp_transport == "sse":
            # Validate credentials for HTTP mode (where interactive auth isn't possible)
            missing_creds = []

            # Check Azure CLI credentials
            if not settings.use_managed_identity and not settings.has_azure_credentials():
                logger.warning(
                    "⚠️ Azure CLI credentials missing in HTTP mode. Interactive 'az login' will not work for remote users."
                )
                missing_creds.append(
                    "Azure CLI (AZURE_APP_TENANT_ID, AZURE_APP_CLIENT_ID, AZURE_APP_CLIENT_SECRET)"
                )

            # Check Graph credentials
            if settings.use_managed_identity:
                logger.info("Using managed identity for Azure CLI and Microsoft Graph")
            elif settings.share_app_registration:
                # When sharing is enabled, Graph will use Azure credentials if available
                if settings.has_azure_credentials():
                    logger.info(
                        "✅ Using shared app registration: Graph API will use Azure CLI credentials"
                    )
                else:
                    logger.warning(
                        "⚠️ Shared app registration enabled but Azure CLI credentials missing. Graph API will fall back to read-only mode."
                    )
                    missing_creds.append(
                        "Azure CLI credentials (required when SHARE_APP_REGISTRATION=true)"
                    )
            else:
                # Separate credentials mode
                if settings.is_graph_read_only_mode:
                    logger.warning(
                        "⚠️ Graph API credentials missing in HTTP mode. Interactive Device Code Flow will not work for remote users."
                    )
                    logger.info(
                        "💡 Tip: Set SHARE_APP_REGISTRATION=true to use Azure CLI credentials for Graph API"
                    )
                    missing_creds.append(
                        "Microsoft Graph (GRAPH_APP_CLIENT_ID, GRAPH_APP_TENANT_ID, GRAPH_APP_CLIENT_SECRET) or enable SHARE_APP_REGISTRATION"
                    )
                elif not settings.get_graph_client_secret():
                    logger.warning(
                        "⚠️ Graph API Client Secret missing in HTTP mode. Tool calls will fail until the environment is configured."
                    )
                    missing_creds.append("Microsoft Graph Secret (GRAPH_APP_CLIENT_SECRET)")

            if missing_creds:
                logger.error("Missing required credentials for non-interactive HTTP mode:")
                for cred in missing_creds:
                    logger.error(f"  - {cred}")
                logger.error("Please provide these environment variables to enable authentication.")

            sse = SseServerTransport("/messages/")

            async def handle_sse(request: Request) -> PlainTextResponse:
                async with sse.connect_sse(
                    request.scope, request.receive, request._send
                ) as streams:
                    await server.run(streams[0], streams[1], server.create_initialization_options())
                # Return empty response to avoid NoneType error when client disconnects
                return PlainTextResponse("")

            async def sse_health(_request: Request) -> JSONResponse:
                return JSONResponse({"status": "ok"})

            starlette_app = Starlette(
                routes=[
                    Route("/health", endpoint=sse_health),
                    Route("/sse", endpoint=handle_sse),
                    Mount("/messages/", app=sse.handle_post_message),
                ],
                debug=settings.log_level == "DEBUG",
            )

            sse_cors_app = CORSMiddleware(
                starlette_app,
                allow_origins=settings.cors_allowed_origins,
                allow_methods=["GET", "POST"],
                allow_headers=["Authorization", "Content-Type"],
            )
            sse_secured_app = HttpSecurityMiddleware(
                sse_cors_app,
                api_key=api_key,
                allowed_origins=settings.cors_allowed_origins,
            )

            logger.info(f"Starting SSE server on port {settings.mcp_port}")
            config = uvicorn.Config(
                sse_secured_app,
                host=settings.mcp_host,
                port=settings.mcp_port,
                log_level=settings.log_level.lower(),
            )
            server_instance = uvicorn.Server(config)
            await server_instance.serve()
        elif settings.mcp_transport == "openapi":
            # OpenAPI mode using FastAPI
            logger.info("Starting OpenAPI server...")

            app = FastAPI(
                title="Unified Microsoft MCP API",
                description="OpenAPI interface for Azure CLI and Microsoft Graph tools",
                version="1.1.0",
            )

            # Add CORS middleware to allow cross-origin requests
            app.add_middleware(
                CORSMiddleware,
                allow_origins=settings.cors_allowed_origins,
                allow_credentials=False,
                allow_methods=["GET", "POST"],
                allow_headers=["Authorization", "Content-Type"],
            )

            @app.get("/health", include_in_schema=False)
            async def health() -> Dict[str, str]:
                return {"status": "ok"}

            @app.post("/execute-azure-cli", response_model=AzureCliResponse)
            async def execute_azure_cli(request: AzureCliRequest) -> AzureCliResponse:
                if not azure_cli_service:
                    raise HTTPException(status_code=500, detail="Azure CLI service not initialized")

                try:
                    logger.info("Executing Azure CLI command via API")
                    result = await azure_cli_service.execute_azure_cli(request.command)

                    # Try to parse result as JSON if it's a JSON string
                    # This prevents double-encoding JSON responses
                    try:
                        parsed_result = json.loads(result)
                        return AzureCliResponse(result=parsed_result)
                    except (json.JSONDecodeError, TypeError):
                        # If it's not valid JSON, return as string
                        return AzureCliResponse(result=result)
                except Exception as e:
                    logger.error(f"Error executing Azure CLI command: {e}")
                    raise HTTPException(status_code=500, detail=str(e))

            @app.post("/execute-graph-command", response_model=GraphResponse)
            async def execute_graph_command(request: GraphRequest) -> GraphResponse:
                if not graph_service:
                    raise HTTPException(status_code=500, detail="Graph service not initialized")

                try:
                    logger.info(
                        f"Executing Graph command via API: {request.method} {request.command}"
                    )
                    result = await graph_service.execute_command(
                        request.command,
                        request.method,
                        request.data,
                    )
                    # Ensure the result matches the response model structure
                    # Use model_validate to handle missing fields gracefully
                    return GraphResponse.model_validate(result)
                except Exception as e:
                    logger.error(f"Error executing Graph command: {e}")
                    raise HTTPException(status_code=500, detail=str(e))

            secured_app = HttpSecurityMiddleware(
                app,
                api_key=api_key,
                allowed_origins=settings.cors_allowed_origins,
                public_paths={"/docs", "/openapi.json", "/redoc"},
            )
            logger.info(f"Starting FastAPI server on port {settings.mcp_port}")
            config = uvicorn.Config(
                secured_app,
                host=settings.mcp_host,
                port=settings.mcp_port,
                log_level=settings.log_level.lower(),
            )
            server_instance = uvicorn.Server(config)
            await server_instance.serve()
        else:
            # Run the server with stdio transport
            logger.warning(
                f"⚠️ Transport mode '{settings.mcp_transport}' not recognized, falling back to stdio mode"
            )
            logger.warning(
                "⚠️ Note: stdio mode requires interactive stdin, which may not work in detached Docker containers"
            )
            async with stdio_server() as streams:
                await server.run(
                    streams[0],  # read stream
                    streams[1],  # write stream
                    server.create_initialization_options(),
                )

    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Error in MCP server: {e}")
        sys.exit(1)
    finally:
        if graph_service is not None:
            await graph_service.close()


def run() -> None:
    """Run the asynchronous server from console-script and module entry points."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
