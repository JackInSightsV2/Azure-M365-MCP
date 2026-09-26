import asyncio
import os
import sys

import pytest

from unified_mcp.cli_tools import ToolLocator
from unified_mcp.config import Settings
from unified_mcp.process import AsyncProcessRunner


def make_tool(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("")
    path.chmod(0o755)
    return str(path)


def on_path(**found):
    """A ``which`` that finds only the programs given, at the paths given."""
    return lambda name: found.get(name)


@pytest.fixture
def dirs(tmp_path):
    return tmp_path / "venv-bin", tmp_path / "tools"


def locator(dirs, which=None, *, windows=False, path="/usr/bin"):
    bundled, tools = dirs
    return ToolLocator(
        str(tools),
        bundled_dir=str(bundled),
        which=which or on_path(),
        environ={"PATH": path},
        windows=windows,
    )


def test_path_wins_over_bundled_and_downloaded_tools(dirs):
    bundled, tools = dirs
    make_tool(bundled, "az")
    make_tool(tools, "kubectl")

    found = locator(dirs, on_path(az="/opt/bin/az", kubectl="/opt/bin/kubectl"))

    assert found.find("az") == "/opt/bin/az"
    assert found.find("kubectl") == "/opt/bin/kubectl"


def test_bundled_az_is_used_when_az_is_not_on_path(dirs):
    bundled, tools = dirs
    expected = make_tool(bundled, "az")
    make_tool(tools, "az")

    assert locator(dirs).find("az") == expected


def test_downloaded_tools_are_used_last(dirs):
    _, tools = dirs
    expected = make_tool(tools, "kubelogin")

    found = locator(dirs)

    assert found.find("kubelogin") == expected
    assert found.find("kubectl") is None


@pytest.mark.skipif(os.name == "nt", reason="Windows has no executable bit")
def test_non_executable_files_are_ignored(dirs):
    _, tools = dirs
    tools.mkdir(parents=True)
    (tools / "kubectl").write_text("")

    assert locator(dirs).find("kubectl") is None


def test_windows_names(dirs):
    bundled, tools = dirs
    az = make_tool(bundled, "az.bat")
    kubectl = make_tool(tools, "kubectl.exe")

    found = locator(dirs, windows=True)

    assert found.find("az") == az
    assert found.find("kubectl") == kubectl
    assert found.installed_path("kubelogin") == os.path.join(str(tools), "kubelogin.exe")
    assert locator(dirs).installed_path("kubelogin") == os.path.join(str(tools), "kubelogin")


def test_windows_runs_tools_on_path_by_full_path(dirs):
    found = locator(dirs, on_path(az=r"C:\CLI\az.cmd"), windows=True)

    arguments, env = found.prepare(["az", "account", "show"])

    assert arguments == [r"C:\CLI\az.cmd", "account", "show"]
    assert env is None


def test_prepare_leaves_everything_alone_when_tools_are_on_path(dirs):
    found = locator(dirs, on_path(az="/opt/bin/az", kubectl="/opt/bin/kubectl"))

    assert found.prepare(["kubectl", "get", "pods"]) == (["kubectl", "get", "pods"], None)


def test_prepare_prepends_bundled_and_downloaded_directories(dirs):
    bundled, tools = dirs
    az = make_tool(bundled, "az")
    make_tool(tools, "kubectl")
    make_tool(tools, "kubelogin")
    found = locator(dirs, path="/usr/bin:/bin")

    arguments, env = found.prepare(["az", "aks", "list"], {"PATH": "/usr/bin:/bin", "X": "1"})

    assert arguments == [az, "aks", "list"]
    assert env == {
        "PATH": os.pathsep.join([str(bundled), str(tools), "/usr/bin:/bin"]),
        "X": "1",
    }


def test_prepare_keeps_a_caller_environment_even_with_nothing_to_add(dirs):
    found = locator(dirs, on_path(az="/opt/bin/az"))

    assert found.prepare(["az"], {"PATH": "/x", "A": "b"}) == (["az"], {"PATH": "/x", "A": "b"})


def test_tools_directory_defaults_beside_the_token_cache(tmp_path):
    settings = Settings(_env_file=None, TOKEN_CACHE_DIR=str(tmp_path))

    assert settings.tools_directory() == os.path.join(str(tmp_path), "bin")
    assert Settings(_env_file=None, TOOLS_DIR="/opt/tools").tools_directory() == "/opt/tools"
    assert ToolLocator.from_settings(settings).bundled_dir == os.path.dirname(sys.executable)


@pytest.mark.asyncio
async def test_process_runner_runs_resolved_tools_with_the_extended_path(dirs, monkeypatch):
    bundled, _ = dirs
    az = make_tool(bundled, "az")
    spawned = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def fake_exec(*arguments, **options):
        spawned["arguments"] = list(arguments)
        spawned["env"] = options.get("env")
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    runner = AsyncProcessRunner(locator(dirs, path="/usr/bin"))

    result = await runner.run(["az", "version"], timeout=5)

    assert result.stdout == "ok"
    assert spawned["arguments"] == [az, "version"]
    assert spawned["env"]["PATH"] == os.pathsep.join([str(bundled), "/usr/bin"])
