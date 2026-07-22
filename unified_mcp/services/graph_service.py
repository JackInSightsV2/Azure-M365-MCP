"""Microsoft Graph Service for executing Graph API commands with dual authentication modes."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from azure.identity import ClientSecretCredential, DeviceCodeCredential, ManagedIdentityCredential

from unified_mcp.config import Settings


class GraphService:
    """Service for executing Microsoft Graph API commands with dual authentication modes."""

    def __init__(self, settings: Settings):
        """Initialize Microsoft Graph service."""
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self._operation_semaphore = asyncio.Semaphore(settings.max_concurrent_operations)
        self._http_client: Optional[httpx.AsyncClient] = None

        # Store device code info for user display
        self.device_code_info: Optional[Dict[str, Any]] = None
        self.credential: Optional[
            ClientSecretCredential | DeviceCodeCredential | ManagedIdentityCredential
        ] = None
        self.client_secret = settings.get_graph_client_secret()  # Try to get from environment first
        self.auth_config = settings.get_graph_auth_config()

        # Log the authentication mode
        if self.auth_config["mode"] == "managed_identity":
            identity_type = "user-assigned" if self.auth_config["client_id"] else "system-assigned"
            self.logger.info("GraphService initialized with %s managed identity", identity_type)
        elif settings.is_graph_read_only_mode:
            self.logger.info(
                "GraphService initialized in READ-ONLY mode using Microsoft Graph PowerShell public client"
            )
        else:
            secret_source = "environment variable" if self.client_secret else "not configured"
            auth_source = (
                "shared Azure CLI credentials"
                if settings.share_app_registration and settings.has_azure_credentials()
                else "Graph-specific credentials"
            )
            self.logger.info(
                f"GraphService initialized in READ/WRITE mode using custom app: {self.auth_config['client_id']}"
            )
            self.logger.info(f"Authentication source: {auth_source}")
            self.logger.info(f"Client secret source: {secret_source}")

    def _device_code_callback(
        self, verification_uri: str, user_code: str, expires_on: datetime
    ) -> None:
        """Callback to capture device code authentication details."""
        if expires_on.tzinfo is None:
            expires_on = expires_on.replace(tzinfo=timezone.utc)
        expires_in = max(0, int((expires_on - datetime.now(timezone.utc)).total_seconds()))
        self.device_code_info = {
            "verification_uri": verification_uri,
            "user_code": user_code,
            "expires_in": expires_in,
        }
        self.logger.info("Device code authentication is required at %s", verification_uri)

    async def _get_client_secret(self) -> Dict[str, Any]:
        """Return client secret prompt for MCP flow."""
        if not self.client_secret:
            return {
                "success": False,
                "error": "Client secret required for custom app registration",
                "auth_required": True,
                "auth_type": "client_secret",
                "client_id": self.auth_config["client_id"],
                "tenant_id": self.auth_config["tenant_id"],
                "instructions": f"""
CLIENT SECRET REQUIRED:

Your custom app registration requires a client secret for authentication.

App Registration Details:
• Client ID: {self.auth_config["client_id"]}
• Tenant ID: {self.auth_config["tenant_id"]}

To complete authentication, you can either:

Set the secret as an environment variable:
Add to your MCP configuration:
  "env": {{
    "CLIENT_SECRET": "your-app-secret-here"
  }}

Or use Docker args:
  "-e", "CLIENT_SECRET=your-app-secret-here"

If you don't have a client secret:
- Go to Azure Portal > Azure Active Directory > App registrations
- Find your app registration (Client ID: {self.auth_config["client_id"]})
- Go to Certificates & secrets > New client secret
- Copy the secret VALUE (not the ID)

