import json
from pathlib import Path

import pytest

from unified_mcp.installer import SERVER_NAME, launch_command

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_MANIFEST = REPOSITORY_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_MANIFEST = REPOSITORY_ROOT / ".claude-plugin" / "marketplace.json"
VERIFIER_AGENT = REPOSITORY_ROOT / "agents" / "tenant-verifier.md"
READ_TOOLS = {"microsoft365_read", "azure_read", "azure_find_resource", "kubernetes_read"}
COMPONENT_KEYS = ("skills", "commands", "agents", "hooks", "outputStyles", "lspServers")


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _paths(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _frontmatter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    block, _, _ = text[4:].partition("\n---\n")
    fields = {}
    for line in block.splitlines():
        key, separator, value = line.partition(":")
        if separator and not line.startswith(" "):
            fields[key.strip()] = value.strip()
    return fields


def test_marketplace_lists_the_plugin_from_this_repository():
    marketplace = _load(MARKETPLACE_MANIFEST)
    plugin = _load(PLUGIN_MANIFEST)

    assert marketplace["name"] and marketplace["owner"]["name"]
    [entry] = marketplace["plugins"]
    assert entry["name"] == plugin["name"]
    assert entry["source"].startswith("./") and ".." not in entry["source"]
    assert (REPOSITORY_ROOT / entry["source"] / ".claude-plugin" / "plugin.json").is_file()


def test_plugin_component_paths_exist():
    plugin = _load(PLUGIN_MANIFEST)

    for key in COMPONENT_KEYS:
        for relative in _paths(plugin.get(key)):
            assert relative.startswith("./"), f"{key} path {relative} must start with ./"
            assert (REPOSITORY_ROOT / relative).exists(), f"{key} path {relative} is missing"
    for relative in _paths(plugin.get("mcpServers")):
        assert (REPOSITORY_ROOT / relative).exists(), f"mcpServers path {relative} is missing"


def test_plugin_server_matches_the_installer():
    plugin = _load(PLUGIN_MANIFEST)
    command, args = launch_command()

    server = plugin["mcpServers"][SERVER_NAME]
    assert server["command"] == command
    assert server["args"] == args


def test_plugin_provides_setup_and_microsoft_cloud_skills():
    skills = {path.parent.name for path in (REPOSITORY_ROOT / "skills").glob("*/SKILL.md")}

    assert {"setup", "microsoft-cloud"} <= skills


@pytest.mark.parametrize(
    "skill", sorted((REPOSITORY_ROOT / "skills").glob("*/SKILL.md")), ids=lambda p: p.parent.name
)
def test_skill_frontmatter_has_name_and_description(skill):
    fields = _frontmatter(skill)

    assert fields.get("name") == skill.parent.name
    assert fields.get("description")


def test_verifier_agent_has_name_and_description():
    fields = _frontmatter(VERIFIER_AGENT)

    assert fields.get("name") == "tenant-verifier"
    assert fields.get("description")


def test_verifier_agent_has_read_tools_only():
    plugin = _load(PLUGIN_MANIFEST)
    tools = [tool.strip() for tool in _frontmatter(VERIFIER_AGENT)["tools"].split(",")]

    plugin_prefix = f"mcp__plugin_{plugin['name']}_{SERVER_NAME}__"
    assert {plugin_prefix + name for name in READ_TOOLS} <= set(tools)
    for tool in tools:
        assert tool.startswith("mcp__"), f"{tool} is not an MCP tool"
        assert tool.rpartition("__")[2] in READ_TOOLS, f"{tool} is not a Read tool"
