from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_client_secret_missing(mock_graph_service):
    """Test response when client secret is missing for custom app."""
    # Force custom mode configuration
    mock_graph_service.auth_config = {
        "mode": "custom",
        "client_id": "id",
        "tenant_id": "tenant",
        "auth_mode": "client_secret",
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

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_response
    mock_graph_service._get_http_client = MagicMock(return_value=mock_client)

    result = await mock_graph_service.execute_command("users")

    assert result["success"] is True
    assert result["data"]["value"][0]["displayName"] == "User"
    mock_client.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_command_post(mock_graph_service):
    """Test POST command execution."""
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": "new-id"}

    data = {"displayName": "New User"}

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_response
    mock_graph_service._get_http_client = MagicMock(return_value=mock_client)

    result = await mock_graph_service.execute_command("users", method="POST", data=data)

    assert result["success"] is True
    assert result["status_code"] == 201
    mock_client.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_command_error(mock_graph_service):
    """Test API error handling."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"error": {"message": "User not found"}}

    mock_client = AsyncMock()
    mock_client.request.return_value = mock_response
    mock_graph_service._get_http_client = MagicMock(return_value=mock_client)

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

    # Patch the active loop to return a failing token-acquisition future
    with patch("asyncio.get_running_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.run_in_executor.return_value = future
        mock_get_loop.return_value = mock_loop

        result = await mock_graph_service.execute_command("me")

        assert result["success"] is False
        assert result["auth_required"] is True
        assert "Authentication failed" in result["error"]
