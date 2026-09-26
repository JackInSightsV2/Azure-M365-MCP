import pytest

from unified_mcp.application import ToolApplication, create_tools
from unified_mcp.testing import FakeAzureCliService, FakeAzureRestService, FakeGraphService


def test_create_tools_exposes_azure_read_and_write():
    names = {tool.name for tool in create_tools()}
    assert names == {
        "azure_read",
        "azure_write",
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


def test_azure_tools_carry_read_and_destructive_hints():
    tools = {tool.name: tool for tool in create_tools()}

    assert tools["azure_read"].annotations.readOnlyHint is True
    assert tools["azure_read"].annotations.destructiveHint is False
    assert tools["azure_write"].annotations.readOnlyHint is False
    assert tools["azure_write"].annotations.destructiveHint is True


@pytest.mark.asyncio
async def test_azure_read_routes_cli_command_to_azure_cli():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_read", {"command": "az group list"})

    assert result.is_error is False
    assert "rg1" in result.text


@pytest.mark.asyncio
async def test_azure_read_routes_rest_path_to_arm_service():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool(
        "azure_read",
        {"command": "subscriptions?api-version=2022-12-01"},
    )

    assert result.is_error is False
    assert "Fake Subscription" in result.text


@pytest.mark.asyncio
async def test_azure_write_routes_rest_write_to_arm_service():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool(
        "azure_write",
        {
            "command": "subscriptions/s/resourcegroups/rg?api-version=2021-04-01",
            "method": "PUT",
            "data": {"location": "eastus"},
        },
    )

    assert result.is_error is False
    assert "Mock ARM response for PUT" in result.text


@pytest.mark.asyncio
async def test_azure_write_runs_cli_write_command():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_write", {"command": "az group create -n rg -l eastus"})

    assert result.is_error is False
    assert "Mock output for command: az group create" in result.text


@pytest.mark.asyncio
async def test_azure_read_rejects_cli_write_action():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_read", {"command": "az vm delete -n vm1 -g rg"})

    assert result.is_error is True
    assert "azure_write" in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_azure_read_rejects_non_get_rest_method(method):
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool(
        "azure_read",
        {"command": "subscriptions?api-version=2022-12-01", "method": method},
    )

    assert result.is_error is True
    assert "azure_write" in result.text


@pytest.mark.asyncio
async def test_azure_read_falls_back_to_arm_when_cli_absent():
    app = ToolApplication(None, FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_read", {"command": "az account list"})

    assert result.is_error is False
    assert "Fake Subscription" in result.text


@pytest.mark.asyncio
async def test_azure_read_falls_back_to_arm_when_cli_sign_in_fails():
    cli = FakeAzureCliService(failure="AADSTS53003: Access has been blocked by Conditional Access")
    app = ToolApplication(cli, FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_read", {"command": "az account list -o json"})

    assert result.is_error is False
    assert "Fake Subscription" in result.text


@pytest.mark.asyncio
async def test_cli_fallback_without_arm_mapping_suggests_arm_path():
    cli = FakeAzureCliService(failure="Please run 'az login' to setup account.")
    app = ToolApplication(cli, FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_read", {"command": "az vm list"})

    assert result.is_error is True
    assert "az login" in result.text
    assert "api-version" in result.text


@pytest.mark.asyncio
async def test_azure_rest_path_uses_cli_when_arm_service_disabled():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), arm_service=None)

    result = await app.execute_tool(
        "azure_read", {"command": "subscriptions?api-version=2022-12-01"}
    )

    assert result.is_error is False
    assert "az rest --method get" in result.text


@pytest.mark.asyncio
async def test_azure_without_any_service_is_error():
    app = ToolApplication(None, FakeGraphService(), arm_service=None)

    result = await app.execute_tool("azure_read", {"command": "az account list"})

    assert result.is_error is True
    assert "not available" in result.text


@pytest.mark.asyncio
async def test_azure_read_validates_command():
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_read", {})

    assert result.is_error is True
    assert "Missing command" in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["execute_azure_cli_command", "azure_rest_request"])
async def test_old_azure_tool_names_are_unknown(name):
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool(name, {"command": "az account list"})

    assert result.is_error is True
    assert "Unknown tool" in result.text


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

    for name in ("azure_read", "azure_write"):
        azure = tools[name]
        for term in (
            "azure",
            "subscriptions",
            "resource groups",
            "virtual machines",
            "storage",
            "networking",
            "role assignments",
            "cost",
            "azure cli",
            "resource manager",
            "conditional access",
        ):
            assert term in azure, (name, term)


def test_server_instructions_signal_microsoft_connection():
    from unified_mcp.application import SERVER_INSTRUCTIONS

    lowered = SERVER_INSTRUCTIONS.lower()
    assert "microsoft 365" in lowered
    assert "entra" in lowered
    # tool names remain present for clients that surface instructions
    assert "microsoft365_read" in SERVER_INSTRUCTIONS
    assert "microsoft365_write" in SERVER_INSTRUCTIONS
    assert "graph_command" not in SERVER_INSTRUCTIONS
    assert "azure_read" in SERVER_INSTRUCTIONS
    assert "azure_write" in SERVER_INSTRUCTIONS
    assert "execute_azure_cli_command" not in SERVER_INSTRUCTIONS
    assert "azure_rest_request" not in SERVER_INSTRUCTIONS
    for term in ("subscriptions", "resource groups", "virtual machines", "conditional access"):
        assert term in lowered, term
