import pytest

from unified_mcp.application import ToolApplication, create_tools
from unified_mcp.testing import FakeAzureCliService, FakeAzureRestService, FakeGraphService


def test_create_tools_exposes_azure_rest_request():
    names = {tool.name for tool in create_tools()}
    assert names == {
        "execute_azure_cli_command",
        "azure_rest_request",
        "microsoft365_read",
        "microsoft365_write",
    }


def test_microsoft365_tools_carry_read_and_write_hints():
    tools = {tool.name: tool for tool in create_tools()}

    read = tools["microsoft365_read"].annotations
    assert read is not None and read.readOnlyHint is True

    write = tools["microsoft365_write"].annotations
    assert write is not None and write.destructiveHint is True
    assert write.readOnlyHint is not True


@pytest.mark.asyncio
async def test_microsoft365_read_routes_get_to_graph():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("microsoft365_read", {"command": "me"})

    assert result.is_error is False
    assert "Mock User" in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_microsoft365_read_rejects_write_methods(method):
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool(
        "microsoft365_read",
        {"command": "users/specific-id", "method": method},
    )

    assert result.is_error is True
    assert "microsoft365_write" in result.text


@pytest.mark.asyncio
async def test_microsoft365_write_routes_patch_to_graph():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool(
        "microsoft365_write",
        {"command": "users/specific-id", "method": "PATCH", "data": {"jobTitle": "Lead"}},
    )

    assert result.is_error is False
    assert "PATCH users/specific-id" in result.text


@pytest.mark.asyncio
async def test_microsoft365_write_rejects_get():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("microsoft365_write", {"command": "me", "method": "GET"})

    assert result.is_error is True
    assert "microsoft365_read" in result.text


@pytest.mark.asyncio
async def test_graph_command_name_is_removed():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("graph_command", {"command": "me"})

    assert result.is_error is True
    assert "Unknown tool" in result.text


@pytest.mark.asyncio
async def test_azure_rest_request_routes_to_arm_service():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool(
        "azure_rest_request",
        {"command": "subscriptions?api-version=2022-12-01"},
    )

    assert result.is_error is False
    assert "Fake Subscription" in result.text


@pytest.mark.asyncio
async def test_azure_rest_request_without_service_is_error():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), arm_service=None)

    result = await app.execute_tool("azure_rest_request", {"command": "subscriptions"})

    assert result.is_error is True
    assert "not enabled" in result.text


@pytest.mark.asyncio
async def test_azure_rest_request_validates_command():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_rest_request", {})

    assert result.is_error is True
    assert "Missing command" in result.text


def test_tool_descriptions_use_intent_keywords():
    """Descriptions must carry the everyday terms users phrase requests in, so the
    model matches intent to a tool instead of answering from general knowledge."""
    tools = {t.name: t.description.lower() for t in create_tools()}

    for name in ("microsoft365_read", "microsoft365_write"):
        graph = tools[name]
        assert "microsoft 365" in graph, name
        assert "m365" in graph and "office 365" in graph, name
        assert "entra" in graph and "azure ad" in graph, name
        for term in ("users", "mail", "teams", "groups", "licences", "licenses"):
            assert term in graph, (name, term)
    assert "sign-in" in tools["microsoft365_read"]

    azure_cli = tools["execute_azure_cli_command"]
    assert "azure" in azure_cli and "subscription" in azure_cli

    arm = tools["azure_rest_request"]
    assert "conditional access" in arm and "resource manager" in arm


def test_server_instructions_signal_microsoft_connection():
    from unified_mcp.application import SERVER_INSTRUCTIONS

    lowered = SERVER_INSTRUCTIONS.lower()
    assert "microsoft 365" in lowered
    assert "entra" in lowered
    # tool names remain present for clients that surface instructions
    assert "microsoft365_read" in SERVER_INSTRUCTIONS
    assert "microsoft365_write" in SERVER_INSTRUCTIONS
    assert "graph_command" not in SERVER_INSTRUCTIONS
    assert "execute_azure_cli_command" in SERVER_INSTRUCTIONS
