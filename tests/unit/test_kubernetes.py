import os
import tempfile

import pytest

from unified_mcp.application import ToolApplication, create_tools
from unified_mcp.cli_tools import ToolLocator
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
# Stands in for the server's own bin directory and the tools directory, so the tools the
# test environment happens to have (such as the bundled az) never leak in.
ABSENT_DIRECTORY = os.path.join(tempfile.gettempdir(), "unified-mcp-tests-absent")


def make_app(runner=None, *, azure=None, environ=None, tools_dir=None, which=None, **settings):
    runner = runner or FakeProcessRunner()
    tools = ToolLocator(
        str(tools_dir or ABSENT_DIRECTORY),
        bundled_dir=ABSENT_DIRECTORY,
        which=which or runner.which,
        windows=False,
    )
    service = KubernetesService(
        Settings(**settings),
        runner=runner,
        environ=environ or {},
        tools=tools,
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


class InstallingRunner(FakeProcessRunner):
    """Fake runner whose 'az aks install-cli' writes kubectl and kubelogin where asked."""

    def __init__(self, results=None, *, install=True):
        super().__init__(results)
        self.install = install

    async def run(self, arguments, timeout, env=None):
        result = await super().run(arguments, timeout, env)
        if self.install and list(arguments[:3]) == ["az", "aks", "install-cli"]:
            for flag in ("--install-location", "--kubelogin-install-location"):
                path = arguments[arguments.index(flag) + 1]
                with open(path, "w", encoding="utf-8"):
                    pass
                os.chmod(path, 0o755)
        return result


def not_on_path(*names):
    """A ``which`` that finds every program except ``names``."""
    return lambda name: None if name in names else f"/usr/local/bin/{name}"


def install_cli_call(tools_dir):
    return [
        "az",
        "aks",
        "install-cli",
        "--install-location",
        os.path.join(str(tools_dir), "kubectl"),
        "--kubelogin-install-location",
        os.path.join(str(tools_dir), "kubelogin"),
        "--only-show-errors",
    ]


@pytest.mark.asyncio
async def test_connect_without_az_explains_how_to_get_it():
    app, runner = make_app(FakeProcessRunner(missing=["az"]))

    result = await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)

    assert result.is_error is True
    assert "az not found" in result.text
    assert "https://aka.ms/installazurecli" in result.text
    assert runner.calls == []


@pytest.mark.asyncio
async def test_connect_without_az_cannot_download_kubectl():
    app, runner = make_app(which=not_on_path("az", "kubectl"))

    result = await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)

    assert result.is_error is True
    assert "az, kubectl not found" in result.text
    assert runner.calls == []


@pytest.mark.asyncio
async def test_connect_downloads_kubectl_and_kubelogin_once(tmp_path):
    tools_dir = tmp_path / "bin"
    app, runner = make_app(
        InstallingRunner(), tools_dir=tools_dir, which=not_on_path("kubectl", "kubelogin")
    )

    first = await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)
    second = await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)
    read = await app.execute_tool("kubernetes_read", {"command": "kubectl get pods"})

    assert first.is_error is False, first.text
    assert second.is_error is False and read.is_error is False
    installs = [call for call in runner.calls if call[:3] == ["az", "aks", "install-cli"]]
    assert installs == [install_cli_call(tools_dir)]
    assert runner.calls[0] == install_cli_call(tools_dir)
    assert (tools_dir / "kubectl").is_file() and (tools_dir / "kubelogin").is_file()


@pytest.mark.asyncio
async def test_kubectl_on_path_is_used_without_downloading(tmp_path):
    app, runner = make_app(tools_dir=tmp_path / "bin")

    await app.execute_tool("kubernetes_connect", CONNECT_ARGUMENTS)
    await app.execute_tool("kubernetes_read", {"command": "kubectl get pods"})

    assert not [call for call in runner.calls if "install-cli" in call]
    assert not (tmp_path / "bin").exists()


@pytest.mark.asyncio
async def test_previously_downloaded_kubectl_is_reused(tmp_path):
    for name in ("kubectl", "kubelogin"):
        path = tmp_path / name
        path.write_text("")
        path.chmod(0o755)
    app, runner = make_app(tools_dir=tmp_path, which=not_on_path("kubectl", "kubelogin"))

    result = await app.execute_tool("kubernetes_read", {"command": "kubectl get pods"})

    assert result.is_error is False
    assert runner.calls == [["kubectl", "get", "pods"]]


@pytest.mark.asyncio
async def test_kubernetes_read_downloads_missing_kubectl_then_runs(tmp_path):
    app, runner = make_app(
        InstallingRunner(), tools_dir=tmp_path, which=not_on_path("kubectl", "kubelogin")
    )

    result = await app.execute_tool("kubernetes_read", {"command": "kubectl get pods"})

    assert result.is_error is False, result.text
    assert runner.calls == [install_cli_call(tmp_path), ["kubectl", "get", "pods"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["kubernetes_connect", "kubernetes_read"])
async def test_failed_download_gives_manual_install_commands(tmp_path, tool):
    runner = InstallingRunner(
        {
            ("az", "aks", "install-cli"): ProcessResult(
                1, "", "ERROR: Connection error while attempting to download client"
            )
        },
        install=False,
    )
    app, runner = make_app(runner, tools_dir=tmp_path, which=not_on_path("kubectl", "kubelogin"))
    arguments = (
        CONNECT_ARGUMENTS if tool == "kubernetes_connect" else {"command": "kubectl get pods"}
    )

    result = await app.execute_tool(tool, arguments)

    assert result.is_error is True
    assert "kubectl not found" in result.text
    assert "az aks install-cli" in result.text
    assert str(tmp_path) in result.text
    assert "Connection error" in result.text
    assert "brew install kubectl Azure/kubelogin/kubelogin" in result.text
    assert "winget install -e --id Kubernetes.kubectl" in result.text
    assert runner.calls == [install_cli_call(tmp_path)]


@pytest.mark.asyncio
async def test_download_that_installs_nothing_is_reported(tmp_path):
    app, runner = make_app(
        InstallingRunner(install=False), tools_dir=tmp_path, which=not_on_path("kubectl")
    )

    result = await app.execute_tool("kubernetes_read", {"command": "kubectl get pods"})

    assert result.is_error is True
    assert "the tools were not installed" in result.text
    assert result.payload["missing_tools"] == ["kubectl"]


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
        "kubectl rollout status deployment/web --timeout=60s",
        "kubectl rollout history deployment/web",
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
async def test_kubectl_vanishing_mid_run_explains_how_to_install():
    runner = FakeProcessRunner(missing=["kubectl"])
    app, runner = make_app(runner, which=not_on_path())

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
    arguments = (
        CONNECT_ARGUMENTS if tool == "kubernetes_connect" else {"command": "kubectl get pods"}
    )

    result = await app.execute_tool(tool, arguments)

    assert result.is_error is True
    assert "ENABLE_KUBERNETES" in result.text


def test_redact_hides_tokens():
    text = redact("token: abc123 password=hunter2 --token=xyz Bearer qwerty")
    for secret in ("abc123", "hunter2", "xyz", "qwerty"):
        assert secret not in text
