import pytest

from unified_mcp.config import Settings
from unified_mcp.execution_policy import ExecutionPolicy, ExecutionPolicyMode


def test_unrestricted_policy_preserves_existing_behavior():
    policy = ExecutionPolicy()

    assert policy.check_azure("az group delete --name demo").allowed
    assert policy.check_graph("users/id", "DELETE").allowed


@pytest.mark.parametrize(
    "command",
    ["az account show", "az group list", "az resource exists --ids /resource", "az --version"],
)
def test_read_only_policy_allows_known_azure_reads(command):
    policy = ExecutionPolicy(ExecutionPolicyMode.READ_ONLY)

    assert policy.check_azure(command).allowed


@pytest.mark.parametrize(
    "command",
    [
        "az group create --name list",
        "az group delete --name demo",
        "az rest --method GET --url https://management.azure.com/",
    ],
)
def test_read_only_policy_denies_azure_mutations_and_escape_hatch(command):
    policy = ExecutionPolicy(ExecutionPolicyMode.READ_ONLY)

    assert not policy.check_azure(command).allowed


def test_read_only_policy_allows_only_graph_get():
    policy = ExecutionPolicy(ExecutionPolicyMode.READ_ONLY)

    assert policy.check_graph("users", "GET").allowed
    assert not policy.check_graph("users", "PATCH").allowed


def test_allowlist_policy_matches_command_and_path_boundaries():
    policy = ExecutionPolicy(
        ExecutionPolicyMode.ALLOWLIST,
        azure_allowlist=("az account show", "az group list"),
        graph_allowlist=("GET /users",),
    )

    assert policy.check_azure("az account show --output json").allowed
    assert not policy.check_azure("az account list").allowed
    assert policy.check_graph("users/id", "GET").allowed
    assert not policy.check_graph("users-internal", "GET").allowed
    assert not policy.check_graph("users", "DELETE").allowed


def test_settings_parse_execution_policy_and_allowlists():
    settings = Settings(
        EXECUTION_POLICY="allowlist",
        AZURE_COMMAND_ALLOWLIST="az account show,az group list",
        GRAPH_REQUEST_ALLOWLIST="GET /users,GET /groups",
    )

    assert settings.execution_policy is ExecutionPolicyMode.ALLOWLIST
    assert settings.azure_command_allowlist == ["az account show", "az group list"]
    assert settings.graph_request_allowlist == ["GET /users", "GET /groups"]
