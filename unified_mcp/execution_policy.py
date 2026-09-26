"""Execution policy for Azure CLI and Microsoft Graph operations."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from enum import Enum


class ExecutionPolicyMode(str, Enum):
    """Supported command authorization modes."""

    UNRESTRICTED = "unrestricted"
    READ_ONLY = "read-only"
    ALLOWLIST = "allowlist"


@dataclass(frozen=True)
class PolicyDecision:
    """Result of checking a command against policy."""

    allowed: bool
    reason: str | None = None


class ExecutionPolicy:
    """Authorize tool operations before authentication or external execution."""

    _READ_ONLY_AZURE_ACTIONS = {
        "check",
        "exists",
        "find",
        "get",
        "get-instance-view",
        "list",
        "query",
        "show",
        "what-if",
    }
    # Read-shaped actions that change local state (for example, writing kubeconfig).
    _LOCAL_SIDE_EFFECT_ACTIONS = {"get-credentials"}

    def __init__(
        self,
        mode: ExecutionPolicyMode = ExecutionPolicyMode.UNRESTRICTED,
        azure_allowlist: tuple[str, ...] = (),
        graph_allowlist: tuple[str, ...] = (),
    ) -> None:
        self.mode = mode
        self.azure_allowlist = azure_allowlist
        self.graph_allowlist = graph_allowlist

    def check_azure(self, command: str) -> PolicyDecision:
        """Authorize an Azure CLI command."""
        if self.mode is ExecutionPolicyMode.UNRESTRICTED:
            return PolicyDecision(True)

        try:
            arguments = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            return PolicyDecision(False, "Azure CLI command could not be parsed")

        normalized = " ".join(arguments)
        if self.mode is ExecutionPolicyMode.ALLOWLIST:
            if any(
                self._matches_token_prefix(arguments, prefix) for prefix in self.azure_allowlist
            ):
                return PolicyDecision(True)
            return PolicyDecision(False, "Azure CLI command is not in AZURE_COMMAND_ALLOWLIST")

        if [argument.lower() for argument in arguments[:2]] == ["az", "login"]:
            return PolicyDecision(True)
        if "--help" in arguments or "-h" in arguments or arguments == ["az", "--version"]:
            return PolicyDecision(True)
        if len(arguments) > 1 and arguments[1] == "rest":
            return PolicyDecision(False, "'az rest' is not permitted by read-only policy")

        command_path: list[str] = []
        for argument in arguments[1:]:
            if argument.startswith("-"):
                break
            command_path.append(argument.lower())
        if command_path and self._is_read_only_action(command_path[-1]):
            return PolicyDecision(True)
        return PolicyDecision(
            False, f"Azure CLI command is not recognized as read-only: {normalized}"
        )

    def check_kubernetes(self, arguments: list[str], *, read_only: bool) -> PolicyDecision:
        """Authorize a parsed kubectl command already classified as read or write.

        In allowlist mode kubectl prefixes (for example ``kubectl get``) are listed in
        AZURE_COMMAND_ALLOWLIST alongside Azure CLI prefixes.
        """
        if self.mode is ExecutionPolicyMode.UNRESTRICTED:
            return PolicyDecision(True)
        if self.mode is ExecutionPolicyMode.READ_ONLY:
            if read_only:
                return PolicyDecision(True)
            return PolicyDecision(False, "kubectl changes are disabled by read-only policy")
        if any(self._matches_token_prefix(arguments, prefix) for prefix in self.azure_allowlist):
            return PolicyDecision(True)
        return PolicyDecision(False, "kubectl command is not in AZURE_COMMAND_ALLOWLIST")

    @classmethod
    def _is_read_only_action(cls, action: str) -> bool:
        """Exact read actions, plus variants such as 'list-locations' or 'show-tags'."""
        if action in cls._READ_ONLY_AZURE_ACTIONS:
            return True
        if action in cls._LOCAL_SIDE_EFFECT_ACTIONS:
            return False
        return action.startswith(("list-", "show-", "get-"))

    def check_graph(self, command: str, method: str) -> PolicyDecision:
        """Authorize a Microsoft Graph request."""
        method = method.upper()
        if self.mode is ExecutionPolicyMode.UNRESTRICTED:
            return PolicyDecision(True)
        if self.mode is ExecutionPolicyMode.READ_ONLY:
            if method == "GET":
                return PolicyDecision(True)
            return PolicyDecision(False, "Microsoft Graph writes are disabled by read-only policy")

        request = f"{method} /{command.lstrip('/')}"
        if any(self._matches_graph_prefix(request, prefix) for prefix in self.graph_allowlist):
            return PolicyDecision(True)
        return PolicyDecision(False, "Microsoft Graph request is not in GRAPH_REQUEST_ALLOWLIST")

    @staticmethod
    def _matches_token_prefix(arguments: list[str], prefix: str) -> bool:
        try:
            prefix_arguments = shlex.split(prefix, posix=os.name != "nt")
        except ValueError:
            return False
        return arguments[: len(prefix_arguments)] == prefix_arguments

    @staticmethod
    def _matches_graph_prefix(request: str, prefix: str) -> bool:
        normalized = prefix.rstrip("/")
        return request == normalized or request.startswith((f"{normalized}/", f"{normalized}?"))
