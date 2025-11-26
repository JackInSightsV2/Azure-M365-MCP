import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from unified_mcp.services.graph_service import GraphService

@pytest.mark.asyncio
async def test_get_client_secret_missing(mock_graph_service):
    """Test response when client secret is missing for custom app."""
    # Force custom mode configuration
    mock_graph_service.auth_config = {
        "mode": "custom", 
        "client_id": "id", 
        "tenant_id": "tenant",
        "auth_mode": "client_secret"
    }
    mock_graph_service.client_secret = None
    
    result = await mock_graph_service._get_client_secret()
    
    assert result["success"] is False
    assert result["auth_required"] is True
    assert result["auth_type"] == "client_secret"

@pytest.mark.asyncio
async def test_execute_command_success(mock_graph_service):
    """Test successful command execution."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"value": [{"displayName": "User"}]}
    
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        
        result = await mock_graph_service.execute_command("users")
        
        assert result["success"] is True
        assert result["data"]["value"][0]["displayName"] == "User"
        mock_client.get.assert_called_once()

@pytest.mark.asyncio
async def test_execute_command_post(mock_graph_service):
    """Test POST command execution."""
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": "new-id"}
    
    data = {"displayName": "New User"}
    
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        
        result = await mock_graph_service.execute_command("users", method="POST", data=data)
        
        assert result["success"] is True
        assert result["status_code"] == 201
        mock_client.post.assert_called_once()

@pytest.mark.asyncio
async def test_execute_command_error(mock_graph_service):
    """Test API error handling."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"error": {"message": "User not found"}}
    
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        
        result = await mock_graph_service.execute_command("users/invalid")
        
        assert result["success"] is False
        assert result["status_code"] == 404
        assert "User not found" in result["error"]

@pytest.mark.asyncio
async def test_auth_failure_handling(mock_graph_service):
    """Test handling of authentication failures."""
    import asyncio
    
    # Create a Future that fails immediately
    future = asyncio.Future()
    future.set_exception(Exception("Auth failed"))
    
    # Patch get_event_loop to return a mock loop that returns our failing future
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor.return_value = future
        mock_get_loop.return_value = mock_loop
        
        result = await mock_graph_service.execute_command("me")
        
        assert result["success"] is False
        assert result["auth_required"] is True
        assert "Authentication failed" in result["error"]

