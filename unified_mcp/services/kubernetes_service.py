"""Kubernetes (AKS) access through the user's own kubectl, kubelogin, and Azure CLI."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Dict, Optional

from unified_mcp.config import Settings
from unified_mcp.execution_policy import ExecutionPolicy
from unified_mcp.process import AsyncProcessRunner, ProcessResult, ProcessTimeoutError

INSTALL_HINT = (
    "Install them with 'brew install azure-cli kubectl Azure/kubelogin/kubelogin' (macOS), "
    "or install the Azure CLI and run 'az aks install-cli' to add kubectl and kubelogin. "
    "The Docker image does not include kubectl or kubelogin; run the server on the desktop "
    "for Kubernetes."
)

# kubectl verbs that only read. Every other verb changes the cluster or local config.
_READ_VERBS = frozenset(
    {
        "get",
        "describe",
        "logs",
        "top",
        "explain",
        "api-resources",
        "api-versions",
        "version",
        "cluster-info",
        "events",
        "diff",
    }
)
# Verbs whose read-only status depends on their subcommand.
_READ_SUBCOMMANDS = {
    "auth": frozenset({"can-i", "whoami"}),
    "config": frozenset({"view", "get-contexts", "current-context"}),
}
_INTERACTIVE_VERBS = frozenset({"port-forward", "proxy", "attach", "edit"})
_INTERACTIVE_FLAGS = frozenset({"-i", "-t", "-it", "-ti", "--stdin", "--tty"})
_WATCH_FLAGS = frozenset({"-w", "--watch", "--watch-only"})
_FOLLOW_FLAGS = frozenset({"-f", "--follow"})
_FILENAME_FLAGS = frozenset({"-f", "--filename"})
# Global kubectl flags that take a value, so the token after them is not a command word.
_GLOBAL_VALUE_FLAGS = frozenset(
    {
        "-n",
        "--namespace",
        "--context",
        "--kubeconfig",
        "--cluster",
        "--user",
        "-s",
        "--server",
        "--token",
        "--as",
        "--as-group",
        "--as-uid",
        "--request-timeout",
        "--cache-dir",
        "--certificate-authority",
        "--client-certificate",
        "--client-key",
        "--tls-server-name",
        "-v",
        "--v",
        "--vmodule",
        "--log-file",
        "--profile",
        "--profile-output",
    }
)
_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
_REDACTIONS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"), r"\1<REDACTED>"),
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "<REDACTED>"),
    (re.compile(r"(?i)(--(?:token|password|client-secret)(?:=|\s+))\S+"), r"\1<REDACTED>"),
    (
        re.compile(
            r"(?i)((?:access[-_]?token|refresh[-_]?token|id[-_]?token|client[-_]?secret"
            r"|password|token)[\"']?\s*[:=]\s*[\"']?)[^\s\"',]+"
        ),
        r"\1<REDACTED>",
    ),
)


class KubectlCommandError(ValueError):
    """A kubectl command this server will not run, with the reason as its message."""


@dataclass(frozen=True)
class KubectlCommand:
    """A parsed kubectl command and whether it only reads."""

    arguments: tuple[str, ...]
    verb: str
    subcommand: Optional[str]
    read_only: bool

    @property
    def label(self) -> str:
        return " ".join(part for part in ("kubectl", self.verb, self.subcommand) if part)


def redact(text: str) -> str:
    """Hide bearer tokens, JWTs, and secret-valued flags or fields in ``text``."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def validate_namespace(namespace: str) -> None:
    """Raise ``KubectlCommandError`` unless ``namespace`` is a valid namespace name."""
    if not _NAMESPACE_PATTERN.match(namespace):
        raise KubectlCommandError(
            f"'{namespace}' is not a valid Kubernetes namespace (lowercase letters, digits, "
            "and '-', at most 63 characters)"
        )