Restart the server after changing its credentials.
""",
            }
        return {"success": True}

    def _clear_device_code_info(self) -> None:
        """Clear stale device-code details before acquiring a new token."""
        self.device_code_info = None

    async def execute_command(
        self,
        command: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a Microsoft Graph API command with support for all HTTP methods."""
        try:
            async with self._operation_semaphore:
                return await asyncio.wait_for(
                    self._execute_command(command, method, data),
                    timeout=self.settings.operation_timeout,
                )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Microsoft Graph operation timed out",
            }

    async def _execute_command(
        self,
        command: str,
        method: str,
        data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Perform a Graph operation while the public wrapper enforces limits."""
        try:
            self.logger.info(f"Executing Microsoft Graph command: {method} {command}")

            # Handle Mock Mode
            if self.settings.mock_mode:
                self.logger.info(f"MOCK MODE: Returning fake response for '{command}'")
                if command.strip("/") in ["me", "me/"]:
                    return {
                        "success": True,
                        "data": {
                            "displayName": "Mock User",
                            "jobTitle": "Mock Developer",
                            "mail": "mock@example.com",
                            "userPrincipalName": "mock@example.com",
                            "id": "mock-user-id",
                        },
                        "status_code": 200,
                    }
                elif command.strip("/") in ["users", "users/"]:
                    return {
                        "success": True,
                        "data": {
                            "value": [
                                {"displayName": "User One", "mail": "one@example.com"},
                                {"displayName": "User Two", "mail": "two@example.com"},
                            ]
                        },
                        "status_code": 200,
                    }
                elif "users/" in command and method == "GET":
                    return {
                        "success": True,
                        "data": {
                            "displayName": "Specific User",
                            "mail": "specific@example.com",
                            "id": "specific-id",
                        },
                        "status_code": 200,
                    }
                else:
                    return {
                        "success": True,
                        "data": {"message": f"Mock response for {method} {command}"},
                        "status_code": 200,
                    }

            # Create credential based on auth mode
            if self.credential is None:
                if self.auth_config["mode"] == "managed_identity":
                    self.credential = ManagedIdentityCredential(
                        client_id=self.auth_config["client_id"]
                    )
                    self.logger.info("Using ManagedIdentityCredential")
                elif self.auth_config["mode"] == "custom":
                    # Custom app registration mode - requires client secret
                    if not self.client_secret:
                        secret_result = await self._get_client_secret()
                        if isinstance(secret_result, dict) and not secret_result.get(
                            "success", True
                        ):
                            return secret_result

                    client_secret = self.client_secret
                    if client_secret is None:
                        return {
                            "success": False,
                            "error": "Client secret is not configured",
                            "auth_required": True,
                        }
                    self.credential = ClientSecretCredential(
                        tenant_id=self.auth_config["tenant_id"],
                        client_id=self.auth_config["client_id"],
                        client_secret=client_secret,
                    )
                    self.logger.info("Using ClientSecretCredential for custom app registration")
                else:
                    # Default read-only mode
                    self.credential = DeviceCodeCredential(
                        client_id=self.auth_config["client_id"],
                        tenant_id=self.auth_config["tenant_id"],
                        prompt_callback=self._device_code_callback,
                    )
                    self.logger.info("Using DeviceCodeCredential for read-only access")

            # Clear any previous device code info
            self._clear_device_code_info()

            # Try to get access token with a short timeout
            self.logger.info("Getting access token")

            # Use asyncio to run the sync get_token with a timeout
            try:
                credential = self.credential
                if credential is None:
                    raise RuntimeError("Graph credential was not initialized")
                loop = asyncio.get_running_loop()
                access_token = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, lambda: credential.get_token(*self.auth_config["scopes"])
                    ),
                    timeout=3.0,  # 3 second timeout
                )

            except asyncio.TimeoutError:
                # If we have device code info, return it
                if self.device_code_info:
                    return {
                        "success": False,
                        "error": "Device code authentication required",
                        "auth_required": True,
                        "verification_uri": self.device_code_info["verification_uri"],
                        "user_code": self.device_code_info["user_code"],
                        "expires_in": self.device_code_info["expires_in"],
                        "instructions": f"""
AUTHENTICATION REQUIRED:

1. Open this URL in your browser: {self.device_code_info["verification_uri"]}
2. Enter this code: {self.device_code_info["user_code"]}
3. Complete the sign-in process with your Microsoft account
4. This code expires in {self.device_code_info["expires_in"]} seconds
5. After successful authentication, try your request again

The authentication will be cached for future requests.
""",
                    }
                else:
                    return {
                        "success": False,
                        "error": "Authentication timeout",
                        "auth_required": True,
                        "instructions": "Authentication timed out. Please try again.",
                    }

            except Exception as auth_error:
                self.logger.error(f"Authentication failed: {auth_error}")

                # Clear the credential so next attempt can try fresh
                self.credential = None

                # If we have device code info, return it
                if self.device_code_info:
                    return {
                        "success": False,
                        "error": "Device code authentication required",
                        "auth_required": True,
                        "verification_uri": self.device_code_info["verification_uri"],
                        "user_code": self.device_code_info["user_code"],
                        "expires_in": self.device_code_info["expires_in"],
                        "instructions": f"""
AUTHENTICATION REQUIRED:

1. Open this URL in your browser: {self.device_code_info["verification_uri"]}
2. Enter this code: {self.device_code_info["user_code"]}
3. Complete the sign-in process with your Microsoft account
4. This code expires in {self.device_code_info["expires_in"]} seconds
5. After successful authentication, try your request again

The authentication will be cached for future requests.
""",
                    }
                else:
                    # Show the actual authentication error
                    error_msg = str(auth_error)

                    # Check for specific client secret errors
                    if "AADSTS7000215" in error_msg or "Invalid client secret" in error_msg:
                        return {
                            "success": False,
                            "error": "Invalid client secret provided",
                            "auth_required": True,
                            "error_details": error_msg,
                            "instructions": f"""
CLIENT SECRET ERROR:

The client secret you provided is invalid. This could be because:

1. You copied the Secret ID instead of the Secret Value
   - In Azure Portal, use the VALUE column, not the Secret ID
   - The value should look like: 0pz8Q~~xfcUDmn0...
   - NOT the ID like: 74edbec7-9b02-44d6-b091-3df29daa1a2c

2. The client secret has expired
   - Check the expiration date in Azure Portal
   - Create a new client secret if needed

3. The client secret was incorrectly copied
   - Make sure you copied the complete value
   - Avoid extra spaces or characters

App Registration Details:
• Client ID: {self.auth_config["client_id"]}
• Tenant ID: {self.auth_config["tenant_id"]}

Please verify your client secret and try again.
""",
                        }
                    else:
                        # Generic auth error without device code info
                        return {
                            "success": False,
                            "error": f"Authentication failed: {error_msg}",
                            "auth_required": True,
                            "instructions": "Please try again. If the issue persists, you may need to clear cached credentials.",
                        }

            # Prepare the API request
            url = f"https://graph.microsoft.com/v1.0/{command.lstrip('/')}"
            headers = {
                "Authorization": f"Bearer {access_token.token}",
                "Content-Type": "application/json",
            }

            self.logger.info(f"Making {method} request to: {url}")

            method = method.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                return {
                    "success": False,
                    "error": f"Unsupported HTTP method: {method}",
                }

            client = self._get_http_client()
            for attempt in range(3):
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=data if method in {"POST", "PUT", "PATCH"} else None,
                )
                if response.status_code != 429 or attempt == 2:
                    break
                retry_after = response.headers.get("Retry-After", "1")
                try:
                    delay = min(float(retry_after), 30.0)
                except ValueError:
                    delay = 1.0
                self.logger.warning("Graph throttled the request; retrying in %.1fs", delay)
                await asyncio.sleep(delay)

            self.logger.info(f"Response status: {response.status_code}")

            if response.status_code in [200, 201, 202, 204]:
                # Handle successful responses
                if response.status_code == 204:  # No content
                    return {
                        "success": True,
                        "data": {
                            "message": "Operation completed successfully (no content returned)"
                        },
                        "status_code": response.status_code,
                    }
                else:
                    try:
                        data = response.json()
                        return {"success": True, "data": data, "status_code": response.status_code}
                    except json.JSONDecodeError:
                        # Some responses might not be JSON
                        return {
                            "success": True,
                            "data": {
                                "message": "Operation completed successfully",
                                "response_text": response.text,
                            },
                            "status_code": response.status_code,
                        }
            else:
                # Handle error responses
                try:
                    error_data = response.json()
                    error_message = error_data.get("error", {}).get("message", response.text)

                    # Special handling for /me endpoint with application authentication
                    if (
                        command.strip("/") in ["me", "me/"]
                        and response.status_code == 400
                        and "delegated authentication" in error_message.lower()
                        and isinstance(self.credential, ClientSecretCredential)
                    ):
                        return {
                            "success": False,
                            "error": f"HTTP {response.status_code}: {error_message}",
                            "status_code": response.status_code,
                            "error_details": error_data,
                            "suggestion": (
                                "The /me endpoint requires delegated authentication (user context). "
                                "Since you're using application-only authentication, try one of these alternatives:\n"
                                "1. Use /users/{userId} with a specific user ID\n"
                                "2. Use /users to list all users\n"
                                "3. Switch to delegated authentication if you need user-specific data"
                            ),
                        }

                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}: {error_message}",
                        "status_code": response.status_code,
                        "error_details": error_data,
                    }
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}: {response.text}",
                        "status_code": response.status_code,
                    }

        except Exception as e:
            self.logger.error(f"Error executing command: {e}")
            return {"success": False, "error": str(e)}

    def _get_http_client(self) -> httpx.AsyncClient:
        """Create one pooled HTTP client for the service lifetime."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.operation_timeout)
            )
        return self._http_client

    async def close(self) -> None:
        """Release pooled HTTP connections and identity resources."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        if self.credential is not None and hasattr(self.credential, "close"):
            self.credential.close()
