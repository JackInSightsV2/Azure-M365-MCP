"""Opt-in Resource inventory: a local list of the user's Azure resources.

The Resource inventory lets ``azure_find_resource`` answer "which subscription and
resource group is X in?" with one cheap lookup on the server. It is built from a single
Azure Resource Graph query across every subscription the user can see and stores only
each resource's name, type, subscription, resource group, location, and ID; never tags
or properties. Microsoft 365 objects are never included.

The file is a map of the user's whole Azure estate, so it exists only with consent.
Consent is either the ``RESOURCE_INVENTORY`` setting or a consent file beside the token
cache, written and removed by ``unified-microsoft-mcp resource-inventory on|off``.
Withdrawing consent deletes the Resource inventory.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)

INVENTORY_FILENAME = "unified-microsoft-mcp.resource-inventory.json"
CONSENT_FILENAME = "unified-microsoft-mcp.resource-inventory.consent"
RESOURCE_GRAPH_PATH = "providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"
FIELDS = ("name", "type", "subscriptionId", "resourceGroup", "location", "id")
RESOURCE_GRAPH_QUERY = "Resources | project " + ", ".join(FIELDS)
MAX_AGE_SECONDS = 24 * 60 * 60
MAX_MATCHES = 20
_PAGE_SIZE = 1000
_MAX_PAGES = 1000
_FORMAT_VERSION = 1

OPT_IN_COMMAND = (
    "uvx --from git+https://github.com/JackInSightsV2/Azure-M365-MCP "
    "unified-microsoft-mcp resource-inventory on"
)


class ArmQueryExecutor(Protocol):
    """The part of the Azure Resource Manager REST port the Resource inventory needs."""

    async def execute_command(
        self,
        command: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]: ...


class ResourceInventoryError(Exception):
    """The Resource Graph query failed; ``payload`` is the ARM service's result."""

    def __init__(self, payload: Dict[str, Any]) -> None:
        super().__init__(str(payload.get("error", "Resource Graph query failed")))
        self.payload = payload


@dataclass(frozen=True)
class FindResult:
    """Resources matching a name, capped at :data:`MAX_MATCHES`."""

    matches: list[Dict[str, str]]
    total: int
    built_at: float


