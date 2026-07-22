"""Deterministic external-service fakes for local and container contract tests."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


class FakeAzureCliService:
    """Azure CLI adapter with no subprocess or authentication side effects."""

    async def execute_azure_cli(self, command: str) -> str:
        if command.startswith("az login"):
            return json.dumps(
                [
                    {
                        "cloudName": "AzureCloud",
                        "homeTenantId": "fake-tenant-id",
                        "id": "fake-subscription-id",
                        "isDefault": True,
                        "name": "Fake Subscription",
                        "state": "Enabled",
                        "tenantId": "fake-tenant-id",
                        "user": {
                            "name": "fake-service-principal",
                            "type": "servicePrincipal",
                        },
                    }
                ],
                indent=2,
            )
        if command.startswith("az account list"):
            return json.dumps(
                [
                    {
                        "cloudName": "AzureCloud",
                        "homeTenantId": "fake-tenant-id",
                        "id": "fake-subscription-id",
                        "isDefault": True,
                        "name": "Fake Subscription",
                        "state": "Enabled",
                        "tenantId": "fake-tenant-id",
                        "user": {"name": "fake-user", "type": "user"},
                    }
                ],
                indent=2,
            )
        if command.startswith("az group list"):
            return json.dumps(
                [
                    {
                        "id": "/subscriptions/fake/resourceGroups/rg1",
                        "name": "rg1",
                        "location": "eastus",
                    },
                    {
                        "id": "/subscriptions/fake/resourceGroups/rg2",
                        "name": "rg2",
                        "location": "westus",
                    },
                ],
                indent=2,
            )
        return f"Mock output for command: {command}"

    async def close(self) -> None:
        """Match the production service lifecycle contract."""


class FakeGraphService:
    """Microsoft Graph adapter with deterministic JSON responses."""

    async def execute_command(
        self,
        command: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        endpoint = command.strip("/")
        if endpoint == "me":
            payload: Any = {
                "displayName": "Mock User",
                "jobTitle": "Mock Developer",
                "mail": "mock@example.com",
                "userPrincipalName": "mock@example.com",
                "id": "mock-user-id",
            }
        elif endpoint == "users":
            payload = {
                "value": [
                    {"displayName": "User One", "mail": "one@example.com"},
                    {"displayName": "User Two", "mail": "two@example.com"},
                ]
            }
        elif endpoint.startswith("users/") and method.upper() == "GET":
            payload = {
                "displayName": "Specific User",
                "mail": "specific@example.com",
                "id": "specific-id",
            }
        else:
            payload = {"message": f"Mock response for {method.upper()} {command}"}
        return {"success": True, "data": payload, "status_code": 200}

    async def close(self) -> None:
        """Match the production service lifecycle contract."""
