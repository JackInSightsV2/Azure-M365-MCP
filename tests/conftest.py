import os
import pytest
from unittest.mock import MagicMock, AsyncMock

from unified_mcp.config import Settings
from unified_mcp.services.azure_cli_service import AzureCliService
from unified_mcp.services.graph_service import GraphService

@pytest.fixture
def mock_env(monkeypatch):
    """Mock environment variables."""
    monkeypatch.setenv("AZURE_APP_TENANT_ID", "fake-tenant")
    monkeypatch.setenv("AZURE_APP_CLIENT_ID", "fake-client")
    monkeypatch.setenv("AZURE_APP_CLIENT_SECRET", "fake-secret")
    monkeypatch.setenv("GRAPH_CLIENT_ID", "fake-graph-client")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_FILE", "test.log")

@pytest.fixture
def settings(mock_env):
    """Create settings instance with mocked environment."""
    return Settings()

@pytest.fixture
def mock_azure_cli_service(settings):
    """Create a mocked AzureCliService."""
    service = AzureCliService(settings)
    # Mock the internal methods that interact with system
    service._run_azure_cli_command = AsyncMock()
    service._authenticate = AsyncMock(return_value="Authentication successful")
    return service

@pytest.fixture
def mock_graph_service(settings):
    """Create a mocked GraphService."""
    service = GraphService(settings)
    # Mock credential and http client interaction
    service.credential = MagicMock()
    service.credential.get_token = MagicMock(return_value=MagicMock(token="fake-token"))
    return service

