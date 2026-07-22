"""Microsoft Graph execution with typed authentication and shared token acquisition."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from unified_mcp.auth import ServicePrincipalProfile, TokenBroker
from unified_mcp.config import Settings
from unified_mcp.execution_policy import ExecutionPolicy


class GraphService:
    """Execute Microsoft Graph requests under bounded concurrency and policy."""

    _METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

    def __init__(
        self,
        settings: Settings,
        *,
        token_broker: TokenBroker | None = None,
        http_client: httpx.AsyncClient | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)
        self.auth_profile = settings.get_graph_auth_profile()
        self.policy = policy or settings.build_execution_policy()
        self._operation_semaphore = asyncio.Semaphore(settings.max_concurrent_operations)
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self.device_code_info: Dict[str, Any] | None = None
        self.token_broker = token_broker or TokenBroker(
            self.auth_profile,
            self._device_code_callback,
        )
        self.logger.info("GraphService initialized with %s authentication", self.auth_profile.kind)

    def _device_code_callback(
        self,
        verification_uri: str,
        user_code: str,
        expires_on: datetime,
    ) -> None:
        if expires_on.tzinfo is None:
            expires_on = expires_on.replace(tzinfo=timezone.utc)
        expires_in = max(0, int((expires_on - datetime.now(timezone.utc)).total_seconds()))
        self.device_code_info = {
            "verification_uri": verification_uri,
            "user_code": user_code,
            "expires_in": expires_in,
        }
        self.logger.info("Microsoft Graph device authentication required at %s", verification_uri)

    async def _get_client_secret(self) -> Dict[str, Any]:
        """Return a guided response when an application profile has no secret."""
        profile = self.auth_profile
        if not isinstance(profile, ServicePrincipalProfile) or profile.client_secret:
            return {"success": True}
        return {
            "success": False,
            "error": "Client secret required for custom app registration",
            "auth_required": True,
            "auth_type": "client_secret",
            "client_id": profile.client_id,
            "tenant_id": profile.tenant_id,
            "instructions": (
                "Set GRAPH_APP_CLIENT_SECRET (or CLIENT_SECRET), then restart the server. "
                "Use the secret value from Microsoft Entra ID, not its secret ID."
            ),
        }

    async def execute_command(
        self,
        command: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a Graph request with timeout and concurrency enforcement."""
        method = method.upper()
        if not command or not command.strip():
            return {"success": False, "error": "Microsoft Graph command is required"}
        if method not in self._METHODS:
            return {"success": False, "error": f"Unsupported HTTP method: {method}"}

        decision = self.policy.check_graph(command, method)
        if not decision.allowed:
            return {
                "success": False,
                "error": f"Execution policy denied request - {decision.reason}",
            }

        try:
            async with self._operation_semaphore:
                return await asyncio.wait_for(
                    self._execute_command(command, method, data),
                    timeout=self.settings.operation_timeout,
                )
        except asyncio.TimeoutError:
            return {"success": False, "error": "Microsoft Graph operation timed out"}

    async def _execute_command(
        self,
        command: str,
        method: str,
        data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        self.logger.info("Executing Microsoft Graph command: %s %s", method, command)

        secret_status = await self._get_client_secret()
        if not secret_status["success"]:
            return secret_status

        try:
            access_token = await self.token_broker.get_token()
        except asyncio.TimeoutError:
            return self._device_auth_response()
        except Exception as error:
            self.logger.error("Microsoft Graph authentication failed: %s", error)
            if self.device_code_info:
                return self._device_auth_response()
            message = str(error)
            if "AADSTS7000215" in message or "Invalid client secret" in message:
                return {
                    "success": False,
                    "error": "Invalid client secret provided",
                    "auth_required": True,
                    "error_details": message,
                    "instructions": (
                        "Use the client secret value (not its ID), verify it has not expired, "
                        "then restart the server."
                    ),
                }
            return {
                "success": False,
                "error": f"Authentication failed: {message}",
                "auth_required": True,
            }

        url = f"https://graph.microsoft.com/v1.0/{command.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {access_token.token}",
            "Content-Type": "application/json",
        }

        try:
            client = self._get_http_client()
            response: httpx.Response | None = None
            for attempt in range(3):
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=data if method in {"POST", "PUT", "PATCH"} else None,
                )
                if response.status_code != 429 or attempt == 2:
                    break
                await asyncio.sleep(self._retry_delay(response))
            assert response is not None
            return self._format_response(response, command)
        except Exception as error:
            self.logger.error("Microsoft Graph request failed: %s", error)
            return {"success": False, "error": str(error)}

    def _device_auth_response(self) -> Dict[str, Any]:
        info = self.device_code_info
        if not info:
            return {
                "success": False,
                "error": "Authentication timeout",
                "auth_required": True,
                "instructions": "Try the request again to start device authentication.",
            }
        return {
            "success": False,
            "error": "Device code authentication required",
            "auth_required": True,
            **info,
            "instructions": (
                f"Open {info['verification_uri']}, enter code {info['user_code']}, "
                "complete sign-in, then retry the request."
            ),
        }

    @staticmethod
    def _retry_delay(response: httpx.Response) -> float:
        try:
            return min(float(response.headers.get("Retry-After", "1")), 30.0)
        except ValueError:
            return 1.0

    def _format_response(self, response: httpx.Response, command: str) -> Dict[str, Any]:
        if response.status_code in {200, 201, 202, 204}:
            if response.status_code == 204:
                payload: Any = {"message": "Operation completed successfully (no content returned)"}
            else:
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    payload = {
                        "message": "Operation completed successfully",
                        "response_text": response.text,
                    }
            return {"success": True, "data": payload, "status_code": response.status_code}

        try:
            error_data = response.json()
            error_message = error_data.get("error", {}).get("message", response.text)
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}",
                "status_code": response.status_code,
            }

        result: Dict[str, Any] = {
            "success": False,
            "error": f"HTTP {response.status_code}: {error_message}",
            "status_code": response.status_code,
            "error_details": error_data,
        }
        if (
            command.strip("/") == "me"
            and response.status_code == 400
            and "delegated authentication" in error_message.lower()
            and self.token_broker.is_application_identity
        ):
            result["suggestion"] = (
                "The /me endpoint requires delegated authentication. Use /users/{userId}, "
                "list /users, or configure delegated authentication."
            )
        return result

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.operation_timeout)
            )
        return self._http_client

    async def close(self) -> None:
        """Release token acquisition and pooled HTTP resources."""
        await self.token_broker.close()
        if self._http_client is not None and self._owns_http_client:
            await self._http_client.aclose()
        self._http_client = None