def parse_kubectl(command: str) -> KubectlCommand:
    """Parse and classify a kubectl command, rejecting interactive or long-running ones."""
    if "\x00" in command:
        raise KubectlCommandError("The command contains a NUL character")
    try:
        arguments = shlex.split(command, posix=os.name != "nt")
    except ValueError as error:
        raise KubectlCommandError(f"The command could not be parsed: {error}") from error
    if not arguments or arguments[0].lower() != "kubectl":
        raise KubectlCommandError("The command must start with 'kubectl'")

    # Everything after '--' belongs to the program kubectl runs (for example with exec).
    kubectl_arguments = arguments[: arguments.index("--")] if "--" in arguments else arguments
    positionals: list[str] = []
    skip_value = False
    for argument in kubectl_arguments[1:]:
        if skip_value:
            skip_value = False
            continue
        if argument.startswith("-"):
            skip_value = argument in _GLOBAL_VALUE_FLAGS
            continue
        positionals.append(argument)
    if not positionals:
        raise KubectlCommandError("Name a kubectl command, for example 'kubectl get pods'")

    verb = positionals[0].lower()
    subcommand = positionals[1].lower() if len(positionals) > 1 else None
    flags = [
        argument.split("=", 1)[0] for argument in kubectl_arguments if argument.startswith("-")
    ]
    _reject_unsupported(verb, subcommand, kubectl_arguments, flags)

    if verb in _READ_SUBCOMMANDS:
        read_only = subcommand in _READ_SUBCOMMANDS[verb]
    else:
        read_only = verb in _READ_VERBS
    return KubectlCommand(tuple(arguments), verb, subcommand, read_only)


def _reject_unsupported(
    verb: str, subcommand: Optional[str], arguments: list[str], flags: list[str]
) -> None:
    long_running = (
        "The server runs each command to completion without a terminal, so interactive "
        "and long-running kubectl commands are not supported."
    )
    if verb in _INTERACTIVE_VERBS:
        raise KubectlCommandError(
            f"'kubectl {verb}' is interactive or long-running. {long_running}"
        )
    for argument in arguments:
        name, _, value = argument.partition("=")
        if name in _INTERACTIVE_FLAGS and value.lower() != "false":
            raise KubectlCommandError(
                f"'{argument}' needs an interactive terminal. {long_running} Run the command "
                "without -i/-t (for example 'kubectl exec <pod> -- <command>')."
            )
        if name in _WATCH_FLAGS and value.lower() != "false":
            raise KubectlCommandError(
                f"'{argument}' watches until stopped. {long_running} Run it without the watch flag."
            )
        if verb == "logs" and name in _FOLLOW_FLAGS and value.lower() != "false":
            raise KubectlCommandError(
                f"'{argument}' follows logs until stopped. {long_running} Use '--tail=<lines>' "
                "or '--since=<duration>' instead."
            )
    if verb != "logs":
        for index, argument in enumerate(arguments):
            name, _, value = argument.partition("=")
            if name in _FILENAME_FLAGS and (
                value == "-" or (not value and arguments[index + 1 : index + 2] == ["-"])
            ):
                raise KubectlCommandError(
                    "Reading a manifest from standard input ('-f -') is not supported. Pass a "
                    "file path or URL to -f, or use a command such as 'kubectl create' or "
                    "'kubectl set'."
                )
    if verb == "config" and subcommand == "view" and "--raw" in flags:
        raise KubectlCommandError(
            "'kubectl config view --raw' prints credentials. Run 'kubectl config view' instead."
        )


