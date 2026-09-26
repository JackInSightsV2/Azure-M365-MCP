"""Transport-independent tool definitions and execution core."""

from __future__ import annotations

import json
import logging
import os
import shlex
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Protocol

from mcp.types import Resource, TextContent, Tool, ToolAnnotations
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, ValidationError

from unified_mcp.execution_policy import ExecutionPolicy, ExecutionPolicyMode
from unified_mcp.resource_inventory import (
    MAX_MATCHES,
    RESOURCE_GRAPH_PATH,
    ResourceInventory,
    ResourceInventoryError,
    consent_message,
)

SERVER_INSTRUCTIONS = (
    "This server connects to the user's Microsoft cloud: Microsoft 365 (also called M365 "
    "or Office 365), Entra ID (Azure AD), and Microsoft Azure. Use it whenever the user "
    "asks about their Microsoft account, tenant, email, calendar, Teams, SharePoint or "
    "OneDrive files, users, groups, licenses, Intune devices, sign-in or audit logs, or "
    "Azure subscriptions and resources — do not answer those from general knowledge when "
    "these tools can fetch the real data.\n\n"
    "- microsoft365_read: read Microsoft 365 and Entra ID (Azure AD) via the Microsoft "
    "Graph API (GET only). Look up users, groups, licences/licenses, mail, calendar, Teams, "
    "files, devices, sign-in logs, and directory data.\n"
    "- microsoft365_write: change Microsoft 365 and Entra ID (Azure AD) via the Microsoft "
    "Graph API (POST/PUT/PATCH/DELETE). Create or update users, groups, licence/license "
    "assignments, send mail, manage calendar, Teams, and files.\n"
    "- azure_read: read Microsoft Azure resources — subscriptions, resource groups, "
    "virtual machines, storage, networking, role assignments, costs. Pass an Azure CLI "
    "command (begins with 'az') or an Azure Resource Manager REST path; the server uses "
    "the Azure CLI and falls back to ARM REST when the CLI is unavailable or blocked by "
    "Conditional Access.\n"
    "- azure_write: create, change, or delete the same Azure resources, with the same "
    "inputs and fallback.\n"
    "- azure_find_resource: find which subscription and resource group an Azure resource "
    "is in by name, in one call. Try it before searching subscriptions one by one.\n\n"
    "Prefer read operations, inspect the help resources before unfamiliar actions, and "
    "never place credentials in tool arguments. Authentication prompts may require the "
    "user to complete a sign-in (browser window or device code) and retry."
)


MICROSOFT365_READ = "microsoft365_read"
MICROSOFT365_WRITE = "microsoft365_write"


class AzureExecutor(Protocol):
    """Azure execution port shared by real and fake adapters."""

    async def execute_azure_cli(self, command: str) -> str: ...

    async def close(self) -> None: ...


class GraphExecutor(Protocol):
    """Graph execution port shared by real and fake adapters."""

    async def execute_command(
        self,
        command: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]: ...

    async def close(self) -> None: ...


class RestExecutor(Protocol):
    """Azure Resource Manager REST port shared by real and fake adapters."""

    async def execute_command(
        self,
        command: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]: ...

    async def close(self) -> None: ...


AZURE_READ_TOOL = "azure_read"
AZURE_WRITE_TOOL = "azure_write"
AZURE_FIND_RESOURCE_TOOL = "azure_find_resource"
ARM_BASE_URL = "https://management.azure.com/"

# Azure CLI commands with a direct ARM REST equivalent, keyed by command path (the
# non-flag tokens after 'az'). Anything else cannot fall back and asks for an ARM path.
_CLI_TO_ARM_PATHS: Dict[tuple[str, ...], str] = {
    ("account", "list"): "subscriptions?api-version=2022-12-01",
    # No default subscription exists outside the CLI, so list them all.
    ("account", "show"): "subscriptions?api-version=2022-12-01",
}
# ARM endpoints that take POST but only read or predict: Resource Graph queries, Cost
# Management queries, and deployment What-if.
_READ_ONLY_ARM_POST_SUFFIXES = (
    "providers/microsoft.resourcegraph/resources",
    "providers/microsoft.costmanagement/query",
    "/whatif",
)
_CLI_SIGN_IN_MARKERS = (
    "aadsts",
    "az login",
    "sign-in was refused",
    "authentication",
    "not logged in",
    "no subscription found",
    # The Azure CLI is not installed.
    "no such file or directory",
    "command not found",
)
_ARM_PATH_HINT = (
    "Retry with an Azure Resource Manager REST path instead, for example "
    "'subscriptions?api-version=2022-12-01' or "
    "'subscriptions/{id}/resourceGroups?api-version=2021-04-01'."
)


