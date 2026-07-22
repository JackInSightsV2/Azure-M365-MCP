"""Azure CLI command execution and authentication gating."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex

from unified_mcp.auth import (
    InteractiveAzureProfile,
    ManagedIdentityProfile,
    ServicePrincipalProfile,
)
from unified_mcp.config import Settings
from unified_mcp.execution_policy import ExecutionPolicy
from unified_mcp.process import AsyncProcessRunner, ProcessResult, ProcessTimeoutError
from unified_mcp.services.azure_login_handler import AzureLoginHandler


class AzureCliService:
    """Execute validated Azure CLI commands under authentication and policy controls."""

    def __init__(
        self,
        settings: Settings,
        *,
        runner: AsyncProcessRunner | None = None,
        login_handler: AzureLoginHandler | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.auth_profile = settings.get_azure_auth_profile()
        self.runner = runner or AsyncProcessRunner()
        self.login_handler = login_handler or AzureLoginHandler(settings.command_timeout)
        self.policy = policy or settings.build_execution_policy()
        self._authenticated = False
        self._auth_lock = asyncio.Lock()
        self._command_semaphore = asyncio.Semaphore(settings.max_concurrent_commands)
        self.logger = logging.getLogger(__name__)

        self.logger.info(
            "AzureCliService initialized with %s authentication", self.auth_profile.kind
        )

    async def execute_azure_cli(self, command: str) -> str:
        """Execute an Azure CLI command after validation, policy, and configured auth."""
        redacted = self._redact_sensitive_command(command)
        self.logger.debug("Executing Azure CLI command: %s", redacted)

        if not self._validate_command(command):
            return "Error: Invalid command. Command must start with 'az'."

        decision = self.policy.check_azure(command)
        if not decision.allowed:
            return f"Error: Execution policy denied command - {decision.reason}"

        is_login = self._is_login_command(command)
        if not is_login and not isinstance(self.auth_profile, InteractiveAzureProfile):
            auth_error = await self._ensure_authenticated()
            if auth_error is not None:
                self.logger.error("Configured Azure authentication failed; command blocked")
                return (
                    "Error: Azure authentication failed; command was not executed. " f"{auth_error}"
                )

        try:
            return await self._run_azure_cli_command(command)
        except Exception as error:
            self.logger.error("Error executing Azure CLI command: %s", error)
            return f"Error: Command execution failed - {error}"

    async def _ensure_authenticated(self) -> str | None:
        """Authenticate exactly once, returning an error instead of falling through."""
        async with self._auth_lock:
            if self._authenticated:
                return None
            result = await self._authenticate_profile()
            if result.returncode != 0:
                return result.stderr or result.stdout or "Authentication failed"
            self._authenticated = True
            self.logger.info("Azure CLI authentication succeeded")
            return None

    async def _authenticate_profile(self) -> ProcessResult:
        profile = self.auth_profile
        if isinstance(profile, ManagedIdentityProfile):
            arguments = ["az", "login", "--identity"]
            if profile.client_id:
                arguments.extend(["--client-id", profile.client_id])
        elif isinstance(profile, ServicePrincipalProfile):
            arguments = [
                "az",
                "login",
                "--service-principal",
                "--tenant",
                profile.tenant_id,
                "--username",
                profile.client_id,
                "--password",
                profile.client_secret,
            ]
        else:
            return ProcessResult(0, "Using Azure CLI cached identity", "")

        try:
            return await self.runner.run(arguments, timeout=self.settings.command_timeout)
        except ProcessTimeoutError:
            return ProcessResult(1, "", "Azure CLI authentication timed out")
        except Exception as error:
            return ProcessResult(1, "", str(error))

    async def _authenticate_managed_identity(self) -> str:
        """Backward-compatible helper used by integrations and tests."""
        profile = self.auth_profile
        if not isinstance(profile, ManagedIdentityProfile):
            return "Error: Managed identity is not configured"
        result = await self._authenticate_profile()
        if result.returncode != 0:
            return f"Error: {result.stderr or 'Managed identity authentication failed'}"
        return result.stdout or "Authentication successful"

    def _validate_command(self, command: str) -> bool:
        if not command or not command.strip() or "\x00" in command:
            return False
        try:
            arguments = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            return False
        return bool(arguments) and arguments[0].lower() == "az"

    @staticmethod
    def _is_login_command(command: str) -> bool:
        try:
            arguments = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            return False
        return arguments[:2] == ["az", "login"]

    def _redact_sensitive_command(self, command: str) -> str:
        sensitive_flags = [
            (r"--password\s+\S+", "--password <REDACTED>"),
            (r"--password=\S+", "--password=<REDACTED>"),
            (r"--client-secret\s+\S+", "--client-secret <REDACTED>"),
            (r"--client-secret=\S+", "--client-secret=<REDACTED>"),
            (r"--secret\s+\S+", "--secret <REDACTED>"),
            (r"--secret=\S+", "--secret=<REDACTED>"),
            (r"--key\s+\S+", "--key <REDACTED>"),
            (r"--key=\S+", "--key=<REDACTED>"),
            (r"--api-key\s+\S+", "--api-key <REDACTED>"),
            (r"--api-key=\S+", "--api-key=<REDACTED>"),
        ]
        redacted = command
        for pattern, replacement in sensitive_flags:
            redacted = re.sub(pattern, replacement, redacted)
        return redacted

    async def _run_azure_cli_command(self, command: str) -> str:
        arguments = shlex.split(command, posix=os.name != "nt")
        interactive_login = arguments[:2] == ["az", "login"] and not {
            "--service-principal",
            "--identity",
            "--federated-token",
        }.intersection(arguments)
        if interactive_login:
            return await self.login_handler.handle_az_login_command(command)

        try:
            async with self._command_semaphore:
                result = await self.runner.run(arguments, timeout=self.settings.command_timeout)
        except ProcessTimeoutError:
            return f"Error: Command timed out\nCommand: {self._redact_sensitive_command(command)}"
        except Exception as process_error:
            return f"Error: {process_error}\nCommand: {self._redact_sensitive_command(command)}"

        if result.returncode != 0:
            error_message = result.stderr or "Command failed"
            return f"Command: {self._redact_sensitive_command(command)}\nError: {error_message}"
        return "\n".join(part for part in (result.stdout, result.stderr) if part).strip()

    async def close(self) -> None:
        """Terminate any interactive login still owned by this service."""
        await self.login_handler.close()
