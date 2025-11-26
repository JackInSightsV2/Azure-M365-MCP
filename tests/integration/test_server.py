import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from unified_mcp.main import process_tool_call

@pytest.mark.asyncio
async def test_handle_azure_cli_tool(mock_azure_cli_service):
    """Test Azure CLI tool handler."""
    mock_azure_cli_service.execute_azure_cli = AsyncMock(return_value="Success output")
    
    # Successful call
    result = await process_tool_call(
        "execute_azure_cli_command", 
        {"command": "az account list"},
        mock_azure_cli_service,
        None
    )
    
    assert len(result) == 1
    assert result[0].text == "Success output"
    mock_azure_cli_service.execute_azure_cli.assert_called_with("az account list")
    
    # Missing command
    result = await process_tool_call(
        "execute_azure_cli_command", 
        {},
        mock_azure_cli_service,
        None
    )
    assert "Error: Missing command argument" in result[0].text

    # Service not initialized
    result = await process_tool_call(
        "execute_azure_cli_command", 
        {"command": "az login"},
        None,
        None
    )
    assert "Error: Azure CLI service not initialized" in result[0].text

@pytest.mark.asyncio
async def test_handle_graph_tool(mock_graph_service):
    """Test Graph tool handler."""
    mock_graph_service.execute_command = AsyncMock(return_value={
        "success": True, 
        "data": {"key": "value"}
    })
    
    # Successful call
    result = await process_tool_call(
        "graph_command", 
        {"command": "me"},
        None,
        mock_graph_service
    )
    
    assert len(result) == 1
    assert "Success" in result[0].text
    assert '"key": "value"' in result[0].text
    mock_graph_service.execute_command.assert_called_with("me", "GET", None, None)
    
    # Error response
    mock_graph_service.execute_command = AsyncMock(return_value={
        "success": False, 
        "error": "Failed",
        "status_code": 404
    })
    
    result = await process_tool_call(
        "graph_command", 
        {"command": "me"},
        None,
        mock_graph_service
    )
    assert "Error" in result[0].text
    assert "Failed" in result[0].text

@pytest.mark.asyncio
async def test_handle_unknown_tool():
    """Test unknown tool handler."""
    result = await process_tool_call(
        "unknown_tool", 
        {},
        None,
        None
    )
    assert "Unknown tool" in result[0].text