class GraphToolInput(BaseModel):
    """Typed Microsoft Graph tool input."""

    command: str = Field(min_length=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    data: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra="forbid")


class AzureToolInput(BaseModel):
    """Typed Azure Read/Write tool input: an Azure CLI command or an ARM REST path."""

    command: str = Field(min_length=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    data: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(extra="forbid")


class FindResourceInput(BaseModel):
    """Typed azure_find_resource input: all or part of a resource name."""

    name: str = Field(min_length=1)
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolExecutionResult:
    """One canonical result consumed by MCP and OpenAPI transports."""

    tool_name: str
    payload: Any
    text: str
    is_error: bool


class ToolApplication:
    """Validate and dispatch every tool call through one typed core."""

    def __init__(
        self,
        azure_service: AzureExecutor | None,
        graph_service: GraphExecutor | None,
        arm_service: RestExecutor | None = None,
        resource_inventory: ResourceInventory | None = None,
    ) -> None:
        self.azure_service = azure_service
        self.graph_service = graph_service
        self.arm_service = arm_service
        self.resource_inventory = resource_inventory
        self.logger = logging.getLogger(__name__)

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> ToolExecutionResult:
        if name in (AZURE_READ_TOOL, AZURE_WRITE_TOOL):
            try:
                azure_request = AzureToolInput.model_validate(arguments)
            except ValidationError as error:
                return self._error(name, self._validation_message(error))
            if self._is_cli_command(azure_request.command):
                return await self._execute_azure_cli(name, azure_request)
            return await self._execute_azure_rest(name, azure_request)

        if name == AZURE_FIND_RESOURCE_TOOL:
            try:
                find_request = FindResourceInput.model_validate(arguments)
            except ValidationError as error:
                return self._error(name, self._validation_message(error))
            return await self._find_resource(find_request.name)

        if name in (MICROSOFT365_READ, MICROSOFT365_WRITE):
            if self.graph_service is None:
                return self._error(name, "Graph service not initialized")
            try:
                graph_request = GraphToolInput.model_validate(arguments)
            except ValidationError as error:
                return self._error(name, self._validation_message(error))
            if name == MICROSOFT365_READ and graph_request.method != "GET":
                return self._error(
                    name,
                    f"{MICROSOFT365_READ} only accepts GET; use {MICROSOFT365_WRITE} "
                    f"for {graph_request.method}",
                )
            if name == MICROSOFT365_WRITE and graph_request.method == "GET":
                return self._error(
                    name,
                    f"{MICROSOFT365_WRITE} does not accept GET; use {MICROSOFT365_READ} for reads",
                )
            graph_payload = await self.graph_service.execute_command(
                graph_request.command,
                graph_request.method,
                graph_request.data,
            )
            return ToolExecutionResult(
                name,
                graph_payload,
                self._format_graph(graph_request, graph_payload),
                not bool(graph_payload.get("success")),
            )

        return self._error(name, f"Unknown tool: {name}")

    async def _find_resource(self, name: str) -> ToolExecutionResult:
        """Look a resource up by name in the opt-in Resource inventory."""
        tool = AZURE_FIND_RESOURCE_TOOL
        inventory = self.resource_inventory
        if inventory is None:
            return self._error(tool, "The Resource inventory is not available in this server")
        if not inventory.has_consent():
            # Consent may have been withdrawn since the last build: leave no map behind.
            inventory.delete()
            message = consent_message()
            return ToolExecutionResult(
                tool, {"success": False, "consent_required": True, "error": message}, message, True
            )
        if self.arm_service is None:
            return self._error(
                tool, "The Resource inventory needs Azure Resource Manager REST (ENABLE_AZURE_REST)"
            )
        try:
            found = await inventory.find(name, self.arm_service)
        except ResourceInventoryError as error:
            request = GraphToolInput(command=RESOURCE_GRAPH_PATH, method="POST")
            return ToolExecutionResult(
                tool, error.payload, self._format_graph(request, error.payload), True
            )

        payload = {"success": True, "matches": found.matches, "total": found.total}
        if not found.matches:
            text = (
                f"No Azure resource with a name matching '{name}' in the Resource inventory, "
                "which was refreshed just now. Check the spelling, or the resource may be in "
                "a subscription or Tenant you cannot see."
            )
            return ToolExecutionResult(tool, payload, text, False)
        shown = f"showing the first {MAX_MATCHES} of {found.total}; use a more specific name"
        header = (
            f"Found {found.total} Azure resource(s) matching '{name}'"
            + (f" ({shown})" if found.total > len(found.matches) else "")
            + ", exact name matches first:"
        )
        text = f"{header}\n\n```json\n{json.dumps(found.matches, indent=2)}\n```"
        return ToolExecutionResult(tool, payload, text, False)

    async def _execute_azure_cli(self, name: str, request: AzureToolInput) -> ToolExecutionResult:
        """Run an Azure CLI command, falling back to ARM REST when the CLI is absent or fails."""
        if request.data is not None or request.method != "GET":
            return self._error(
                name, "method and data apply only to Azure Resource Manager REST paths"
            )
        if name == AZURE_READ_TOOL:
            decision = ExecutionPolicy(ExecutionPolicyMode.READ_ONLY).check_azure(request.command)
            if not decision.allowed:
                return self._error(
                    name,
                    f"{AZURE_READ_TOOL} only runs read-only Azure CLI commands "
                    f"(list, show, get, ...). Use {AZURE_WRITE_TOOL} for this command.",
                )
        elif ExecutionPolicy(ExecutionPolicyMode.READ_ONLY).check_azure(request.command).allowed:
            return self._error(
                name,
                f"{AZURE_WRITE_TOOL} only runs commands that change Azure resources. "
                f"Use {AZURE_READ_TOOL} for this command.",
            )

        cli_error: str | None = None
        if self.azure_service is not None:
            payload = await self.azure_service.execute_azure_cli(request.command)
            if not self._is_cli_error(payload):
                return ToolExecutionResult(name, payload, payload, False)
            if not self._is_cli_sign_in_failure(payload) or self.arm_service is None:
                return ToolExecutionResult(name, payload, payload, True)
            cli_error = payload

        if self.arm_service is None:
            return self._error(name, "Azure is not available: no Azure CLI or ARM REST service")

        arm_path = self._cli_to_arm_path(request.command)
        if arm_path is None:
            reason = cli_error or "Error: Azure CLI service not available"
            message = (
                f"{reason}\n\nThis Azure CLI command has no direct Azure Resource Manager "
                f"REST equivalent. {_ARM_PATH_HINT}"
            )
            return ToolExecutionResult(name, {"success": False, "error": message}, message, True)
        return await self._execute_azure_rest(
            name, AzureToolInput(command=arm_path), prefer_cli=False
        )

    async def _execute_azure_rest(
        self,
        name: str,
        request: AzureToolInput,
        *,
        prefer_cli: bool = True,
    ) -> ToolExecutionResult:
        """Call Azure Resource Manager REST, or 'az rest' when only the CLI is available."""
        read_only = self._is_read_only_arm_request(request)
        if name == AZURE_READ_TOOL and not read_only:
            return self._error(
                name,
                f"{AZURE_READ_TOOL} only sends GET requests. "
                f"Use {AZURE_WRITE_TOOL} for {request.method}.",
            )
        if name == AZURE_WRITE_TOOL and read_only:
            return self._error(
                name,
                f"{AZURE_WRITE_TOOL} only sends requests that change Azure resources. "
                f"Use {AZURE_READ_TOOL} for this request.",
            )
        if self.arm_service is None:
            if not prefer_cli or self.azure_service is None:
                return self._error(name, "Azure is not available: no Azure CLI or ARM REST service")
            payload = await self.azure_service.execute_azure_cli(self._az_rest_command(request))
            return ToolExecutionResult(name, payload, payload, self._is_cli_error(payload))

        arm_payload = await self.arm_service.execute_command(
            request.command,
            request.method,
            request.data,
        )
        return ToolExecutionResult(
            name,
            arm_payload,
            self._format_graph(
                GraphToolInput(command=request.command, method=request.method, data=request.data),
                arm_payload,
            ),
            not bool(arm_payload.get("success")),
        )

    @staticmethod
    def _split(command: str) -> list[str]:
        try:
            return shlex.split(command, posix=os.name != "nt")
        except ValueError:
            return command.split()

    @classmethod
    def _is_cli_command(cls, command: str) -> bool:
        arguments = cls._split(command)
        return bool(arguments) and arguments[0].lower() == "az"

    @staticmethod
    def _is_read_only_arm_request(request: AzureToolInput) -> bool:
        """GET, or a POST to an ARM endpoint that only queries or predicts (never changes)."""
        if request.method == "GET":
            return True
        if request.method != "POST":
            return False
        path = request.command.split("?", 1)[0].strip("/").lower()
        return path.endswith(_READ_ONLY_ARM_POST_SUFFIXES)

    @staticmethod
    def _is_cli_sign_in_failure(payload: str) -> bool:
        """Only a missing CLI or a sign-in failure falls back to ARM REST; other errors stand."""
        lowered = payload.lower()
        return any(marker in lowered for marker in _CLI_SIGN_IN_MARKERS)

    @staticmethod
    def _is_cli_error(payload: str) -> bool:
        return payload.startswith("Error:") or "\nError:" in payload

    @classmethod
    def _cli_to_arm_path(cls, command: str) -> str | None:
        command_path: list[str] = []
        for argument in cls._split(command)[1:]:
            if argument.startswith("-"):
                break
            command_path.append(argument.lower())
        return _CLI_TO_ARM_PATHS.get(tuple(command_path))

    @staticmethod
    def _az_rest_command(request: AzureToolInput) -> str:
        url = ARM_BASE_URL + request.command.lstrip("/")
        command = f"az rest --method {request.method.lower()} --url {shlex.quote(url)}"
        if request.data is not None:
            command += f" --body {shlex.quote(json.dumps(request.data))}"
        return command

    @staticmethod
    def _validation_message(error: ValidationError) -> str:
        issue = error.errors()[0]
        location = ".".join(str(part) for part in issue["loc"])
        if issue["type"] == "missing":
            return f"Missing {location} argument"
        return f"Invalid {location}: {issue['msg']}"

    @staticmethod
    def _format_graph(request: GraphToolInput, result: Dict[str, Any]) -> str:
        label = f"{request.method.upper()} {request.command}"
        if result.get("success"):
            data = result.get("data")
            rendered = f"```json\n{json.dumps(data, indent=2)}\n```" if data else "Completed."
            return f"Success ({label})\n\n{rendered}"

        text = f"Error ({label})\n\n{result.get('error', 'Unknown error')}"
        if result.get("auth_required") and result.get("instructions"):
            text += f"\n\nInstructions:\n{result['instructions']}"
        if result.get("suggestion"):
            text += f"\n\nSuggestion:\n{result['suggestion']}"
        if result.get("error_details"):
            details = result["error_details"]
            if not isinstance(details, str):
                details = json.dumps(details, indent=2)
            text += f"\n\nDetails:\n{details}"
        return text

    @staticmethod
    def _error(name: str, message: str) -> ToolExecutionResult:
        text = f"Error: {message}"
        return ToolExecutionResult(name, {"success": False, "error": message}, text, True)

    async def close(self) -> None:
        """Close both adapters, even when the first close fails."""
        errors: list[Exception] = []
        for service in (self.azure_service, self.graph_service, self.arm_service):
            if service is None:
                continue
            try:
                await service.close()
            except Exception as error:
                errors.append(error)
        if errors:
            raise errors[0]


def _azure_input_schema(*, read_only: bool) -> Dict[str, Any]:
    """Shared input schema for the Azure Read and Write tools."""
    method_description = (
        "REST paths only. azure_read sends GET; use azure_write for other methods"
        if read_only
        else "REST paths only. GET reads; POST, PUT, PATCH, DELETE write"
    )
    return {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Azure CLI command beginning with 'az' (for example 'az group list'), "
                    "or an Azure Resource Manager path including the api-version query "
                    "parameter (for example 'subscriptions?api-version=2022-12-01')"
                ),
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "default": "GET",
                "description": method_description,
            },
            "data": {"type": "object", "description": "JSON body for REST write requests"},
        },
        "required": ["command"],
        "additionalProperties": False,
    }


