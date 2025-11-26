"""Azure CLI Service for executing Azure CLI commands."""

import asyncio
import json
import logging
import os
import re
import subprocess
from typing import Optional

from unified_mcp.config import Settings
from unified_mcp.services.azure_login_handler import AzureLoginHandler


class AzureCliService:
    """Service for executing Azure CLI commands."""

    def __init__(self, settings: Settings):
        """Initialize Azure CLI service."""
        self.settings = settings
        self.login_handler = AzureLoginHandler()
        self._authenticated = False  # Track authentication status

        # Set up logger
        self.logger = logging.getLogger(__name__)

        # Configure logging
        log_level = getattr(logging, settings.log_level.upper())

        # Ensure log directory exists
        log_dir = os.path.dirname(settings.log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(settings.log_file), logging.StreamHandler()],
        )

        # Set the logger level for this specific logger
        self.logger.setLevel(log_level)

        self.logger.info("AzureCliService initialized")

        # Note: Don't create async tasks in __init__ - handle authentication separately
        if settings.has_azure_credentials():
            self.logger.info("Azure credentials available for authentication")
        else:
            self.logger.warning("No Azure credentials provided")

    async def execute_azure_cli(self, command: str) -> str:
        """Execute Azure CLI command with validation and error handling."""
        self.logger.info(f"Executing Azure CLI command: {command}")

        # Validate command
        if not self._validate_command(command):
            self.logger.error(f"Invalid command: {command}")
            return "Error: Invalid command. Command must start with 'az'."

        # Sanitize command
        sanitized_command = self._sanitize_command(command)

        # Auto-authenticate if credentials are available and not already authenticated
        # Skip if this is already a login command
        if not sanitized_command.startswith("az login") and not self._authenticated:
            if self.settings.mock_mode:
                self.logger.info("Mock mode enabled - skipping authentication")
                self._authenticated = True
            elif self.settings.has_azure_credentials():
                self.logger.info("Auto-authenticating with service principal credentials")
                credentials_json = self.settings.get_azure_credentials_json()
                if credentials_json:
                    auth_result = await self._authenticate(credentials_json)
                    # Check if authentication succeeded by verifying the result doesn't start with "Error:"
                    # The _authenticate method returns "Error: ..." on failure, so we check the prefix
                    if auth_result and not auth_result.startswith("Error:"):
                        self._authenticated = True
                        self.logger.info("Successfully authenticated with Azure CLI")
                    else:
                        self.logger.warning(f"Authentication may have failed: {auth_result}")

        try:
            output = await self._run_azure_cli_command(sanitized_command)
            self.logger.info(f"Azure CLI command output: {output}")
            return output
        except Exception as e:
            self.logger.error(f"Error executing Azure CLI command: {e}")
            return f"Error: Command execution failed - {str(e)}"

    def _validate_command(self, command: str) -> bool:
        """Validate Azure CLI command."""
        if not command or not command.strip():
            return False

        command = command.strip()

        # Must start with 'az'
        if not command.startswith("az "):
            return False

        # Check for command injection attempts
        dangerous_chars = [";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\r"]
        if any(char in command for char in dangerous_chars):
            return False

        return True

    def _sanitize_command(self, command: str) -> str:
        """Sanitize Azure CLI command."""
        # Basic sanitization - remove dangerous characters
        command = command.strip()

        # Remove potential command injection characters
        dangerous_patterns = [
            r"[;&|`$<>\n\r]",  # Shell metacharacters
            r"\|\|",  # OR operator
            r"&&",  # AND operator
        ]

        for pattern in dangerous_patterns:
            command = re.sub(pattern, "", command)

        return command

    async def _authenticate(self, azure_credentials: str) -> Optional[str]:
        """Authenticate using service principal credentials."""
        try:
            # Read and parse the JSON credentials
            credentials = json.loads(azure_credentials)

            tenant_id = credentials.get("tenantId")
            client_id = credentials.get("clientId")
            client_secret = credentials.get("clientSecret")

            if not all([tenant_id, client_id, client_secret]):
                self.logger.error(
                    "Missing required credentials: tenantId, clientId, or clientSecret"
                )
                return None

            login_command = (
                f"az login --service-principal --tenant {tenant_id} "
                f"--username {client_id} --password {client_secret}"
            )

            # Use direct command execution for service principal (bypass device code handler)
            self.logger.info(f"Authenticating with service principal: {client_id}")
            process = await asyncio.create_subprocess_shell(
                login_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True,
            )

            stdout, stderr = await process.communicate()

            stdout_text = stdout.decode("utf-8") if stdout else ""
            stderr_text = stderr.decode("utf-8") if stderr else ""

            if process.returncode != 0:
                error_msg = stderr_text if stderr_text else "Authentication failed"
                self.logger.error(f"Azure CLI authentication failed: {error_msg}")
                return f"Error: {error_msg}"

            result = stdout_text if stdout_text else "Authentication successful"
            self.logger.info(f"Azure CLI login result: {result}")
            return result

        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing Azure credentials: {e}")
            return f"Error: {str(e)}"
        except Exception as e:
            self.logger.error(f"Error during Azure CLI authentication: {e}")
            return f"Error: {str(e)}"

    async def _run_azure_cli_command(self, command: str) -> str:
        """Run Azure CLI command asynchronously."""
        # Handle Mock Mode
        if self.settings.mock_mode:
            self.logger.info(f"MOCK MODE: Returning fake response for '{command}'")
            if command.startswith("az login"):
                return json.dumps([
                    {
                        "cloudName": "AzureCloud",
                        "homeTenantId": "fake-tenant-id",
                        "id": "fake-subscription-id",
                        "isDefault": True,
                        "managedByTenants": [],
                        "name": "Fake Subscription",
                        "state": "Enabled",
                        "tenantId": "fake-tenant-id",
                        "user": {
                            "name": "fake-service-principal",
                            "type": "servicePrincipal"
                        }
                    }
                ], indent=2)
            elif command.startswith("az account list"):
                return json.dumps([
                    {
                        "cloudName": "AzureCloud",
                        "homeTenantId": "fake-tenant-id",
                        "id": "fake-subscription-id",
                        "isDefault": True,
                        "name": "Fake Subscription",
                        "state": "Enabled",
                        "tenantId": "fake-tenant-id",
                        "user": {"name": "fake-user", "type": "user"}
                    }
                ], indent=2)
            elif command.startswith("az group list"):
                 return json.dumps([
                    {"id": "/subscriptions/fake/resourceGroups/rg1", "name": "rg1", "location": "eastus"},
                    {"id": "/subscriptions/fake/resourceGroups/rg2", "name": "rg2", "location": "westus"}
                ], indent=2)
            else:
                return f"Mock output for command: {command}"

        # Only use device code handler for interactive login (without service-principal flag)
        # Service principal login should go through normal command execution
        if command.startswith("az login") and "--service-principal" not in command:
            return await self.login_handler.handle_az_login_command(command)

        self.logger.info(f"Running Azure CLI command: {command}")

        try:
            # Create subprocess for command execution
            # Use shell=True for Windows compatibility
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,  # Separate stderr for proper handling
                shell=True,
            )

            stdout, stderr = await process.communicate()

            stdout_text = stdout.decode("utf-8") if stdout else ""
            stderr_text = stderr.decode("utf-8") if stderr else ""

            if process.returncode != 0:
                self.logger.error(
                    f"Azure CLI command failed with exit code: {process.returncode}"
                )
                # Return stderr for error information
                return (
                    f"Error: {stderr_text}" if stderr_text else "Error: Command failed"
                )

            # Combine stdout and stderr for successful commands (warnings might be in stderr)
            output = stdout_text
            if stderr_text:
                output = f"{stdout_text}\n{stderr_text}".strip()

            return output

        except asyncio.TimeoutError as e:
            self.logger.error(f"Azure CLI command timed out: {e}")
            return f"Error: Command timed out"
        except Exception as e:
            self.logger.error(f"Error running Azure CLI command: {e}")
            return f"Error: {str(e)}" 