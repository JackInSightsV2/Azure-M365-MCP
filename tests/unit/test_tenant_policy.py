from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.core.exceptions import ClientAuthenticationError

from unified_mcp.application import ToolApplication
from unified_mcp.config import Settings
from unified_mcp.process import ProcessResult
from unified_mcp.services.azure_cli_service import AzureCliService
from unified_mcp.services.azure_rest_service import AzureRestService
from unified_mcp.services.graph_service import GraphService
from unified_mcp.tenant_policy import (
    AZURE_CLI_CLIENT_ID,
    POLICY_ERROR_CODES,
    detect_tenant_policy_refusal,
)
from unified_mcp.testing import FakeAzureCliService, FakeAzureRestService, FakeGraphService

GRAPH_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
ARM_CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"

CONSENT_ERROR = (
    "DeviceCodeCredential authentication failed: AADSTS65001: The user or administrator "
    "has not consented to use the application with ID "
    f"'{GRAPH_CLIENT_ID}' named 'Microsoft Graph Command Line Tools'."
)
CONDITIONAL_ACCESS_ERROR = (
    "AADSTS53003: Access has been blocked by Conditional Access policies. "
    "The access policy does not allow token issuance."
)


def _failing_broker(message: str) -> MagicMock:
    broker = MagicMock()
    broker.get_token = AsyncMock(side_effect=ClientAuthenticationError(message))
    broker.close = AsyncMock()
    return broker


# --- mapping -----------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(POLICY_ERROR_CODES))
def test_every_policy_code_is_recognised(code):
    refusal = detect_tenant_policy_refusal(f"{code}: refused", "client-a")

    assert refusal is not None
    assert refusal.code == code
    assert refusal.client_id == "client-a"
    assert "client-a" in refusal.message
    assert "tenant admin" in refusal.message


def test_client_id_reported_by_entra_wins_over_configured():
    refusal = detect_tenant_policy_refusal(CONSENT_ERROR, "configured-client")

    assert refusal is not None
    assert refusal.client_id == GRAPH_CLIENT_ID
    assert "admin consent" in refusal.message


def test_conditional_access_names_the_policy():
    refusal = detect_tenant_policy_refusal(CONDITIONAL_ACCESS_ERROR, ARM_CLIENT_ID)

    assert refusal is not None
    assert refusal.code == "AADSTS53003"
    assert ARM_CLIENT_ID in refusal.message
    assert "Conditional Access" in refusal.message


def test_similar_code_prefix_is_not_confused():
    # AADSTS530032 must not be read as AADSTS53003, nor an unknown code as a refusal.
    assert detect_tenant_policy_refusal("AADSTS530032: blocked").code == "AADSTS530032"
    assert detect_tenant_policy_refusal("AADSTS530039: something else") is None


@pytest.mark.parametrize(
    "error",
    [
        None,
        "",
        "AADSTS7000215: Invalid client secret provided.",
        "AADSTS50126: Error validating credentials due to invalid username or password.",
        "network unreachable",
    ],
)
def test_other_errors_are_not_policy_refusals(error):
    assert detect_tenant_policy_refusal(error, "client") is None


def test_unknown_client_id_still_gives_plain_message():
    refusal = detect_tenant_policy_refusal("AADSTS90094: admin consent required")

    assert refusal is not None
    assert refusal.client_id is None
    assert "Refused app." in refusal.message


# --- tool execution ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_tool_returns_plain_message_on_consent_refusal():
    graph = GraphService(Settings(), token_broker=_failing_broker(CONSENT_ERROR))
    app = ToolApplication(FakeAzureCliService(), graph, FakeAzureRestService())

    result = await app.execute_tool("microsoft365_read", {"command": "me"})

    assert result.is_error is True
    assert "Tenant policy (AADSTS65001)" in result.text
    assert f"client ID {GRAPH_CLIENT_ID}" in result.text
    assert "Ask a tenant admin to grant admin consent" in result.text
    assert result.payload["tenant_policy"] is True
    assert result.payload["client_id"] == GRAPH_CLIENT_ID