class ResourceInventory:
    """Build, refresh, search, and delete the Resource inventory file."""

    def __init__(
        self,
        directory: str,
        *,
        consent_setting: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.directory = directory
        self.consent_setting = consent_setting
        self.clock = clock
        self.path = os.path.join(directory, INVENTORY_FILENAME)
        self.consent_path = os.path.join(directory, CONSENT_FILENAME)

    @classmethod
    def from_settings(cls, settings: Any) -> "ResourceInventory":
        return cls(
            settings.token_cache_directory(),
            consent_setting=bool(settings.resource_inventory),
        )

    def has_consent(self) -> bool:
        return self.consent_setting or os.path.exists(self.consent_path)

    def grant(self) -> None:
        """Record consent in an owner-only file beside the token cache."""
        text = (
            "The user consented to a local Resource inventory of their Azure resources.\n"
            "Run 'unified-microsoft-mcp resource-inventory off' to withdraw consent and "
            "delete the Resource inventory.\n"
        )
        self._write_private(self.consent_path, text)

    def withdraw(self) -> None:
        """Remove the consent file and delete the Resource inventory."""
        self._remove(self.consent_path)
        self.delete()

    def delete(self) -> None:
        self._remove(self.path)

    async def find(self, name: str, executor: ArmQueryExecutor) -> FindResult:
        """Match ``name`` against the Resource inventory, rebuilding it when needed.

        The inventory is rebuilt when missing or older than 24 hours, and once more on a
        miss so new or renamed resources are found.
        """
        loaded = self._load()
        rebuilt = False
        if loaded is None or self.clock() - loaded[0] >= MAX_AGE_SECONDS:
            loaded = await self.build(executor)
            rebuilt = True
        built_at, resources = loaded
        matches = self._match(name, resources)
        if not matches and not rebuilt:
            built_at, resources = await self.build(executor)
            matches = self._match(name, resources)
        return FindResult(matches[:MAX_MATCHES], len(matches), built_at)

    async def build(self, executor: ArmQueryExecutor) -> tuple[float, list[Dict[str, str]]]:
        """Run the Resource Graph query across all subscriptions and store the result."""
        resources: list[Dict[str, str]] = []
        skip_token: str | None = None
        for _ in range(_MAX_PAGES):
            options: Dict[str, Any] = {"resultFormat": "objectArray", "$top": _PAGE_SIZE}
            if skip_token:
                options["$skipToken"] = skip_token
            payload = await executor.execute_command(
                RESOURCE_GRAPH_PATH,
                "POST",
                {"query": RESOURCE_GRAPH_QUERY, "options": options},
            )
            if not payload.get("success"):
                raise ResourceInventoryError(payload)
            data = payload.get("data") or {}
            for row in data.get("data") or []:
                if isinstance(row, dict):
                    resources.append({field: str(row.get(field) or "") for field in FIELDS})
            skip_token = data.get("$skipToken")
            if not skip_token:
                break
        else:
            logger.warning("Resource inventory stopped after %d pages", _MAX_PAGES)

        built_at = self.clock()
        document = {"version": _FORMAT_VERSION, "built_at": built_at, "resources": resources}
        self._write_private(self.path, json.dumps(document))
        return built_at, resources

    def _load(self) -> tuple[float, list[Dict[str, str]]] | None:
        try:
            with open(self.path, encoding="utf-8") as handle:
                document = json.load(handle)
            return float(document["built_at"]), list(document["resources"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.warning("Rebuilding unreadable Resource inventory at %s: %s", self.path, error)
            return None

    @staticmethod
    def _match(name: str, resources: list[Dict[str, str]]) -> list[Dict[str, str]]:
        """Exact case-insensitive name matches first, then names that contain ``name``."""
        wanted = name.strip().casefold()
        exact = [r for r in resources if r.get("name", "").casefold() == wanted]
        contains = [
            r
            for r in resources
            if wanted in r.get("name", "").casefold() and r.get("name", "").casefold() != wanted
        ]
        return exact + contains

    def _write_private(self, path: str, text: str) -> None:
        """Write atomically to a file created with mode 0600 (never widened later)."""
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.directory, prefix=".inventory.")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(temporary, path)
        except BaseException:
            self._remove(temporary)
            raise

    @staticmethod
    def _remove(path: str) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def consent_message() -> str:
    """Explain the opt-in and its risk when the Resource inventory is off."""
    return (
        "The Resource inventory is off, so azure_find_resource cannot look resources up.\n\n"
        "When turned on, the server keeps a local file listing the name, type, subscription, "
        "resource group, location, and ID of every Azure resource you can see (no tags or "
        "properties), readable only by your user account. That file is a map of your whole "
        "Azure estate: anyone or any program able to read your files could learn it. It is "
        "created only with your explicit consent.\n\n"
        "To opt in, ask to run the setup skill's Resource inventory step, or run:\n"
        f"  {OPT_IN_COMMAND}\n"
        "Withdraw at any time with 'resource-inventory off', which deletes the file.\n\n"
        "Without it, use azure_read with a Resource Graph query instead: POST "
        f"'{RESOURCE_GRAPH_PATH}' with "
        '{"query": "Resources | where name =~ \'<name>\' | project name, type, '
        'subscriptionId, resourceGroup, location, id"}.'
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unified-microsoft-mcp resource-inventory",
        description=(
            "Turn the opt-in Resource inventory on or off. It is a local file mapping every "
            "Azure resource you can see; 'off' deletes it."
        ),
    )
    parser.add_argument("action", choices=("on", "off", "status"))
    return parser


def main(argv: Optional[Sequence[str]] = None, settings: Any = None) -> int:
    """Entry point for ``unified-microsoft-mcp resource-inventory on|off|status``."""
    arguments = build_parser().parse_args(argv)
    if settings is None:
        from unified_mcp.config import Settings

        settings = Settings()
    inventory = ResourceInventory.from_settings(settings)

    if arguments.action == "on":
        inventory.grant()
        print(
            f"Resource inventory consent recorded in {inventory.consent_path}. It is built "
            "on the first azure_find_resource call."
        )
        return 0
    if arguments.action == "off":
        inventory.withdraw()
        print(f"Resource inventory consent withdrawn and {inventory.path} deleted.")
        if inventory.consent_setting:
            print(
                "RESOURCE_INVENTORY=true is still set in the server environment; remove it "
                "from the client's MCP configuration to fully withdraw consent.",
                file=sys.stderr,
            )
            return 1
        return 0

    state = "on" if inventory.has_consent() else "off"
    present = "present" if os.path.exists(inventory.path) else "absent"
    print(f"Resource inventory consent: {state}. File {inventory.path}: {present}.")
    return 0
