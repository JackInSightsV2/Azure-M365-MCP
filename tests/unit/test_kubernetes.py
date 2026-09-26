import pytest

from unified_mcp.application import ToolApplication, create_tools
from unified_mcp.config import Settings
from unified_mcp.process import ProcessResult
from unified_mcp.services.kubernetes_service import KubernetesService, redact
from unified_mcp.testing import (
    FakeAzureCliService,
    FakeAzureRestService,
    FakeGraphService,
    FakeProcessRunner,
)

CONNECT_ARGUMENTS = {
    "subscription": "Contoso Prod",
    "resource_group": "rg-aks",
    "cluster": "aks-prod",
    "namespace": "payments",
}


def make_app(runner=None, *, azure=None, environ=None, **settings):
    runner = runner or FakeProcessRunner()
    service = KubernetesService(
        Settings(**settings),
        runner=runner,
        which=runner.which,
        environ=environ or {},
    )
    app = ToolApplication(
        azure or FakeAzureCliService(),
        FakeGraphService(),
        FakeAzureRestService(),
        kubernetes_service=service,
    )
    return app, runner


def test_kubernetes_tools_carry_hints():
    tools = {tool.name: tool for tool in create_tools()}

    connect = tools["kubernetes_connect"].annotations
    assert connect.readOnlyHint is False and connect.destructiveHint is False
    assert tools["kubernetes_read"].annotations.readOnlyHint is True
    assert tools["kubernetes_read"].annotations.destructiveHint is False
    write = tools["kubernetes_write"].annotations
    assert write.readOnlyHint is False and write.destructiveHint is True


def test_kubernetes_descriptions_use_intent_keywords():
    tools = {t.name: t.description.lower() for t in create_tools()}
    for name in ("kubernetes_read", "kubernetes_write"):
        for term in ("kubernetes", "aks", "kubectl", "pods", "deployments", "namespaces"):
            assert term in tools[name], (name, term)
    assert "logs" in tools["kubernetes_read"]
    for term in ("aks", "kubectl", "kubelogin", "namespace", "subscription"):
        assert term in tools["kubernetes_connect"], term


@pytest.mark.asyncio
async def test_connect_runs_the_manual_steps_in_order():
    runner = FakeProcessRunner(
        {
            ("kubectl", "config", "current-context"): ProcessResult(0, "aks-prod\n", ""),
            ("kubectl", "config", "view"): ProcessResult(0, "payments", ""),
        }
    )
    app, runner = make_app(runner)

    result = await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)

    assert result.is_error is False
    assert runner.calls[:4] == [
        ["az", "account", "set", "--subscription", "Contoso Prod"],
        [
            "az",
            "aks",
            "get-credentials",
            "--resource-group",
            "rg-aks",
            "--name",
            "aks-prod",
            "--overwrite-existing",
        ],
        ["kubelogin", "convert-kubeconfig", "-l", "azurecli"],
        ["kubectl", "config", "set-context", "--current", "--namespace=payments"],
    ]
    assert "Current context: aks-prod" in result.text
    assert "Namespace: payments" in result.text
    assert result.payload["context"] == "aks-prod"


@pytest.mark.asyncio
async def test_connect_without_namespace_skips_set_context_and_reports_default():
    app, runner = make_app(
        FakeProcessRunner({("kubectl", "config", "view"): ProcessResult(0, "", "")})
    )
    arguments = {key: value for key, value in CONNECT_ARGUMENTS.items() if key != "namespace"}

    result = await app.execute_tool("kubernetes_connect", arguments)

    assert result.is_error is False
    assert not [call for call in runner.calls if "set-context" in call]
    assert "Namespace: default" in result.text


@pytest.mark.asyncio
async def test_connect_writes_credentials_to_the_kubeconfig_env_file():
    app, runner = make_app(environ={"KUBECONFIG": "/tmp/work.yaml:/tmp/other.yaml"})

    await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)

    get_credentials = next(call for call in runner.calls if "get-credentials" in call)
    assert get_credentials[-2:] == ["--file", "/tmp/work.yaml"]