class KubernetesService:
    """Run kubectl and the AKS connection steps with the user's own tools and kubeconfig."""

    def __init__(
        self,
        settings: Settings,
        *,
        runner: AsyncProcessRunner | None = None,
        policy: ExecutionPolicy | None = None,
        which: Callable[[str], Optional[str]] = shutil.which,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.runner = runner or AsyncProcessRunner()
        self.policy = policy or settings.build_execution_policy()
        self.which = which
        self.environ = os.environ if environ is None else environ
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_commands)
        self.logger = logging.getLogger(__name__)

    def missing_tools(self, names: Sequence[str]) -> list[str]:
        """Return the command-line tools in ``names`` that are not on PATH."""
        return [name for name in names if self.which(name) is None]

    @staticmethod
    def missing_tools_message(missing: Sequence[str]) -> str:
        return f"{', '.join(missing)} not found on this machine's PATH. {INSTALL_HINT}"

    async def run_kubectl(
        self,
        command: KubectlCommand,
        *,
        context: Optional[str] = None,
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a parsed kubectl command with optional context and namespace flags."""
        decision = self.policy.check_kubernetes(
            list(command.arguments), read_only=command.read_only
        )
        if not decision.allowed:
            return self._failure(f"Execution policy denied command - {decision.reason}")
        missing = self.missing_tools(["kubectl"])
        if missing:
            return self._failure(self.missing_tools_message(missing), missing_tools=missing)

        arguments = list(command.arguments)
        if context is not None:
            arguments.extend(["--context", context])
        if namespace is not None:
            arguments.extend(["--namespace", namespace])

        result = await self._run(arguments)
        # 'kubectl diff' exits 1 when it found differences; that is a successful answer.
        ok = result.returncode == 0 or (command.verb == "diff" and result.returncode == 1)
        if ok:
            output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
            return {"success": True, "command": self._display(arguments), "output": output}
        return self._failure(self._error_text(result, arguments), command=self._display(arguments))

    async def connect(
        self,
        subscription: str,
        resource_group: str,
        cluster: str,
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Select the subscription, fetch AKS credentials, convert them, and set a namespace.

        Stops at the first step that fails and returns that step's output.
        """
        refusal = self.preflight_connect(resource_group, cluster)
        if refusal is not None:
            return refusal

        steps: list[list[str]] = [
            ["az", "account", "set", "--subscription", subscription],
            self._get_credentials_arguments(resource_group, cluster),
            ["kubelogin", "convert-kubeconfig", "-l", "azurecli"],
        ]
        if namespace is not None:
            steps.append(
                ["kubectl", "config", "set-context", "--current", f"--namespace={namespace}"]
            )

        completed: list[str] = []
        for step in steps:
            result = await self._run(step)
            if result.returncode != 0:
                return self._failure(
                    self._error_text(result, step),
                    failed_step=self._display(step),
                    completed_steps=completed,
                )
            completed.append(self._display(step))

        context = await self._run(["kubectl", "config", "current-context"])
        current_namespace = await self._run(
            ["kubectl", "config", "view", "--minify", "-o", "jsonpath={..namespace}"]
        )
        return {
            "success": True,
            "context": context.stdout.strip() if context.returncode == 0 else None,
            "namespace": (
                (current_namespace.stdout.strip() or "default")
                if current_namespace.returncode == 0
                else namespace
            ),
            "completed_steps": completed,
        }

    def preflight_connect(self, resource_group: str, cluster: str) -> Optional[Dict[str, Any]]:
        """Return a failure when policy forbids connecting or a required tool is missing."""
        get_credentials = self._get_credentials_arguments(resource_group, cluster)
        decision = self.policy.check_azure(shlex.join(get_credentials))
        if not decision.allowed:
            return self._failure(f"Execution policy denied command - {decision.reason}")
        missing = self.missing_tools(["az", "kubelogin", "kubectl"])
        if missing:
            return self._failure(self.missing_tools_message(missing), missing_tools=missing)
        return None

    def _get_credentials_arguments(self, resource_group: str, cluster: str) -> list[str]:
        arguments = [
            "az",
            "aks",
            "get-credentials",
            "--resource-group",
            resource_group,
            "--name",
            cluster,
            "--overwrite-existing",
        ]
        kubeconfig = self._kubeconfig_path()
        if kubeconfig:
            # az aks get-credentials ignores KUBECONFIG; kubectl and kubelogin honour it.
            arguments.extend(["--file", kubeconfig])
        return arguments

    def _kubeconfig_path(self) -> Optional[str]:
        value = self.environ.get("KUBECONFIG", "")
        first = value.split(os.pathsep)[0].strip() if value else ""
        return first or None

    async def _run(self, arguments: list[str]) -> ProcessResult:
        self.logger.debug("Running: %s", self._display(arguments))
        try:
            async with self._semaphore:
                return await self.runner.run(arguments, timeout=self.settings.command_timeout)
        except ProcessTimeoutError:
            return ProcessResult(
                124, "", f"Timed out after {self.settings.command_timeout} seconds"
            )
        except FileNotFoundError:
            return ProcessResult(127, "", self.missing_tools_message([arguments[0]]))
        except Exception as error:
            return ProcessResult(1, "", str(error))

    @staticmethod
    def _display(arguments: Sequence[str]) -> str:
        return redact(shlex.join(arguments))

    @classmethod
    def _error_text(cls, result: ProcessResult, arguments: Sequence[str]) -> str:
        detail = (result.stderr or result.stdout or "Command failed").strip()
        return f"Command: {cls._display(arguments)}\n{redact(detail)}"

    @staticmethod
    def _failure(message: str, **fields: Any) -> Dict[str, Any]:
        return {"success": False, "error": message, **fields}

    async def close(self) -> None:
        """Match the service lifecycle contract; no process outlives a call."""
