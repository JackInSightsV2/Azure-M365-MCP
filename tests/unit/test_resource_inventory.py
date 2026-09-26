import json
import os
import stat

import pytest

from unified_mcp.application import ToolApplication, create_tools
from unified_mcp.config import Settings
from unified_mcp.resource_inventory import (
    CONSENT_FILENAME,
    INVENTORY_FILENAME,
    MAX_AGE_SECONDS,
    ResourceInventory,
)
from unified_mcp.resource_inventory import main as inventory_main
from unified_mcp.testing import FakeAzureCliService, FakeAzureRestService, FakeGraphService


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def resource(name, group="rg1", subscription="sub-1", kind="microsoft.web/sites"):
    return {
        "name": name,
        "type": kind,
        "subscriptionId": subscription,
        "resourceGroup": group,
        "location": "uksouth",
        "id": f"/subscriptions/{subscription}/resourceGroups/{group}/providers/{kind}/{name}",
        "tags": {"owner": "secret-team"},
        "properties": {"connectionString": "do-not-store"},
    }


def make_app(tmp_path, arm, *, consent=True, clock=None):
    inventory = ResourceInventory(str(tmp_path), clock=clock or Clock())
    if consent:
        inventory.grant()
    app = ToolApplication(FakeAzureCliService(), FakeGraphService(), arm, inventory)
    return app, inventory


async def find(app, name):
    return await app.execute_tool("azure_find_resource", {"name": name})


def test_find_resource_tool_is_read_only_and_intent_rich():
    tool = {t.name: t for t in create_tools()}["azure_find_resource"]

    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    description = tool.description.lower()
    for term in ("subscription", "resource group", "azure", "by name"):
        assert term in description, term
    assert tool.inputSchema["required"] == ["name"]


@pytest.mark.asyncio
async def test_without_consent_explains_opt_in_and_risk(tmp_path):
    arm = FakeAzureRestService([resource("web-prod")])
    app, _ = make_app(tmp_path, arm, consent=False)

    result = await find(app, "web-prod")

    assert result.is_error is True
    assert "Resource inventory is off" in result.text
    assert "whole Azure estate" in result.text
    assert "resource-inventory on" in result.text
    assert arm.resource_graph_queries == 0
    assert not (tmp_path / INVENTORY_FILENAME).exists()


@pytest.mark.asyncio
async def test_with_consent_builds_once_and_finds_by_name(tmp_path):
    arm = FakeAzureRestService(
        [resource("web-prod"), resource("db-prod", "rg-data", "sub-2", "microsoft.sql/servers")],
        page_size=1,
    )
    app, _ = make_app(tmp_path, arm)

    result = await find(app, "DB-PROD")
    again = await find(app, "web-prod")

    assert result.is_error is False
    assert result.payload["matches"] == [
        {
            "name": "db-prod",
            "type": "microsoft.sql/servers",
            "subscriptionId": "sub-2",
            "resourceGroup": "rg-data",
            "location": "uksouth",
            "id": "/subscriptions/sub-2/resourceGroups/rg-data/providers/microsoft.sql/servers/"
            "db-prod",
        }
    ]
    assert "sub-2" in result.text and "rg-data" in result.text
    assert again.payload["matches"][0]["name"] == "web-prod"
    assert arm.resource_graph_queries == 1


@pytest.mark.asyncio
async def test_stores_only_the_six_fields(tmp_path):
    app, _ = make_app(tmp_path, FakeAzureRestService([resource("web-prod")]))

    await find(app, "web-prod")

    stored = json.loads((tmp_path / INVENTORY_FILENAME).read_text())
    assert stored["resources"] == [
        {
            "name": "web-prod",
            "type": "microsoft.web/sites",
            "subscriptionId": "sub-1",
            "resourceGroup": "rg1",
            "location": "uksouth",
            "id": "/subscriptions/sub-1/resourceGroups/rg1/providers/microsoft.web/sites/web-prod",
        }
    ]
    assert "secret-team" not in json.dumps(stored)


@pytest.mark.asyncio
async def test_inventory_file_is_owner_only(tmp_path):
    app, _ = make_app(tmp_path, FakeAzureRestService([resource("web-prod")]))

    await find(app, "web-prod")

    for filename in (INVENTORY_FILENAME, CONSENT_FILENAME):
        mode = stat.S_IMODE(os.stat(tmp_path / filename).st_mode)
        assert mode == 0o600, filename


