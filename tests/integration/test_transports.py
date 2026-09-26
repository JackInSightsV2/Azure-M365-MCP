import httpx
import pytest

from unified_mcp.application import SERVER_INSTRUCTIONS, ToolApplication
from unified_mcp.config import Settings
from unified_mcp.testing import FakeAzureCliService, FakeGraphService
from unified_mcp.transports import (
    create_mcp_server,
    create_openapi_app,
    create_sse_app,
    create_streamable_http_app,
)


def make_application():
    return ToolApplication(FakeAzureCliService(), FakeGraphService())


def test_mcp_initialization_includes_operational_instructions():
    server = create_mcp_server(Settings(), make_application())

    options = server.create_initialization_options()

    assert options.instructions == SERVER_INSTRUCTIONS
    assert "azure_read" in options.instructions
    assert "azure_write" in options.instructions
    assert "microsoft365_read" in options.instructions
    assert "microsoft365_write" in options.instructions
    assert "azure_find_resource" in options.instructions
    assert "kubernetes_connect" in options.instructions
    assert "kubernetes_read" in options.instructions
    assert "kubernetes_write" in options.instructions


@pytest.mark.asyncio
async def test_mcp_tool_list_follows_enable_kubernetes():
    from mcp.types import ListToolsRequest

    names = {}
    for enabled in (True, False):
        server = create_mcp_server(Settings(ENABLE_KUBERNETES=enabled), make_application())
        handler = server.request_handlers[ListToolsRequest]
        response = await handler(ListToolsRequest(method="tools/list"))
        names[enabled] = {tool.name for tool in response.root.tools}

    assert "kubernetes_read" in names[True]
    assert not {name for name in names[False] if name.startswith("kubernetes_")}


@pytest.mark.asyncio
async def test_openapi_uses_shared_tool_execution_core():
    app = create_openapi_app(Settings(MCP_TRANSPORT="openapi"), make_application())
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        azure = await client.post(
            "/execute-azure-cli",
            json={"command": "az account list"},
        )
        graph = await client.post(
            "/execute-graph-command",
            json={"command": "me"},
        )

    assert azure.status_code == 200
    assert azure.json()["result"][0]["name"] == "Fake Subscription"
    assert graph.status_code == 200
    assert graph.json()["data"]["displayName"] == "Mock User"


@pytest.mark.asyncio
@pytest.mark.parametrize("factory", [create_streamable_http_app, create_sse_app])
async def test_mcp_http_transports_share_health_contract(factory):
    settings = Settings(MCP_TRANSPORT="streamable-http")
    server = create_mcp_server(settings, make_application())
    app = factory(settings, server)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
