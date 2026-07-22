from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unified_mcp.config import Settings
from unified_mcp.main import main


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http", "sse", "openapi"])
async def test_composition_root_runs_and_closes_selected_transport(transport):
    settings = Settings(MCP_TRANSPORT=transport, MOCK_MODE=True)
    application = MagicMock()
    application.close = AsyncMock()
    server = MagicMock()

    with (
        patch("unified_mcp.main.Settings", return_value=settings),
        patch("unified_mcp.main.configure_logging"),
        patch("unified_mcp.main.build_application", return_value=application),
        patch("unified_mcp.main.create_mcp_server", return_value=server),
        patch("unified_mcp.main.run_transport", new=AsyncMock()) as run_transport,
    ):
        await main()

    run_transport.assert_awaited_once_with(settings, server, application)
    application.close.assert_awaited_once()