@pytest.mark.asyncio
async def test_exact_matches_come_before_contains_and_results_are_capped(tmp_path):
    estate = [resource(f"app-{index:02}") for index in range(30)] + [resource("app")]
    app, _ = make_app(tmp_path, FakeAzureRestService(estate))

    result = await find(app, "App")

    assert result.payload["total"] == 31
    assert len(result.payload["matches"]) == 20
    assert result.payload["matches"][0]["name"] == "app"
    assert "first 20 of 31" in result.text


@pytest.mark.asyncio
async def test_stale_inventory_is_rebuilt(tmp_path):
    clock = Clock()
    arm = FakeAzureRestService([resource("web-prod")])
    app, _ = make_app(tmp_path, arm, clock=clock)
    await find(app, "web-prod")

    arm.resources = [resource("web-renamed")]
    clock.now += MAX_AGE_SECONDS - 1
    fresh = await find(app, "web-prod")
    clock.now += 2
    stale = await find(app, "web-prod")

    assert fresh.payload["matches"][0]["name"] == "web-prod"
    assert stale.payload["matches"] == []
    assert json.loads((tmp_path / INVENTORY_FILENAME).read_text())["built_at"] == clock.now


@pytest.mark.asyncio
async def test_miss_rebuilds_once_then_answers(tmp_path):
    arm = FakeAzureRestService([resource("web-prod")])
    app, _ = make_app(tmp_path, arm)
    await find(app, "web-prod")

    arm.resources.append(resource("new-vm"))
    found = await find(app, "new-vm")
    missing = await find(app, "does-not-exist")

    assert found.payload["matches"][0]["name"] == "new-vm"
    assert missing.is_error is False
    assert missing.payload["matches"] == []
    assert "No Azure resource" in missing.text
    assert arm.resource_graph_queries == 3


@pytest.mark.asyncio
async def test_withdrawing_consent_deletes_the_inventory(tmp_path):
    app, inventory = make_app(tmp_path, FakeAzureRestService([resource("web-prod")]))
    await find(app, "web-prod")
    assert (tmp_path / INVENTORY_FILENAME).exists()

    inventory.withdraw()

    assert not (tmp_path / INVENTORY_FILENAME).exists()
    assert not (tmp_path / CONSENT_FILENAME).exists()
    assert "Resource inventory is off" in (await find(app, "web-prod")).text


@pytest.mark.asyncio
async def test_leftover_inventory_is_deleted_when_consent_is_gone(tmp_path):
    app, _ = make_app(tmp_path, FakeAzureRestService([resource("web-prod")]))
    await find(app, "web-prod")
    (tmp_path / CONSENT_FILENAME).unlink()

    result = await find(app, "web-prod")

    assert result.is_error is True
    assert not (tmp_path / INVENTORY_FILENAME).exists()


@pytest.mark.asyncio
async def test_consent_setting_enables_the_inventory(tmp_path):
    inventory = ResourceInventory(str(tmp_path), consent_setting=True, clock=Clock())
    app = ToolApplication(None, None, FakeAzureRestService([resource("web-prod")]), inventory)

    result = await find(app, "web")

    assert result.payload["matches"][0]["name"] == "web-prod"


@pytest.mark.asyncio
async def test_resource_graph_failure_is_reported(tmp_path):
    class FailingArm(FakeAzureRestService):
        async def execute_command(self, command, method="GET", data=None):
            return {
                "success": False,
                "error": "Device code authentication required",
                "auth_required": True,
                "instructions": "Open https://microsoft.com/devicelogin and enter ABC",
            }

    app, _ = make_app(tmp_path, FailingArm())

    result = await find(app, "web-prod")

    assert result.is_error is True
    assert "ABC" in result.text
    assert not (tmp_path / INVENTORY_FILENAME).exists()


def test_cli_turns_consent_on_and_off(tmp_path, capsys):
    settings = Settings(TOKEN_CACHE_DIR=str(tmp_path))
    (tmp_path / INVENTORY_FILENAME).write_text("{}")

    assert inventory_main(["on"], settings) == 0
    assert (tmp_path / CONSENT_FILENAME).exists()
    assert inventory_main(["off"], settings) == 0

    assert not (tmp_path / CONSENT_FILENAME).exists()
    assert not (tmp_path / INVENTORY_FILENAME).exists()
    assert inventory_main(["status"], settings) == 0
    assert "consent: off" in capsys.readouterr().out
