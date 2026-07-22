from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unified_mcp.main import main


def make_settings(transport: str, port: int = 8000) -> MagicMock:
    """Return complete settings for startup tests."""
    settings = MagicMock()
    settings.mcp_transport = transport
    settings.mcp_host = "127.0.0.1"
    settings.mcp_port = port
    settings.mcp_api_key = None
    settings.mcp_server_name = "test-server"
    settings.cors_allowed_origins = ["http://localhost:8000"]
    settings.log_level = "INFO"
    settings.log_file = "test.log"
    settings.command_timeout = 30
    settings.max_concurrent_commands = 2
    settings.operation_timeout = 30
    settings.max_concurrent_operations = 2
    settings.mock_mode = True
    settings.share_app_registration = False
    settings.use_managed_identity = False
    settings.managed_identity_client_id = None
    settings.is_graph_read_only_mode = True
    settings.has_azure_credentials.return_value = False
    settings.get_azure_credentials_json.return_value = None
    settings.get_graph_client_secret.return_value = None
    settings.get_graph_auth_config.return_value = {
        "mode": "default",
        "client_id": "test-client",
        "tenant_id": "common",
        "scopes": ["User.Read"],
    }
    return settings


@pytest.mark.asyncio
async def test_server_startup_stdio():
    """Test server startup in stdio mode."""
    with (
        patch("unified_mcp.main.Settings") as mock_settings_cls,
        patch("unified_mcp.main.stdio_server") as mock_stdio_server,
        patch("unified_mcp.main.Server") as mock_server_cls,
    ):

        # Configure settings for stdio
        mock_settings = make_settings("stdio")
        mock_settings_cls.return_value = mock_settings

        # Mock server instance
        mock_server = MagicMock()
        # Mock methods to return decorators that return the function passed to them
        mock_server.list_tools.return_value = lambda f: f
        mock_server.call_tool.return_value = lambda f: f
        mock_server.list_resources.return_value = lambda f: f
        mock_server.read_resource.return_value = lambda f: f

        # Mock run method which is awaited
        mock_server.run = AsyncMock()
        mock_server.create_initialization_options = MagicMock()

        mock_server_cls.return_value = mock_server

        # Mock stdio context manager
        mock_streams = (AsyncMock(), AsyncMock())
        mock_stdio_server.return_value.__aenter__.return_value = mock_streams

        await main()

        # Verify stdio server was initialized and run
        mock_stdio_server.assert_called_once()
        mock_server.run.assert_called_once()


@pytest.mark.asyncio
async def test_server_startup_streamable_http():
    """Test server startup in the current MCP HTTP mode."""
    with (
        patch("unified_mcp.main.Settings") as mock_settings_cls,
        patch("unified_mcp.main.uvicorn") as mock_uvicorn,
        patch("unified_mcp.main.StreamableHTTPSessionManager") as mock_session_manager,
        patch("unified_mcp.main.Server") as mock_server_cls,
    ):
        mock_settings_cls.return_value = make_settings("streamable-http")

        mock_server = MagicMock()
        mock_server.list_tools.return_value = lambda f: f
        mock_server.call_tool.return_value = lambda f: f
        mock_server.list_resources.return_value = lambda f: f
        mock_server.read_resource.return_value = lambda f: f
        mock_server_cls.return_value = mock_server

        mock_uvicorn_server = AsyncMock()
        mock_uvicorn.Server.return_value = mock_uvicorn_server

        await main()

        mock_session_manager.assert_called_once()
        mock_uvicorn.Config.assert_called_once()
        mock_uvicorn_server.serve.assert_called_once()


@pytest.mark.asyncio
async def test_server_startup_sse():
    """Test server startup in SSE mode."""
    with (
        patch("unified_mcp.main.Settings") as mock_settings_cls,
        patch("unified_mcp.main.uvicorn") as mock_uvicorn,
        patch("unified_mcp.main.SseServerTransport") as mock_sse_transport,
        patch("unified_mcp.main.Server") as mock_server_cls,
    ):

        # Configure settings for SSE
        mock_settings = make_settings("sse")
        # Mock credential checks
        mock_settings.has_azure_credentials.return_value = True
        mock_settings.share_app_registration = False
        mock_settings.is_graph_read_only_mode = False
        mock_settings.get_graph_client_secret.return_value = "secret"
        mock_settings_cls.return_value = mock_settings

        # Mock server
        mock_server = MagicMock()
        # Mock methods to return decorators that return the function passed to them
        mock_server.list_tools.return_value = lambda f: f
        mock_server.call_tool.return_value = lambda f: f
        mock_server.list_resources.return_value = lambda f: f
        mock_server.read_resource.return_value = lambda f: f

        # Mock run method which is awaited
        mock_server.run = AsyncMock()
        mock_server.create_initialization_options = MagicMock()

        mock_server_cls.return_value = mock_server

        # Mock uvicorn server
        mock_uvicorn_server = AsyncMock()
        mock_uvicorn.Server.return_value = mock_uvicorn_server

        await main()

        # Verify SSE transport and uvicorn were initialized
        mock_sse_transport.assert_called_once()
        mock_uvicorn.Config.assert_called_once()
        mock_uvicorn_server.serve.assert_called_once()


@pytest.mark.asyncio
async def test_server_startup_openapi():
    """Test server startup in OpenAPI mode."""
    with (
        patch("unified_mcp.main.Settings") as mock_settings_cls,
        patch("unified_mcp.main.uvicorn") as mock_uvicorn,
        patch("unified_mcp.main.FastAPI") as mock_fastapi,
    ):

        # Configure settings for OpenAPI
        mock_settings = make_settings("openapi")
        mock_settings_cls.return_value = mock_settings

        # Mock uvicorn server
        mock_uvicorn_server = AsyncMock()
        mock_uvicorn.Server.return_value = mock_uvicorn_server

        await main()

        # Verify FastAPI and uvicorn were initialized
        mock_fastapi.assert_called_once()
        mock_uvicorn.Config.assert_called_once()
        mock_uvicorn_server.serve.assert_called_once()
