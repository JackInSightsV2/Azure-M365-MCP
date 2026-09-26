"""Write this server's MCP entry into the configuration of a supported AI client.

Run it with ``uvx`` so nothing needs installing first::

    uvx --from git+https://github.com/JackInSightsV2/Azure-M365-MCP \\
        unified-microsoft-mcp install --client cursor

Each client keeps MCP servers in its own file and format. The installer merges the
``azure-m365`` entry into that file, leaves every other setting and server untouched,
and rewrites nothing when the entry is already current, so it is safe to re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Sequence

import tomlkit
from tomlkit.exceptions import TOMLKitError

SERVER_NAME = "azure-m365"
REPOSITORY_URL = "https://github.com/JackInSightsV2/Azure-M365-MCP"
DOCKER_IMAGE = "ghcr.io/jackinsightsv2/azure-m365-mcp:latest"
CONSOLE_SCRIPT = "unified-microsoft-mcp"

CLIENTS = ("claude-code", "vscode", "cursor", "codex", "claude-desktop")


class Scope(str, Enum):
    """Where the entry applies: one project directory, or every session of the user."""

    PROJECT = "project"
    USER = "user"


class Launch(str, Enum):
    """How the client starts the server."""

    UVX = "uvx"
    DOCKER = "docker"


DEFAULT_SCOPES: dict[str, Scope] = {
    "claude-code": Scope.PROJECT,
    "vscode": Scope.PROJECT,
    "cursor": Scope.PROJECT,
    "codex": Scope.USER,
    "claude-desktop": Scope.USER,
}


class InstallError(Exception):
    """Raised when a client, scope, or existing configuration cannot be handled safely."""


@dataclass(frozen=True)
class InstallResult:
    client: str
    scope: Scope
    path: Path
    changed: bool


def launch_command(launch: Launch = Launch.UVX) -> tuple[str, list[str]]:
    """Return the command and arguments a client runs to start the server."""
    if launch is Launch.DOCKER:
        return "docker", [
            "run",
            "--rm",
            "-i",
            "-v",
            "unified-microsoft-mcp-azure:/home/app/.azure",
            "-v",
            "unified-microsoft-mcp-identity:/home/app/.IdentityService",
            DOCKER_IMAGE,
        ]
    return "uvx", ["--from", f"git+{REPOSITORY_URL}", CONSOLE_SCRIPT]


def _user_data_directory(base_dir: Path, platform: str) -> Path:
    """Return the per-user application data directory relative to a home directory."""
    if platform == "darwin":
        return base_dir / "Library" / "Application Support"
    if platform.startswith("win"):
        return base_dir / "AppData" / "Roaming"
    return base_dir / ".config"


def config_path(client: str, base_dir: Path, scope: Scope, platform: str = sys.platform) -> Path:
    """Return the configuration file for ``client``.

    ``base_dir`` is the project directory for project scope and the home directory for
    user scope.
    """
    if client == "claude-code":
        return base_dir / (".mcp.json" if scope is Scope.PROJECT else ".claude.json")
    if client == "vscode":
        if scope is Scope.PROJECT:
            return base_dir / ".vscode" / "mcp.json"
        return _user_data_directory(base_dir, platform) / "Code" / "User" / "mcp.json"
    if client == "cursor":
        return base_dir / ".cursor" / "mcp.json"
    if client == "codex":
        return base_dir / ".codex" / "config.toml"
    if client == "claude-desktop":
        if scope is Scope.PROJECT:
            raise InstallError("claude-desktop has no project configuration; use --scope user")
        return _user_data_directory(base_dir, platform) / "Claude" / "claude_desktop_config.json"
    raise InstallError(f"Unknown client '{client}'. Choose one of: {', '.join(CLIENTS)}")


def server_entry(client: str, launch: Launch = Launch.UVX) -> dict[str, Any]:
    """Return the server entry in the shape ``client`` expects."""
    command, args = launch_command(launch)
    entry: dict[str, Any] = {"command": command, "args": args}
    if client in ("claude-code", "vscode"):
        entry = {"type": "stdio", **entry}
    return entry


def _servers_key(client: str) -> str:
    if client == "vscode":
        return "servers"
    if client == "codex":
        return "mcp_servers"
    return "mcpServers"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _merge_json(path: Path, servers_key: str, entry: dict[str, Any]) -> bool:
    document: dict[str, Any] = {}
    if path.exists() and path.read_text(encoding="utf-8").strip():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise InstallError(
                f"{path} is not plain JSON ({error}); add the entry by hand or remove comments"
            ) from error
        if not isinstance(loaded, dict):
            raise InstallError(f"{path} does not contain a JSON object")
        document = loaded

    servers = document.setdefault(servers_key, {})
    if not isinstance(servers, dict):
        raise InstallError(f"'{servers_key}' in {path} is not an object")
    if servers.get(SERVER_NAME) == entry:
        return False
    servers[SERVER_NAME] = entry
    _atomic_write(path, json.dumps(document, indent=2) + "\n")
    return True


def _merge_toml(path: Path, servers_key: str, entry: dict[str, Any]) -> bool:
    document = tomlkit.document()
    if path.exists():
        try:
            document = tomlkit.parse(path.read_text(encoding="utf-8"))
        except TOMLKitError as error:
            raise InstallError(f"{path} is not valid TOML ({error})") from error

    servers = document.get(servers_key)
    if servers is None:
        servers = tomlkit.table(is_super_table=True)
        document[servers_key] = servers
    elif not isinstance(servers, dict):
        raise InstallError(f"'{servers_key}' in {path} is not a table")
    existing = servers.get(SERVER_NAME)
    if existing is not None and existing.unwrap() == entry:
        return False

    table = tomlkit.table()
    table["command"] = entry["command"]
    table["args"] = entry["args"]
    servers[SERVER_NAME] = table
    _atomic_write(path, tomlkit.dumps(document))
    return True


def install(
    client: str,
    base_dir: Path,
    scope: Optional[Scope] = None,
    launch: Launch = Launch.UVX,
    platform: str = sys.platform,
) -> InstallResult:
    """Merge the ``azure-m365`` entry into ``client``'s configuration under ``base_dir``."""
    if client not in CLIENTS:
        raise InstallError(f"Unknown client '{client}'. Choose one of: {', '.join(CLIENTS)}")
    resolved_scope = scope or DEFAULT_SCOPES[client]
    path = config_path(client, Path(base_dir), resolved_scope, platform)
    entry = server_entry(client, launch)
    if client == "codex":
        changed = _merge_toml(path, _servers_key(client), entry)
    else:
        changed = _merge_json(path, _servers_key(client), entry)
    return InstallResult(client=client, scope=resolved_scope, path=path, changed=changed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"{CONSOLE_SCRIPT} install",
        description=f"Add the '{SERVER_NAME}' MCP server to an AI client's configuration.",
    )
    parser.add_argument("--client", required=True, choices=CLIENTS)
    parser.add_argument(
        "--scope",
        choices=[scope.value for scope in Scope],
        help="project (current directory) or user (home directory). "
        "Default: project for claude-code, vscode, and cursor; user for codex and "
        "claude-desktop.",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        help="Override the base directory (project root or home directory).",
    )
    parser.add_argument(
        "--launch",
        choices=[launch.value for launch in Launch],
        default=Launch.UVX.value,
        help="How the client starts the server (default: uvx).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = build_parser().parse_args(argv)
    scope = Scope(arguments.scope) if arguments.scope else DEFAULT_SCOPES[arguments.client]
    base_dir = arguments.dir or (Path.cwd() if scope is Scope.PROJECT else Path.home())
    try:
        result = install(arguments.client, base_dir, scope, Launch(arguments.launch))
    except InstallError as error:
        print(f"Install failed: {error}", file=sys.stderr)
        return 1
    if result.changed:
        print(f"Wrote '{SERVER_NAME}' to {result.path}. Restart {result.client} to load it.")
    else:
        print(f"'{SERVER_NAME}' is already up to date in {result.path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
