from unittest.mock import AsyncMock, MagicMock

import pytest
from azure.core.credentials import AccessToken

from unified_mcp.config import Settings
from unified_mcp.process import ProcessResult
from unified_mcp.services.azure_cli_service import AzureCliService
from unified_mcp.services.graph_service import GraphService


@pytest.fixture
def mock_env(monkeypatch):
    """Set deterministic credentials without touching the developer environment."""
    monkeypatch.setenv("AZURE_APP_TENANT_ID", "fake-tenant")
    monkeypatch.setenv("AZURE_APP_CLIENT_ID", "fake-client")
    monkeypatch.setenv("AZURE_APP_CLIENT_SECRET", "fake-secret")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "fake-graph-client")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_FILE", "test.log")


@pytest.fixture
def settings(mock_env):
    return Settings()


@pytest.fixture
def mock_runner():
    runner = MagicMock()
    runner.run = AsyncMock(return_value=ProcessResult(0, "[]", ""))
    return runner


@pytest.fixture
def mock_azure_cli_service(settings, mock_runner):
    service = AzureCliService(settings, runner=mock_runner)
    service._authenticated = True
    return service


@pytest.fixture
def mock_token_broker():
    broker = MagicMock()
    broker.get_token = AsyncMock(return_value=AccessToken("fake-token", 4_102_444_800))
    broker.close = AsyncMock()
    broker.is_application_identity = False
    return broker


@pytest.fixture
def mock_graph_service(settings, mock_token_broker):
    return GraphService(settings, token_broker=mock_token_broker)