@pytest.mark.asyncio
async def test_connect_stops_at_the_first_failing_step():
    runner = FakeProcessRunner(
        {
            ("az", "aks", "get-credentials"): ProcessResult(
                3, "", "ResourceNotFound: The Resource 'aks-prod' was not found."
            )
        }
    )
    app, runner = make_app(runner)

    result = await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)

    assert result.is_error is True
    assert "az aks get-credentials" in result.text
    assert "ResourceNotFound" in result.text
    assert [call[0] for call in runner.calls] == ["az", "az"]
    assert result.payload["completed_steps"] == ["az account set --subscription 'Contoso Prod'"]


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["az", "kubelogin", "kubectl"])
async def test_connect_names_a_missing_tool_and_how_to_install(missing):
    app, runner = make_app(FakeProcessRunner(missing=[missing]))

    result = await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)

    assert result.is_error is True
    assert f"{missing} not found" in result.text
    assert "brew install azure-cli kubectl Azure/kubelogin/kubelogin" in result.text
    assert "az aks install-cli" in result.text
    assert runner.calls == []


@pytest.mark.asyncio
async def test_connect_starts_azure_sign_in_when_the_cli_is_signed_out():
    app, runner = make_app(azure=FakeAzureCliService(failure="Please run 'az login'"))

    result = await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)

    assert result.is_error is True
    assert result.payload["auth_required"] is True
    assert "call kubernetes_connect again" in result.text
    assert runner.calls == []


@pytest.mark.asyncio
async def test_connect_is_denied_by_read_only_policy():
    app, runner = make_app(EXECUTION_POLICY="read-only")

    result = await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)

    assert result.is_error is True
    assert "Execution policy denied" in result.text
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {**CONNECT_ARGUMENTS, "cluster": "--help"},
        {**CONNECT_ARGUMENTS, "namespace": "Bad_Namespace"},
        {"subscription": "sub", "cluster": "aks"},
    ],
)
async def test_connect_rejects_bad_arguments(arguments):
    app, runner = make_app()

    result = await app.execute_tool("kubernetes_connect", arguments)

    assert result.is_error is True
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        "kubectl get pods -A",
        "kubectl describe deploy/web",
        "kubectl logs deploy/web --tail=100",
        "kubectl top pods",
        "kubectl explain pods.spec",
        "kubectl api-resources",
        "kubectl version",
        "kubectl cluster-info",
        "kubectl auth can-i delete pods",
        "kubectl auth whoami",
        "kubectl config get-contexts",
        "kubectl config current-context",
        "kubectl config view",
        "kubectl events --types=Warning",
        "kubectl --context aks-prod get nodes",
    ],
)
async def test_kubernetes_read_runs_read_commands(command):
    app, runner = make_app()

    result = await app.execute_tool("kubernetes_read", {"command": command})

    assert result.is_error is False, result.text
    assert runner.calls[-1][0] == "kubectl"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        "kubectl apply -f deploy.yaml",
        "kubectl delete pod web-123",
        "kubectl scale deploy/web --replicas=3",
        "kubectl rollout restart deploy/web",
        "kubectl label pod web-123 tier=api",
        "kubectl cordon node-1",
        "kubectl exec web-123 -- ls /",
        "kubectl exec web-123 -- grep -i -t x /etc/hosts",
        "kubectl config use-context aks-prod",
        "kubectl auth reconcile -f rbac.yaml",
    ],
)
async def test_kubernetes_read_rejects_writes_and_write_runs_them(command):
    app, runner = make_app()

    rejected = await app.execute_tool("kubernetes_read", {"command": command})
    accepted = await app.execute_tool("kubernetes_write", {"command": command})

    assert rejected.is_error is True
    assert "kubernetes_write" in rejected.text
    assert accepted.is_error is False, accepted.text
    assert len(runner.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["kubectl get pods", "kubectl config view"])
async def test_kubernetes_write_rejects_reads(command):
    app, runner = make_app()

    result = await app.execute_tool("kubernetes_write", {"command": command})

    assert result.is_error is True
    assert "kubernetes_read" in result.text
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "command"),
    [
        ("kubernetes_write", "kubectl exec -it web-123 -- sh"),
        ("kubernetes_write", "kubectl exec -i web-123 -- sh"),
        ("kubernetes_write", "kubectl run debug --image=busybox --tty"),
        ("kubernetes_write", "kubectl run debug --image=busybox --stdin"),
        ("kubernetes_write", "kubectl port-forward svc/web 8080:80"),
        ("kubernetes_write", "kubectl proxy"),
        ("kubernetes_write", "kubectl attach web-123"),
        ("kubernetes_write", "kubectl edit deploy/web"),
        ("kubernetes_read", "kubectl get pods -w"),
        ("kubernetes_read", "kubectl get pods --watch"),
        ("kubernetes_read", "kubectl logs web-123 -f"),
        ("kubernetes_read", "kubectl logs web-123 --follow"),
        ("kubernetes_write", "kubectl apply -f -"),
        ("kubernetes_read", "kubectl config view --raw"),
    ],
)
async def test_interactive_and_long_running_commands_are_rejected(tool, command):
    app, runner = make_app()

    result = await app.execute_tool(tool, {"command": command})

    assert result.is_error is True
    assert "not supported" in result.text or "--raw" in result.text
    assert runner.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["kubernetes_read", "kubernetes_write"])
