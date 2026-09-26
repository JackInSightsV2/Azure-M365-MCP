"""Azure Resource Manager REST access without the Azure CLI binary or its app id.

This service acquires an ARM token through the shared :class:`TokenBroker` and calls
``https://management.azure.com`` directly. Interactive sign-in uses a configurable
public client (Azure PowerShell by default), which lets tenants whose Conditional
Access blocks the Azure CLI application still authenticate with an allowed identity.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from unified_mcp.auth import TokenBroker, pending_sign_in_response
from unified_mcp.config import Settings
from unified_mcp.execution_policy import ExecutionPolicy
from unified_mcp.tenant_policy import detect_tenant_policy_refusal, tenant_policy_response

ARM_BASE_URL = "https://management.azure.com/"


class AzureRestService:
    """Execute Azure Resource Manager REST requests under bounded concurrency and policy."""

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
        self.auth_profile = settings.get_arm_auth_profile()
        self.policy = policy or settings.build_execution_policy()
        self._operation_semaphore = asyncio.Semaphore(settings.max_concurrent_operations)
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self.device_code_info: Dict[str, Any] | None = None
        self.token_broker = token_broker or TokenBroker(
            self.auth_profile,
            self._device_code_callback,
        )
        self.logger.info(
            "AzureRestService initialized with %s authentication", self.auth_profile.kind
        )

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
        self.logger.info(
            "Azure Resource Manager device authentication required at %s", verification_uri
        )

    async def execute_command(
        self,
        command: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute an ARM REST request with timeout and concurrency enforcement."""
        method = method.upper()
        if not command or not command.strip():
            return {"success": False, "error": "Azure Resource Manager path is required"}
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
            return {"success": False, "error": "Azure Resource Manager operation timed out"}

    async def _execute_command(
        self,
        command: str,
        method: str,
        data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        self.logger.info("Executing Azure Resource Manager request: %s %s", method, command)

        try:
            access_token = await self.token_broker.get_token()
        except asyncio.TimeoutError:
            return self._device_auth_response()
        except Exception as error:
            self.logger.error("Azure Resource Manager authentication failed: %s", error)
            refusal = detect_tenant_policy_refusal(error, self.auth_profile.client_id)
            if refusal is not None:
                # The pending device code is spent; do not show it again.
                self.device_code_info = None
                return tenant_policy_response(refusal, str(error))
            if self.device_code_info:
                return self._device_auth_response()
            return {
                "success": False,
                "error": f"Authentication failed: {error}",
                "auth_required": True,
            }

        url = f"{ARM_BASE_URL}{command.lstrip('/')}"
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
            return self._format_response(response)
        except Exception as error:
            self.logger.error("Azure Resource Manager request failed: %s", error)
            return {"success": False, "error": str(error)}

    def _device_auth_response(self) -> Dict[str, Any]:
        info = self.device_code_info
        browser = pending_sign_in_response(self.auth_profile)
        if not info and browser is not None:
            return browser
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

    def _format_response(self, response: httpx.Response) -> Dict[str, Any]:
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

        return {
            "success": False,
            "error": f"HTTP {response.status_code}: {error_message}",
            "status_code": response.status_code,
            "error_details": error_data,
        }

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
