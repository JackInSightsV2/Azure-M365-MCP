"""Transport-independent tool definitions and execution core."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Protocol

from mcp.types import Resource, TextContent, Tool
from pydantic import AnyUrl, BaseModel, ConfigDict, Field, ValidationError

SERVER_INSTRUCTIONS = (
    "Use execute_azure_cli_command for Azure CLI commands beginning with 'az'. "
    "Use graph_command for Microsoft Graph v1.0 paths and an explicit HTTP method for writes. "
    "Prefer read operations, inspect help resources before unfamiliar actions, and never place "
    "credentials in tool arguments. Authentication prompts may require the user to complete "
    "device sign-in and retry."
)


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


class AzureToolInput(BaseModel):
    """Typed Azure CLI tool input."""

    command: str = Field(min_length=1)
    model_config = ConfigDict(extra="forbid")


class GraphToolInput(BaseModel):
    """Typed Microsoft Graph tool input."""

    command: str = Field(min_length=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    data: Optional[Dict[str, Any]] = None
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
    ) -> None:
        self.azure_service = azure_service
        self.graph_service = graph_service
        self.logger = logging.getLogger(__name__)

    async def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> ToolExecutionResult:
        if name == "execute_azure_cli_command":
            if self.azure_service is None:
                return self._error(name, "Azure CLI service not initialized")
            try:
                request = AzureToolInput.model_validate(arguments)
            except ValidationError as error:
                return self._error(name, self._validation_message(error))
            payload = await self.azure_service.execute_azure_cli(request.command)
            is_error = payload.startswith("Error:") or "\nError:" in payload
            return ToolExecutionResult(name, payload, payload, is_error)

        if name == "graph_command":
            if self.graph_service is None:
                return self._error(name, "Graph service not initialized")
            try:
                graph_request = GraphToolInput.model_validate(arguments)
            except ValidationError as error:
                return self._error(name, self._validation_message(error))
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
        for service in (self.azure_service, self.graph_service):
            if service is None:
                continue
            try:
                await service.close()
            except Exception as error:
                errors.append(error)
        if errors:
            raise errors[0]


def create_tools() -> list[Tool]:
    """Return the canonical tool schemas exposed by every MCP transport."""
    return [
        Tool(
            name="execute_azure_cli_command",
            description=(
                "Execute an Azure CLI command. Commands must begin with 'az' and are subject "
                "to the configured execution policy."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Azure CLI command, for example 'az account show'",
                    }
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="graph_command",
            description=(
                "Call a Microsoft Graph v1.0 endpoint with GET, POST, PUT, PATCH, or DELETE."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Graph path such as 'me', 'users', or 'groups'",
                    },
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                        "default": "GET",
                    },
                    "data": {"type": "object", "description": "Body for write requests"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        ),
    ]


def create_resources() -> list[Resource]:
    """Return concise operational help resources."""
    return [
        Resource(
            uri=AnyUrl("azure://help"),
            name="Azure CLI Help",
            description="Authentication, policy, and Azure CLI examples",
            mimeType="text/markdown",
        ),
        Resource(
            uri=AnyUrl("graph://help"),
            name="Microsoft Graph Help",
            description="Authentication, policy, and Graph request examples",
            mimeType="text/markdown",
        ),
    ]


def read_resource(uri: AnyUrl) -> str:
    """Read a canonical help resource."""
    if str(uri) == "azure://help":
        return """# Azure CLI tool

Use `execute_azure_cli_command` with a command beginning with `az`.

- Interactive: call `az login` and complete the device flow.
- Automation: configure service-principal credentials or managed identity.
- Policy: `EXECUTION_POLICY` can be `unrestricted`, `read-only`, or `allowlist`.

Examples: `az account show`, `az group list`, `az vm list`.
Commands are parsed without a shell and sensitive flags are redacted from logs.
"""
    if str(uri) == "graph://help":
        return """# Microsoft Graph tool

Use `graph_command` with a Graph v1.0 path such as `me`, `users`, or `groups`.
The default method is GET; POST, PUT, PATCH, and DELETE require suitable application permissions.

Device-code authentication is used by default. Managed identity and client-secret application
authentication are supported for automation. `EXECUTION_POLICY=read-only` permits only GET.
"""
    raise ValueError(f"Unknown resource: {uri}")


async def process_tool_call(
    name: str,
    arguments: Dict[str, Any],
    azure_service: AzureExecutor | None,
    graph_service: GraphExecutor | None,
) -> List[TextContent]:
    """Compatibility wrapper for callers of the original transport helper."""
    result = await ToolApplication(azure_service, graph_service).execute_tool(name, arguments)
    return [TextContent(type="text", text=result.text)]
