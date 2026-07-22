"""MCP and OpenAPI transport factories around the shared tool application."""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Dict, Literal, Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import CallToolResult, TextContent
from pydantic import AnyUrl, BaseModel
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from unified_mcp.application import (
    SERVER_INSTRUCTIONS,
    ToolApplication,
    create_resources,
    create_tools,
    read_resource,
)
from unified_mcp.config import Settings
from unified_mcp.security import HttpSecurityMiddleware

logger = logging.getLogger(__name__)


class AzureCliRequest(BaseModel):
    command: str


class AzureCliResponse(BaseModel):
    result: Any


class GraphRequest(BaseModel):
    command: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    data: Optional[Dict[str, Any]] = None


class GraphResponse(BaseModel):
    success: bool = False
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    error_details: Any = None
    suggestion: Optional[str] = None
    auth_required: Optional[bool] = None
    verification_uri: Optional[str] = None
    user_code: Optional[str] = None
    expires_in: Optional[int] = None
    instructions: Optional[str] = None

    model_config = {"extra": "allow"}


def create_mcp_server(settings: Settings, application: ToolApplication) -> Server[Any, Any]:
    """Create the protocol server and register transport-independent handlers."""
    server: Server[Any, Any] = Server(
        settings.mcp_server_name,
        version="1.1.0",
        instructions=SERVER_INSTRUCTIONS,
    )
    tools = create_tools()
    resources = create_resources()

    @server.list_tools()  # type: ignore[untyped-decorator]
    async def handle_list_tools() -> list[Any]:
        return tools

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
        result = await application.execute_tool(name, arguments)
        structured = (
            result.payload if isinstance(result.payload, dict) else {"result": result.payload}
        )
        return CallToolResult(
            content=[TextContent(type="text", text=result.text)],
            structuredContent=structured,
            isError=result.is_error,
        )

    @server.list_resources()  # type: ignore[untyped-decorator]
    async def handle_list_resources() -> list[Any]:
        return resources

    @server.read_resource()  # type: ignore[untyped-decorator]
    async def handle_read_resource(uri: AnyUrl) -> str:
        return read_resource(uri)

    return server


def _api_key(settings: Settings) -> str | None:
    return settings.mcp_api_key.get_secret_value() if settings.mcp_api_key else None


def create_streamable_http_app(settings: Settings, server: Server[Any, Any]) -> ASGIApp:
    """Create the current MCP Streamable HTTP application."""
    session_manager = StreamableHTTPSessionManager(
        app=server,
        json_response=False,
        stateless=False,
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    app = Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=lifespan,
    )
    cors_app = CORSMiddleware(
        app,
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
    return HttpSecurityMiddleware(
        cors_app,
        api_key=_api_key(settings),
        allowed_origins=settings.cors_allowed_origins,
    )


def create_sse_app(settings: Settings, server: Server[Any, Any]) -> ASGIApp:
    """Create the legacy MCP SSE application."""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> PlainTextResponse:
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return PlainTextResponse("")

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
        debug=settings.log_level == "DEBUG",
    )
    cors_app = CORSMiddleware(
        app,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    return HttpSecurityMiddleware(
        cors_app,
        api_key=_api_key(settings),
        allowed_origins=settings.cors_allowed_origins,
    )


def create_openapi_app(settings: Settings, application: ToolApplication) -> ASGIApp:
    """Create the REST facade using the same execution core as MCP."""
    app = FastAPI(
        title="Unified Microsoft MCP API",
        description="OpenAPI interface for Azure CLI and Microsoft Graph tools",
        version="1.1.0",
    )
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
        execution = await application.execute_tool(
            "execute_azure_cli_command",
            request.model_dump(),
        )
        payload = execution.payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                pass
        return AzureCliResponse(result=payload)

    @app.post("/execute-graph-command", response_model=GraphResponse)
    async def execute_graph_command(request: GraphRequest) -> GraphResponse:
        execution = await application.execute_tool("graph_command", request.model_dump())
        return GraphResponse.model_validate(execution.payload)

    return HttpSecurityMiddleware(
        app,
        api_key=_api_key(settings),
        allowed_origins=settings.cors_allowed_origins,
        public_paths={"/docs", "/openapi.json", "/redoc"},
    )


async def run_transport(
    settings: Settings,
    server: Server[Any, Any],
    application: ToolApplication,
) -> None:
    """Run the selected transport until shutdown."""
    if settings.mcp_transport == "stdio":
        logger.info("Starting MCP stdio transport")
        async with stdio_server() as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )
        return

    if settings.mcp_transport == "streamable-http":
        app = create_streamable_http_app(settings, server)
    elif settings.mcp_transport == "sse":
        app = create_sse_app(settings, server)
    elif settings.mcp_transport == "openapi":
        app = create_openapi_app(settings, application)
    else:
        raise RuntimeError(f"Unsupported MCP transport: {settings.mcp_transport}")

    config = uvicorn.Config(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
    )
    await uvicorn.Server(config).serve()
