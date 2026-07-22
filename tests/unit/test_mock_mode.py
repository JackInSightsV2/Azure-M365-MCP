import json

import pytest

from unified_mcp.main import build_application
from unified_mcp.testing import FakeAzureCliService, FakeGraphService


@pytest.mark.asyncio
async def test_azure_cli_fake_adapter():
    service = FakeAzureCliService()

    login = json.loads(await service.execute_azure_cli("az login"))
    accounts = json.loads(await service.execute_azure_cli("az account list"))

    assert login[0]["user"]["type"] == "servicePrincipal"
    assert accounts[0]["name"] == "Fake Subscription"
    assert "Mock output" in await service.execute_azure_cli("az unknown command")


@pytest.mark.asyncio
async def test_graph_fake_adapter():
    service = FakeGraphService()

    me = await service.execute_command("me")
    users = await service.execute_command("users")

    assert me["data"]["displayName"] == "Mock User"
    assert len(users["data"]["value"]) == 2


def test_mock_mode_selects_fakes(mock_mode_settings):
    application = build_application(mock_mode_settings)

    assert isinstance(application.azure_service, FakeAzureCliService)
    assert isinstance(application.graph_service, FakeGraphService)


@pytest.fixture
def mock_mode_settings():
    from unified_mcp.config import Settings

    return Settings(MOCK_MODE=True)