def create_tools() -> list[Tool]:
    """Return the canonical tool schemas exposed by every MCP transport."""
    return [
        Tool(
            name=AZURE_READ_TOOL,
            description=(
                "Read the user's Microsoft Azure resources: subscriptions, resource groups, "
                "virtual machines, storage accounts, networking, role assignments, and cost "
                "data. Pass either an Azure CLI command (begins with 'az', read-only actions "
                "such as list, show, get) or an Azure Resource Manager REST path with the "
                "api-version query parameter (GET only). The server uses the Azure CLI and "
                "falls back to ARM REST automatically when the CLI is unavailable or blocked by "
                "Conditional Access. Examples: 'az account show', 'az vm list -o table', "
                "'subscriptions?api-version=2022-12-01'. Use azure_write for changes."
            ),
            inputSchema=_azure_input_schema(read_only=True),
            annotations=ToolAnnotations(
                title="Read Azure resources",
                readOnlyHint=True,
                destructiveHint=False,
            ),
        ),
        Tool(
            name=AZURE_WRITE_TOOL,
            description=(
                "Create, change, or delete the user's Microsoft Azure resources: "
                "subscriptions, resource groups, virtual machines, storage accounts, "
                "networking, role assignments, and cost settings. Pass either an Azure CLI "
                "command (begins with 'az', for example 'az group create ...') or an Azure "
                "Resource Manager REST path with the api-version query parameter plus a "
                "method (POST, PUT, PATCH, DELETE) and JSON body. The server uses the Azure "
                "CLI and falls back to ARM REST automatically when the CLI is unavailable or "
                "blocked by Conditional Access. Subject to the configured execution policy."
            ),
            inputSchema=_azure_input_schema(read_only=False),
            annotations=ToolAnnotations(
                title="Change Azure resources",
                readOnlyHint=False,
                destructiveHint=True,
            ),
        ),
        Tool(
            name=AZURE_FIND_RESOURCE_TOOL,
            description=(
                "Find an Azure resource by name: which subscription and resource group is it "
                "in, what type is it, where is it located, and what is its resource ID. One "
                "call searches every subscription the user can see, so try this before "
                "listing subscriptions or resource groups one by one. Case-insensitive; exact "
                "name matches first, then names containing the text; at most 20 results. "
                "Uses the opt-in Resource inventory; if it is off, the result explains how to "
                "turn it on. Examples: 'prod-sql-01', 'webapp'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The resource name, or part of it",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(
                title="Find an Azure resource by name",
                readOnlyHint=True,
                destructiveHint=False,
            ),
        ),
        Tool(
            name=MICROSOFT365_READ,
            description=(
                "Read the user's Microsoft 365 and Entra ID (Azure AD) data via the Microsoft "
                "Graph API — the way to look things up in their Microsoft account and tenant. "
                "Also known as Microsoft 365, M365, Office 365, Azure AD, or Entra. Look up "
                "users, groups, licences/licenses, mail and Outlook, calendar, OneDrive and "
                "SharePoint files, Teams, devices and Intune, and sign-in or audit logs. GET "
                "only; use microsoft365_write to change anything. Provide a Microsoft Graph "
                "v1.0 path. Examples: 'me', 'users', 'users/{id}', 'groups', 'me/messages'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Microsoft Graph v1.0 path such as 'me', 'users', 'users/{id}', "
                            "'groups', or 'me/messages'"
                        ),
                    },
                    "method": {
                        "type": "string",
                        "enum": ["GET"],
                        "default": "GET",
                        "description": "Always GET; use microsoft365_write for writes",
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
        ),
        Tool(
            name=MICROSOFT365_WRITE,
            description=(
                "Change the user's Microsoft 365 and Entra ID (Azure AD) data via the "
                "Microsoft Graph API. Also known as Microsoft 365, M365, Office 365, Azure AD, "
                "or Entra. Create, update, or delete users and groups, assign licences/licenses, "
                "send mail, manage calendar events, Teams, OneDrive and SharePoint files, and "
                "devices. POST/PUT/PATCH/DELETE only; use microsoft365_read for lookups. "
                "Provide a Microsoft Graph v1.0 path, method, and JSON body. Examples: "
                "PATCH 'users/{id}', POST 'groups/{id}/members/$ref', POST 'me/sendMail'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Microsoft Graph v1.0 path such as 'users/{id}', "
                            "'groups/{id}/members/$ref', or 'me/sendMail'"
                        ),
                    },
                    "method": {
                        "type": "string",
                        "enum": ["POST", "PUT", "PATCH", "DELETE"],
                    },
                    "data": {"type": "object", "description": "JSON body for the request"},
                },
                "required": ["command", "method"],
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
        ),
    ]