@pytest.mark.asyncio
async def test_graph_tool_policy_refusal_replaces_stale_device_code():
    graph = GraphService(Settings(), token_broker=_failing_broker(CONDITIONAL_ACCESS_ERROR))
    graph.device_code_info = {
        "verification_uri": "https://microsoft.com/devicelogin",
        "user_code": "OLDCODE",
        "expires_in": 600,
    }
    app = ToolApplication(FakeAzureCliService(), graph, FakeAzureRestService())

    result = await app.execute_tool("microsoft365_read", {"command": "me"})

    assert "AADSTS53003" in result.text
    assert "OLDCODE" not in result.text
    assert graph.device_code_info is None


@pytest.mark.asyncio
async def test_graph_tool_other_auth_errors_unchanged():
    graph = GraphService(Settings(), token_broker=_failing_broker("AADSTS50126: bad password"))
    app = ToolApplication(FakeAzureCliService(), graph, FakeAzureRestService())

    result = await app.execute_tool("microsoft365_read", {"command": "me"})

    assert result.is_error is True
    assert "Authentication failed: AADSTS50126: bad password" in result.text
    assert "tenant_policy" not in result.payload


@pytest.mark.asyncio
async def test_azure_rest_tool_returns_plain_message_on_conditional_access():
    arm = AzureRestService(Settings(), token_broker=_failing_broker(CONDITIONAL_ACCESS_ERROR))
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), arm)

    result = await app.execute_tool("azure_read", {"command": "subscriptions"})

    assert result.is_error is True
    assert "Tenant policy (AADSTS53003)" in result.text
    assert f"client ID {ARM_CLIENT_ID}" in result.text
    assert "tenant admin" in result.text


@pytest.mark.asyncio
async def test_azure_cli_tool_returns_plain_message_on_policy_refusal():
    runner = MagicMock()
    runner.run = AsyncMock(return_value=ProcessResult(1, "", CONDITIONAL_ACCESS_ERROR))
    cli = AzureCliService(Settings(), runner=runner)
    app = ToolApplication(cli, FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_read", {"command": "az account show"})

    assert result.is_error is True
    assert result.text.startswith("Error: Sign-in was refused")
    assert f"client ID {AZURE_CLI_CLIENT_ID}" in result.text
    runner.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_azure_cli_tool_explains_failed_device_login():
    runner = MagicMock()
    runner.run = AsyncMock(
        return_value=ProcessResult(1, "", "Please run 'az login' to setup account.")
    )
    cli = AzureCliService(Settings(), runner=runner)
    cli.login_handler.last_login_error = f"{CONSENT_ERROR}"
    app = ToolApplication(cli, FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_read", {"command": "az account show"})

    assert result.is_error is True
    assert "AADSTS65001" in result.text
    assert "tenant admin" in result.text


@pytest.mark.asyncio
async def test_azure_cli_service_principal_refusal_names_configured_app():
    runner = MagicMock()
    runner.run = AsyncMock(return_value=ProcessResult(1, "", "AADSTS7000112: app disabled"))
    settings = Settings(
        AZURE_APP_TENANT_ID="tenant",
        AZURE_APP_CLIENT_ID="sp-client",
        AZURE_APP_CLIENT_SECRET="secret",
    )
    app = ToolApplication(
        AzureCliService(settings, runner=runner), FakeGraphService(), FakeAzureRestService()
    )

    result = await app.execute_tool("azure_read", {"command": "az account show"})

    assert result.is_error is True
    assert "client ID sp-client" in result.text
    assert "enable this app" in result.text


@pytest.mark.asyncio
async def test_azure_cli_tool_other_errors_unchanged():
    runner = MagicMock()
    runner.run = AsyncMock(return_value=ProcessResult(1, "", "ResourceGroupNotFound"))
    cli = AzureCliService(Settings(), runner=runner)
    app = ToolApplication(cli, FakeGraphService(), FakeAzureRestService())

    result = await app.execute_tool("azure_read", {"command": "az group show"})

    assert result.text == "Command: az group show\nError: ResourceGroupNotFound"
