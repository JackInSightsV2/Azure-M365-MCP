import pytest
import json
from unittest.mock import patch, MagicMock
from unified_mcp.services.azure_cli_service import AzureCliService
from unified_mcp.services.graph_service import GraphService
from unified_mcp.config import Settings

@pytest.fixture
def mock_mode_settings():
    return Settings(MOCK_MODE=True, AZURE_APP_TENANT_ID="test", AZURE_APP_CLIENT_ID="test", AZURE_APP_CLIENT_SECRET="test")

@pytest.mark.asyncio
async def test_azure_cli_mock_mode(mock_mode_settings):
    """Test Azure CLI service in Mock Mode."""
    service = AzureCliService(mock_mode_settings)
    
    # Test login mock
    result = await service.execute_azure_cli("az login")
    data = json.loads(result)
    assert data[0]["state"] == "Enabled"
    assert data[0]["user"]["type"] == "servicePrincipal"
    
    # Test account list mock
    result = await service.execute_azure_cli("az account list")
    data = json.loads(result)
    assert data[0]["name"] == "Fake Subscription"
    
    # Test other command mock
    result = await service.execute_azure_cli("az unknown command")
    assert "Mock output for command" in result

@pytest.mark.asyncio
async def test_graph_mock_mode(mock_mode_settings):
    """Test Graph service in Mock Mode."""
    service = GraphService(mock_mode_settings)
    
    # Test 'me' endpoint mock
    result = await service.execute_command("me")
    assert result["success"] is True
    assert result["data"]["displayName"] == "Mock User"
    
    # Test 'users' endpoint mock
    result = await service.execute_command("users")
    assert result["success"] is True
    assert len(result["data"]["value"]) == 2
    
    # Test fallback mock
    result = await service.execute_command("groups")
    assert result["success"] is True
    assert "Mock response" in result["data"]["message"]