def create_resources() -> list[Resource]:
    """Return concise operational help resources."""
    return [
        Resource(
            uri=AnyUrl("azure://help"),
            name="Azure Help",
            description="Subscriptions, resource groups, VMs — auth, policy, and examples",
            mimeType="text/markdown",
        ),
        Resource(
            uri=AnyUrl("graph://help"),
            name="Microsoft 365 & Entra ID Help",
            description="Users, mail, Teams, groups, licenses, devices — auth, policy, and examples",
            mimeType="text/markdown",
        ),
    ]


def read_resource(uri: AnyUrl) -> str:
    """Read a short help resource; the microsoft-cloud skill is the full reference."""
    if str(uri) == "azure://help":
        return """# Azure tools

`azure_read` (read-only `az` actions such as list/show/get, or ARM REST GET) and
`azure_write` (every other `az` command, or ARM REST with `method` and `data`).
ARM paths need an `api-version`, for example `subscriptions?api-version=2022-12-01`.
The server uses the Azure CLI and falls back to ARM REST when the CLI is missing or its
sign-in fails. Examples: `az account show`, `az group list`, `az vm list -d`.

If a tool asks for sign-in (a browser window, or a device code), complete the
Interactive sign-in and retry. For common
commands and paths, see the `microsoft-cloud` skill:
https://github.com/JackInSightsV2/Azure-M365-MCP/blob/main/skills/microsoft-cloud/SKILL.md
"""
    if str(uri) == "graph://help":
        return """# Microsoft 365 and Entra ID tools

`microsoft365_read` (GET) and `microsoft365_write` (POST, PUT, PATCH, DELETE with a JSON
body) take a Microsoft Graph v1.0 path, for example `me`, `users`, `groups`,
`subscribedSkus`, `me/messages`, `deviceManagement/managedDevices`, `auditLogs/signIns`.

If a tool asks for sign-in (a browser window, or a device code), complete the
Interactive sign-in and retry. For common
paths and query tips, see the `microsoft-cloud` skill:
https://github.com/JackInSightsV2/Azure-M365-MCP/blob/main/skills/microsoft-cloud/SKILL.md
"""
    raise ValueError(f"Unknown resource: {uri}")


async def process_tool_call(
    name: str,
    arguments: Dict[str, Any],
    azure_service: AzureExecutor | None,
    graph_service: GraphExecutor | None,
    arm_service: RestExecutor | None = None,
) -> List[TextContent]:
    """Compatibility wrapper for callers of the original transport helper."""
    result = await ToolApplication(azure_service, graph_service, arm_service).execute_tool(
        name, arguments
    )
    return [TextContent(type="text", text=result.text)]
