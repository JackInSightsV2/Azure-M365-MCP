from unittest.mock import AsyncMock, MagicMock

import pytest

from unified_mcp.config import Settings
from unified_mcp.process import ProcessResult
from unified_mcp.services.azure_cli_service import AzureCliService


def test_validate_command(mock_azure_cli_service):
    assert mock_azure_cli_service._validate_command("az account list")
    assert mock_azure_cli_service._validate_command("az group show --name mygroup")
    assert not mock_azure_cli_service._validate_command("ls -la")
    assert not mock_azure_cli_service._validate_command("")
    # Metacharacters are literal because subprocess execution never invokes a shell.
    assert mock_azure_cli_service._validate_command("az account list; rm -rf /")


@pytest.mark.asyncio
async def test_execute_azure_cli_success(mock_azure_cli_service, mock_runner):
    mock_runner.run.return_value = ProcessResult(0, "[]", "")

    result = await mock_azure_cli_service.execute_azure_cli("az account list")

    assert result == "[]"
    mock_runner.run.assert_awaited_once_with(
        ["az", "account", "list"],
        timeout=mock_azure_cli_service.settings.command_timeout,
    )


@pytest.mark.asyncio
async def test_execute_azure_cli_failure(mock_azure_cli_service, mock_runner):
    mock_runner.run.return_value = ProcessResult(1, "", "Error message")

    result = await mock_azure_cli_service.execute_azure_cli("az invalid command")

    assert result == "Command: az invalid command\nError: Error message"


@pytest.mark.asyncio
async def test_configured_auth_failure_blocks_requested_command():
    settings = Settings(
        AZURE_APP_TENANT_ID="tenant",
        AZURE_APP_CLIENT_ID="client",
        AZURE_APP_CLIENT_SECRET="bad-secret",
    )
    runner = MagicMock()
    runner.run = AsyncMock(return_value=ProcessResult(1, "", "invalid credentials"))
    service = AzureCliService(settings, runner=runner)

    result = await service.execute_azure_cli("az account show")

    assert "command was not executed" in result
    assert "invalid credentials" in result
    runner.run.assert_awaited_once()
    assert runner.run.await_args.args[0][:3] == ["az", "login", "--service-principal"]


@pytest.mark.asyncio
async def test_managed_identity_authentication_uses_client_id():
    runner = MagicMock()
    runner.run = AsyncMock(return_value=ProcessResult(0, "[]", ""))
    service = AzureCliService(
        Settings(USE_MANAGED_IDENTITY=True, MANAGED_IDENTITY_CLIENT_ID="managed-client"),
        runner=runner,
    )

    result = await service._authenticate_managed_identity()

    assert result == "[]"
    runner.run.assert_awaited_once_with(
        ["az", "login", "--identity", "--client-id", "managed-client"],
        timeout=service.settings.command_timeout,
    )


@pytest.mark.asyncio
async def test_execute_azure_cli_invalid_input(mock_azure_cli_service):
    result = await mock_azure_cli_service.execute_azure_cli("ls -la")
    assert "Error: Invalid command" in result


def test_redact_sensitive_command(mock_azure_cli_service):
    redacted = mock_azure_cli_service._redact_sensitive_command(
        "az login --password secret --client-secret=key123"
    )
    assert "--password secret" not in redacted
    assert "key123" not in redacted
    assert "--password <REDACTED>" in redacted
    assert "--client-secret=<REDACTED>" in redacted
