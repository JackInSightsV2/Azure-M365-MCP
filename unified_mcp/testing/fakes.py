"""Deterministic external-service fakes for local and container contract tests."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional

from unified_mcp.process import ProcessResult


class FakeAzureCliService:
    """Azure CLI adapter with no subprocess or authentication side effects.

    Pass ``failure`` to simulate a CLI that is broken or whose sign-in is refused: every
    command then returns that text as an ``Error:`` result, as the real service does.
    """

    def __init__(self, failure: Optional[str] = None) -> None:
        self.failure = failure

    async def execute_azure_cli(self, command: str) -> str:
        if self.failure is not None:
            return f"Error: {self.failure}"
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


DEFAULT_FAKE_RESOURCES: List[Dict[str, Any]] = [
    {
        "name": "fake-vm",
        "type": "microsoft.compute/virtualmachines",
        "subscriptionId": "fake-subscription-id",
        "resourceGroup": "rg1",
        "location": "eastus",
        "id": "/subscriptions/fake-subscription-id/resourceGroups/rg1/providers/"
        "Microsoft.Compute/virtualMachines/fake-vm",
    },
    {
        "name": "fakestorage",
        "type": "microsoft.storage/storageaccounts",
        "subscriptionId": "fake-subscription-id",
        "resourceGroup": "rg2",
        "location": "westus",
        "id": "/subscriptions/fake-subscription-id/resourceGroups/rg2/providers/"
        "Microsoft.Storage/storageAccounts/fakestorage",
    },
]


class FakeAzureRestService:
    """Azure Resource Manager REST adapter with deterministic JSON responses.

    Answers Azure Resource Graph queries from ``resources``, ``page_size`` rows at a time
    with a ``$skipToken`` for the next page, and counts them in ``resource_graph_queries``.
    Assign ``resources`` to change the estate between calls.
    """

    def __init__(
        self,
        resources: Optional[List[Dict[str, Any]]] = None,
        page_size: int = 1000,
    ) -> None:
        self.resources = list(DEFAULT_FAKE_RESOURCES if resources is None else resources)
        self.page_size = page_size
        self.resource_graph_queries = 0

    async def execute_command(
        self,
        command: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        path = command.split("?", 1)[0].strip("/")
        if (
            path.lower() == "providers/microsoft.resourcegraph/resources"
            and method.upper() == "POST"
        ):
            return self._resource_graph(data or {})
        if path == "subscriptions":
            payload: Any = {
                "value": [
                    {
                        "subscriptionId": "fake-subscription-id",
                        "displayName": "Fake Subscription",
                        "state": "Enabled",
                    }
                ]
            }
        else:
            payload = {"message": f"Mock ARM response for {method.upper()} {command}"}
        return {"success": True, "data": payload, "status_code": 200}

    def _resource_graph(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Page through ``resources`` the way Azure Resource Graph does."""
        options = body.get("options") or {}
        start = int(options.get("$skipToken") or 0)
        end = start + min(self.page_size, int(options.get("$top") or self.page_size))
        if start == 0:
            self.resource_graph_queries += 1
        page = self.resources[start:end]
        payload: Dict[str, Any] = {
            "totalRecords": len(self.resources),
            "count": len(page),
            "resultTruncated": "false",
            "data": page,
        }
        if end < len(self.resources):
            payload["$skipToken"] = str(end)
        return {"success": True, "data": payload, "status_code": 200}

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


class FakeProcessRunner:
    """Process runner that records calls and answers from scripted results.

    ``results`` maps an argument prefix (a tuple such as ``("kubectl", "get")``) to the
    result of any call starting with it; the longest matching prefix wins, and calls with
    no match succeed with ``"Mock output for command: ..."``. Programs named in
    ``missing`` raise ``FileNotFoundError`` and are absent from ``which``, the way a tool
    that is not installed behaves.
    """

    def __init__(
        self,
        results: Optional[Mapping[tuple[str, ...], ProcessResult]] = None,
        missing: Sequence[str] = (),
    ) -> None:
        self.results = dict(results or {})
        self.missing = set(missing)
        self.calls: List[List[str]] = []

    async def run(
        self,
        arguments: Sequence[str],
        timeout: float,
        env: Optional[Mapping[str, str]] = None,
    ) -> ProcessResult:
        call = list(arguments)
        self.calls.append(call)
        if call and call[0] in self.missing:
            raise FileNotFoundError(2, "No such file or directory", call[0])
        matches = [prefix for prefix in self.results if tuple(call[: len(prefix)]) == prefix]
        if matches:
            return self.results[max(matches, key=len)]
        return ProcessResult(0, f"Mock output for command: {' '.join(call)}", "")

    def which(self, name: str) -> Optional[str]:
        """Stand-in for ``shutil.which``: every program except the missing ones exists."""
        return None if name in self.missing else f"/usr/local/bin/{name}"