@pytest.mark.parametrize("command", ["ls -la", "az aks list", "kubectl", "kubectl 'unclosed"])
async def test_non_kubectl_commands_are_rejected(tool, command):
    app, runner = make_app()

    result = await app.execute_tool(tool, {"command": command})

    assert result.is_error is True
    assert runner.calls == []


@pytest.mark.asyncio
async def test_context_and_namespace_are_appended_as_flags():
    app, runner = make_app()

    result = await app.execute_tool(
        "kubernetes_read",
        {"command": "kubectl get pods", "context": "aks-prod", "namespace": "payments"},
    )

    assert result.is_error is False
    assert runner.calls == [
        ["kubectl", "get", "pods", "--context", "aks-prod", "--namespace", "payments"]
    ]


@pytest.mark.asyncio
async def test_shell_metacharacters_stay_literal_arguments():
    app, runner = make_app()

    await app.execute_tool("kubernetes_read", {"command": "kubectl get pods; rm -rf /"})

    assert runner.calls == [["kubectl", "get", "pods;", "rm", "-rf", "/"]]


@pytest.mark.asyncio
async def test_kubectl_failure_is_an_error_with_tokens_redacted():
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJl"
    runner = FakeProcessRunner(
        {("kubectl",): ProcessResult(1, "", f"Unauthorized: Authorization: Bearer {jwt}")}
    )
    app, runner = make_app(runner)

    result = await app.execute_tool(
        "kubernetes_read", {"command": "kubectl get pods --token secret-value"}
    )

    assert result.is_error is True
    assert "Unauthorized" in result.text
    assert jwt not in result.text
    assert "secret-value" not in result.text


@pytest.mark.asyncio
async def test_kubectl_diff_with_differences_is_not_an_error():
    runner = FakeProcessRunner({("kubectl", "diff"): ProcessResult(1, "-replicas: 2", "")})
    app, _ = make_app(runner)

    result = await app.execute_tool("kubernetes_read", {"command": "kubectl diff -f web.yaml"})

    assert result.is_error is False
    assert "-replicas: 2" in result.text


@pytest.mark.asyncio
async def test_missing_kubectl_explains_how_to_install():
    app, runner = make_app(FakeProcessRunner(missing=["kubectl"]))

    result = await app.execute_tool("kubernetes_read", {"command": "kubectl get pods"})

    assert result.is_error is True
    assert "kubectl not found" in result.text
    assert "az aks install-cli" in result.text


@pytest.mark.asyncio
async def test_read_only_policy_allows_kubectl_reads_only():
    app, runner = make_app(EXECUTION_POLICY="read-only")

    read = await app.execute_tool("kubernetes_read", {"command": "kubectl get pods"})
    write = await app.execute_tool("kubernetes_write", {"command": "kubectl delete pod web"})

    assert read.is_error is False
    assert write.is_error is True and "Execution policy denied" in write.text
    assert len(runner.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["kubernetes_connect", "kubernetes_read", "kubernetes_write"])
async def test_kubernetes_tools_report_when_disabled(tool):
    app = ToolApplication(FakeAzureCliService(), FakeGraphService())
    arguments = CONNECT_ARGUMENTS if tool == "kubernetes_connect" else {"command": "kubectl x"}

    result = await app.execute_tool(tool, arguments)

    assert result.is_error is True
    assert "ENABLE_KUBERNETES" in result.text


def test_redact_hides_tokens():
    text = redact("token: abc123 password=hunter2 --token=xyz Bearer qwerty")
    for secret in ("abc123", "hunter2", "xyz", "qwerty"):
        assert secret not in text
