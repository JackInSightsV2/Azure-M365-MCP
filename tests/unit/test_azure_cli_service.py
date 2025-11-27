import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from unified_mcp.services.azure_cli_service import AzureCliService

@pytest.mark.asyncio
async def test_validate_command(mock_azure_cli_service):
    """Test command validation."""
    # Valid commands
    assert mock_azure_cli_service._validate_command("az account list")
    assert mock_azure_cli_service._validate_command("az group show --name mygroup")
    
    # Invalid commands
    assert not mock_azure_cli_service._validate_command("ls -la")
    assert not mock_azure_cli_service._validate_command("git status")
    assert not mock_azure_cli_service._validate_command("")
    
    # Dangerous characters
    assert not mock_azure_cli_service._validate_command("az account list; rm -rf /")
    assert not mock_azure_cli_service._validate_command("az account list && echo 'hacked'")

@pytest.mark.asyncio
async def test_sanitize_command(mock_azure_cli_service):
    """Test command sanitization."""
    command = "az group list; echo 'test'"
    sanitized = mock_azure_cli_service._sanitize_command(command)
    assert ";" not in sanitized
    assert "echo" in sanitized # It removes chars, not words, but checking specific dangerous chars is key
    
    # Check specific dangerous patterns removal
    assert mock_azure_cli_service._sanitize_command("az group list ||") == "az group list "
    assert mock_azure_cli_service._sanitize_command("az group list &&") == "az group list "

@pytest.mark.asyncio
async def test_execute_azure_cli_success(mock_azure_cli_service):
    """Test successful command execution."""
    # Restore the mocked method we want to test fully, but mock the subprocess part
    # Actually, the fixture mocked _run_azure_cli_command, which makes this test trivial.
    # We should unmock it or test _run_azure_cli_command directly via subprocess mock.
    
    with patch("asyncio.create_subprocess_shell") as mock_subprocess:
        # Configure mock process
        process_mock = AsyncMock()
        process_mock.communicate.return_value = (b"[]", b"")
        process_mock.returncode = 0
        mock_subprocess.return_value = process_mock
        
        # Unmock the method on the service instance to test the logic
        mock_azure_cli_service._run_azure_cli_command = AzureCliService._run_azure_cli_command.__get__(mock_azure_cli_service, AzureCliService)
        
        result = await mock_azure_cli_service.execute_azure_cli("az account list")
        
        assert result == "[]"
        mock_subprocess.assert_called_once()
        args, _ = mock_subprocess.call_args
        assert "az account list" in args[0]

@pytest.mark.asyncio
async def test_execute_azure_cli_failure(mock_azure_cli_service):
    """Test failed command execution."""
    with patch("asyncio.create_subprocess_shell") as mock_subprocess:
        process_mock = AsyncMock()
        process_mock.communicate.return_value = (b"", b"Error message")
        process_mock.returncode = 1
        mock_subprocess.return_value = process_mock
        
        mock_azure_cli_service._run_azure_cli_command = AzureCliService._run_azure_cli_command.__get__(mock_azure_cli_service, AzureCliService)
        
        result = await mock_azure_cli_service.execute_azure_cli("az invalid command")
        
        assert "Error: Error message" in result
        assert "Command: az invalid command" in result

@pytest.mark.asyncio
async def test_execute_azure_cli_invalid_input(mock_azure_cli_service):
    """Test execution with invalid input validation."""
    result = await mock_azure_cli_service.execute_azure_cli("ls -la")
    assert "Error: Invalid command" in result

@pytest.mark.asyncio
async def test_redact_sensitive_command(mock_azure_cli_service):
    """Test sensitive command redaction."""
    # Test password redaction
    command = "az login --username user --password secret123"
    redacted = mock_azure_cli_service._redact_sensitive_command(command)
    assert "--password <REDACTED>" in redacted
    assert "secret123" not in redacted
    
    # Test client-secret redaction
    command = "az login --client-secret mysecret"
    redacted = mock_azure_cli_service._redact_sensitive_command(command)
    assert "--client-secret <REDACTED>" in redacted
    assert "mysecret" not in redacted
    
    # Test with equals sign
    command = "az login --password=secret123"
    redacted = mock_azure_cli_service._redact_sensitive_command(command)
    assert "--password=<REDACTED>" in redacted
    assert "secret123" not in redacted
    
    # Test command without sensitive data remains unchanged
    command = "az account list"
    redacted = mock_azure_cli_service._redact_sensitive_command(command)
    assert redacted == command
    
    # Test multiple sensitive flags
    command = "az login --username user --password secret --client-secret key123"
    redacted = mock_azure_cli_service._redact_sensitive_command(command)
    assert "--password <REDACTED>" in redacted
    assert "--client-secret <REDACTED>" in redacted
    assert "secret" not in redacted
    assert "key123" not in redacted

